# gBizINFO

経済産業省 [gBizINFO](https://info.gbiz.go.jp/) の法人活動情報を、SQL で検索・集計できるテーブルにしたデータセットです。法人番号ごとの基本情報（資本金・従業員数・設立年・業種）と、補助金・調達・財務・職場情報・表彰・届出と認定・特許の実績を収録しています。法人番号（`corporate_number`）で houjin_bangou・edinet・p_portal と結合できます。

## 出典と利用条件

- gBizINFO の「データダウンロード」の全件データ（8 種類）を加工して作成しています
- 出典：gBizINFO（経済産業省）。gBizINFO 利用規約に基づき出典を明記して再配布しています
- 最新性・正確性・完全性等が保証されたものではありません

## テーブル

| テーブル | 内容 |
| --- | --- |
| `main.mart_gbizinfo_company` | 1 法人 1 行の活動のまとめ（基本情報、補助金と調達の集計、最新の財務、職場の指標） |
| `main.mart_gbizinfo_finance` | 財務指標の推移（法人 × 回次、1 法人あたり直近 5 期まで） |
| `main.mart_gbizinfo_workplace` | 職場情報（1 法人 1 行、女性活躍と両立支援の公表項目） |
| `main.mart_gbizinfo_subsidy` | 補助金の交付実績（1 件 1 行） |
| `main.mart_gbizinfo_procurement` | 国の調達（受注）の実績（1 件 1 行） |
| `main.mart_gbizinfo_commendation` | 表彰の実績（1 件 1 行） |
| `main.mart_gbizinfo_certification` | 届出・認定の実績（1 件 1 行） |
| `main.mart_gbizinfo_patent` | 特許・意匠・商標の登録実績（1 件 1 行） |

法人の名称と所在地は houjin_bangou にあります。所在地で絞るときは `corporate_number` で houjin_bangou と結合してください。

## 使い方

日野市に本店がある法人を、補助金の交付額の多い順に並べる:

```sql
SELECT h.name, c.subsidy_count, c.subsidy_total_amount
FROM gbizinfo.main.mart_gbizinfo_company AS c
JOIN houjin_bangou.main.mart_houjin_bangou AS h USING (corporate_number)
WHERE h.lg_code = '132128' AND c.subsidy_count > 0
ORDER BY c.subsidy_total_amount DESC;
```

## 財務情報の期の扱い

財務情報は 1 法人あたり直近 5 期分を回次（`period_number`）0〜4 で持ちます（0 が最新）。ただし gBizINFO が返す事業年度の表記は最新期の分しか無く、どの回次の行にも同じ文字列（例「第20期（自 2025年４月１日 至 2026年３月31日）」）が入ります。

そのため、この表記から最新期の期末日 `latest_period_end` を取り出し（和暦も西暦に変換します）、そこから回次の分だけ年をさかのぼった `period_end_estimated` を付けています。後者は推定値で、決算期を変更した法人ではずれます。収録している 24,294 行すべてで期末日を取り出せています（2026-08 時点）。

収益の列は業種で分かれます。売上高（`net_sales`）が空の 4,454 行のうち 3,843 行は、営業収益・営業収入・営業総収入・経常収益・正味収入保険料のいずれかで報告しているので、これら 5 列も持っています（2026-08 時点）。売上高だけを集計すると、銀行・保険・鉄道・不動産などが抜けます。`operating_receipts` は「営業収入」で、利益ではなく収入です。

## 職場情報の埋まり方

職場情報は女性活躍推進法・次世代育成支援対策推進法に基づく公表項目で、届け出るかどうかも、どの項目を埋めるかも法人が決めます。gBizINFO は 1 項目も届け出ていない法人も名称だけの行として返すため、`mart_gbizinfo_workplace` は値を 1 つ以上報告している法人に絞っています（149,483 法人のうち 33,049 法人、2026-08 時点）。

絞ったあとも、項目ごとに報告している法人の数が大きく違います（収録 33,049 法人に対する割合、2026-08 時点）。

| 項目 | 報告法人 | 割合 |
| --- | ---: | ---: |
| 女性労働者の割合 | 21,497 | 65.0% |
| 平均継続勤務年数 (男性) | 14,566 | 44.1% |
| 女性管理職人数 | 14,041 | 42.5% |
| 女性役員人数 | 8,438 | 25.5% |
| 従業員の平均年齢 | 2,715 | 8.2% |
| 月平均所定外労働時間 | 2,700 | 8.2% |
| 育児休業対象者数 (男性) | 2,520 | 7.6% |

項目を組み合わせて集計すると母数がさらに小さくなります。割合を出すときは、その項目を報告した法人を母数にしてください。

- 継続勤務年数と女性労働者比率には、対象の労働者区分の列（`avg_service_years_scope`・`female_ratio_scope`）があります。数値の範囲ではなく、その数字が対象とする労働者の区分で、法人によって違います。法人間で比べるときはこの列で統一してください。`avg_service_years_scope` は 正社員／その他／対象とする労働者すべて／基幹的な職種、`female_ratio_scope` は 正社員／その他／基幹的な職種 のいずれかです
- 区分だけ選んで数値を報告していない法人（935 法人）は収録していません。収録した法人でも、`avg_service_years_scope` があって年数が空の行はあります
- 比率の列（`female_manager_ratio`・`female_officer_ratio`・`childcare_leave_ratio_male`・`childcare_leave_ratio_female`）は人数から算出したもので、分母が 0 の行は空です。育児休業取得率は対象者と取得者を数える年度がずれる法人があり、100% を超える行が男性 12 件・女性 47 件あります（2026-08 時点）

## 更新

基本情報と特許は月 1 回、それ以外の活動のデータは毎日取り込みます。
