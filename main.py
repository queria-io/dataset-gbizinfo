"""gBizINFO 法人活動情報の取得 + dbt build パイプライン.

経済産業省 gBizINFO のデータダウンロード機能から情報種別ごとの全件 CSV を取得し、
そのパスを dbt の var として渡して raw→stg→mart を構築する。
fdl checkout の作業場の DuckLake カタログ (FDL_WORKING) へ書き込み、
公開は fdl commit / fdl push が担う (scripts/build.sh)。

gBizINFO の各ファイル (基本情報・特許を除く) は日次更新される。鮮度を上げるため、
更新の頻度に応じて取得対象を 2 モードに分ける:

  full (月次・既定):
    基本情報・特許を含む全 8 種別を取得して全モデルをビルドする。
    基本情報 (Kihonjoho 約 1.7GB)・特許 (Tokkyojoho 約 1.2GB) は重いが
    変化が緩やかなため月次で十分。

  activity (日次): 環境変数 GBIZINFO_SYNC_MODE=activity で指定。
    補助金・調達・財務・職場・表彰・届出認定の活動 6 種別のみ取得し、
    `dbt build --exclude raw_gbizinfo_basic raw_gbizinfo_patent` で
    基本情報・特許層を据え置いたまま活動データと mart を再ビルドする。
    据え置く層は前回の full ビルドのテーブルをそのまま使う。
    既存カタログの raw_gbizinfo_basic / raw_gbizinfo_patent を参照するため、
    公開中のバージョンを fdl checkout してから実行する (build-fdl.sh が行う)。
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import duckdb
import httpx
from dbt.cli.main import dbtRunner

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())

BASE = "https://info.gbiz.go.jp/hojin"
DOWNLOAD_TOP = f"{BASE}/DownloadTop"
DOWNLOAD_URL = f"{BASE}/Download"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass(frozen=True)
class TypeSpec:
    """1 情報種別の取得・モデル化に必要な定義。"""

    key: str  # dbt var の suffix / 種別識別子 (例: basic)
    downfile: str  # DownloadTop の downfile パラメータ値


# 月次 full ビルドでのみ取得する重量級・低頻度更新の種別。
FULL_ONLY_TYPES: list[TypeSpec] = [
    TypeSpec("basic", "Kihonjoho"),
    TypeSpec("patent", "Tokkyojoho"),
]
# 日次更新する活動データ。dbt var 名は gbiz_<key>_csv。
ACTIVITY_TYPES: list[TypeSpec] = [
    TypeSpec("subsidy", "Hojokinjoho"),
    TypeSpec("procurement", "Chotatsujoho"),
    TypeSpec("finance", "Zaimujoho"),
    TypeSpec("workplace", "Shokubajoho"),
    TypeSpec("commendation", "Hyoshojoho"),
    TypeSpec("certification", "TodokedeNinteijoho"),
]
ALL_TYPES: list[TypeSpec] = [*FULL_ONLY_TYPES, *ACTIVITY_TYPES]

# activity モードで据え置く (再ビルドしない) full 専用種別の raw モデル。
FULL_ONLY_RAW_MODELS = [f"raw_gbizinfo_{spec.key}" for spec in FULL_ONLY_TYPES]


def _download_csv(client: httpx.Client, spec: TypeSpec, token: str, dest_dir: Path) -> Path:
    """1 種別の全件 CSV をストリーミングダウンロードしてローカルパスを返す。"""
    csv_path = dest_dir / f"{spec.downfile}.csv"
    logger.info("ダウンロード開始: %s (%s)", spec.key, spec.downfile)
    with client.stream(
        "POST",
        DOWNLOAD_URL,
        headers={"Referer": DOWNLOAD_TOP},
        data={
            "downfile": spec.downfile,
            "meta": "",
            "downenc": "UTF-8",
            "downtype": "csv",
            "apiToken": token,
        },
    ) as resp:
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "text/html" in content_type:
            # トークン不正やセッション切れの場合 200 でも HTML が返る
            raise RuntimeError(
                f"{spec.key}: CSV ではなく HTML が返りました "
                f"(トークン/セッションを確認: content-type={content_type})"
            )
        with open(csv_path, "wb") as f:
            for chunk in resp.iter_bytes(1 << 20):
                f.write(chunk)
    size = csv_path.stat().st_size
    logger.info("ダウンロード完了: %s (%d bytes)", csv_path.name, size)
    return csv_path


@contextmanager
def _ducklake_connect() -> Generator[duckdb.DuckDBPyConnection]:
    """fdl checkout の作業場の DuckLake をアタッチした新規 DuckDB セッションを開く。

    shared/scripts/build-fdl.sh が渡す環境変数 (作業場のカタログ ``FDL_WORKING`` と
    新しいデータファイルの置き場 ``FDL_DATA_PATH``) を使う。置き場が公開ストレージの
    ``data/`` のときは、build-fdl.sh が鍵を取り直す DuckDB の永続 secret を作っているので、
    この接続でも期限が切れるたびに取り直される。
    """
    catalog_path = os.environ["FDL_WORKING"]
    data_url = os.environ["FDL_DATA_PATH"]
    # ビルドが公開ストレージを読むときの名乗り。build-fdl.sh が queria-build として
    # 渡す。profiles.yml の config_options と同じ値を、こちらのセッションにも通す。
    # 接続を開くときにしか決められないので config= で渡す
    conn = duckdb.connect(
        ":memory:",
        config={"custom_user_agent": os.environ.get("QUERIA_USER_AGENT", "")},
    )
    try:
        conn.execute("INSTALL ducklake; LOAD ducklake;")
        conn.execute("INSTALL sqlite; LOAD sqlite;")
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        # 永続 secret の credential_chain はこの拡張にある
        conn.execute("INSTALL aws; LOAD aws;")
        conn.execute(
            f"ATTACH 'ducklake:{catalog_path}' AS gbizinfo "
            f"(DATA_PATH '{data_url}', OVERRIDE_DATA_PATH true, "
            f"DATA_INLINING_ROW_LIMIT 0, META_TYPE 'sqlite', "
            f"META_JOURNAL_MODE 'WAL', BUSY_TIMEOUT 5000)"
        )
        yield conn
    finally:
        conn.close()


def _full_only_raw_exists() -> bool:
    """full 専用種別の raw テーブルがすべて DuckLake に存在するか確認する。

    activity モードは基本情報・特許層を据え置くため、初回 (full 未実行) や
    新しい full 専用種別の追加直後はテーブルが揃わない。その場合は full に
    フォールバックさせ、据え置く層を確実に用意する。
    """
    with _ducklake_connect() as conn:
        for table_name in FULL_ONLY_RAW_MODELS:
            rows = conn.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_catalog = 'gbizinfo' AND table_name = ?",
                [table_name],
            ).fetchall()
            if not rows:
                return False
        return True


def main() -> None:
    target = os.environ.get("DBT_TARGET", sys.argv[1] if len(sys.argv) > 1 else "default")
    mode = os.environ.get("GBIZINFO_SYNC_MODE", "full").lower()
    token = os.environ["GBIZINFO_API_TOKEN"]

    if mode == "activity" and not _full_only_raw_exists():
        logger.warning(
            "activity モードだが %s が揃っていないため full にフォールバックします",
            ", ".join(FULL_ONLY_RAW_MODELS),
        )
        mode = "full"

    types = ACTIVITY_TYPES if mode == "activity" else ALL_TYPES
    logger.info("mode=%s: %d 種別を取得", mode, len(types))

    # CSV は一時ディレクトリへ。build 完了まで保持する (raw モデルが参照するため)。
    with tempfile.TemporaryDirectory(prefix="gbizinfo_") as tmp:
        dest = Path(tmp)
        downloaded: dict[str, Path] = {}
        with httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=httpx.Timeout(60.0, read=1800.0),
        ) as client:
            # DownloadTop を GET して JSESSIONID cookie を確立してから取得する
            client.get(DOWNLOAD_TOP).raise_for_status()
            for spec in types:
                downloaded[spec.key] = _download_csv(client, spec, token, dest)

        # raw モデルは var('gbiz_<key>_csv') を参照するため、全種別の var を
        # 定義する (activity モードで未取得の基本情報・特許はダミーパス。
        # raw_gbizinfo_basic / raw_gbizinfo_patent を --exclude するため実行時には
        # 参照されない)。
        unused = dest / "__unused__.csv"
        dbt_vars_parts = [
            f"gbiz_{spec.key}_csv: '{downloaded.get(spec.key, unused)}'"
            for spec in ALL_TYPES
        ]
        dbt_vars = "{" + ", ".join(dbt_vars_parts) + "}"

        build_cmd = ["build", "--target", target, "--vars", dbt_vars]
        if mode == "activity":
            build_cmd += ["--exclude", *FULL_ONLY_RAW_MODELS]

        dbt = dbtRunner()
        for cmd in (
            ["deps"],
            build_cmd,
            ["docs", "generate", "--target", target, "--vars", dbt_vars],
        ):
            result = dbt.invoke(cmd)
            if not result.success:
                raise SystemExit(f"dbt {' '.join(cmd)} failed")


if __name__ == "__main__":
    main()
