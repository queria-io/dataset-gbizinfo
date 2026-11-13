#!/usr/bin/env bash
set -euo pipefail
# activity モードは前回 full ビルドの raw_gbizinfo_basic を据え置いて参照するので、
# 公開中のバージョンが前提。build-fdl.sh は fdl checkout から始まる
# 記述 (*.table.yml) の無いテーブル (raw と stg のビュー) は掲載しない
export FDL_UNDESCRIBED="${FDL_UNDESCRIBED:-unlisted}"
exec "$(dirname "$0")/../shared/scripts/build-fdl.sh" "$@"
