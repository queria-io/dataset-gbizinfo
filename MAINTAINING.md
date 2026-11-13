# 運用メモ

## 取得方式

gBizINFO のデータダウンロード (DownloadTop) から全件 CSV を取得する。各ファイルは
日次更新されるため、更新頻度に応じて 2 モードに分けて鮮度を上げている。

- full (月次): 基本情報・特許を含む全 8 種別を取得して全モデルを再ビルドする
  (基本情報 Kihonjoho 約 1.7GB・特許 Tokkyojoho 約 1.2GB は重いが変化が緩やかなため月次)。
  ワークフロー: `.github/workflows/sync.yml`
- activity (日次): 活動 6 種別 (補助金・調達・財務・職場・表彰・届出認定) のみ取得し、
  `dbt build --exclude raw_gbizinfo_basic raw_gbizinfo_patent` で基本情報・特許層を
  据え置いたまま活動データと mart を再ビルドする。
  ワークフロー: `.github/workflows/sync-activity.yml`

モードは環境変数 `GBIZINFO_SYNC_MODE` (`full` 既定 / `activity`) で切り替える。
activity モードでも基本情報・特許テーブルが揃っていなければ full にフォールバックする。

## セットアップと実行

```bash
git submodule update --init
uv sync
echo "FDL_TOKEN=<Queria の API トークン>" > .env
echo "GBIZINFO_API_TOKEN=<gBizINFO アクセストークン>" >> .env

scripts/build.sh                    # ビルドして Queria に公開する
```

`scripts/build.sh` は公開中のバージョンを `fdl checkout` してから取り込み・ビルドし、`fdl commit` と `fdl push` で公開する（`shared/scripts/build-fdl.sh`）。GitHub Actions では Queria のトークンを OIDC で取得する。

`GBIZINFO_API_TOKEN` は gBizINFO の API 利用申請で発行されるアクセストークン
(REST API と データダウンロードで共通)。

