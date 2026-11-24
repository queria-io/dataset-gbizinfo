#!/usr/bin/env bash
set -euo pipefail
# activity モードは前回 full ビルドの raw_gbizinfo_basic を据え置いて参照するので、
# 公開中のバージョンが前提。build-fdl.sh は fdl checkout から始まる
# 説明 (<model>.tabledoc.yml) の無いテーブルは Queria の一覧と検索に出さない
export FDL_UNDESCRIBED="${FDL_UNDESCRIBED:-hidden}"
exec "$(dirname "$0")/../shared/scripts/build-fdl.sh" "$@"
