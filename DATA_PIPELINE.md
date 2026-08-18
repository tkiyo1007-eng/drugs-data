# メーカー案内データ更新

厚生労働省の供給状況と、メーカーが公表する将来の販売予定は別の情報として管理する。
在庫がある間は「通常出荷」と「販売中止予定」が同時に成立するため、供給状況でメーカー案内の収集対象を絞らない。

## 生成ファイル

| ファイル | 用途 |
|---|---|
| `maker_announcements.json` | Web・iOSが参照する品目ごとの代表案内 |
| `maker_announcement_events.json` | 差し替え前を含む品目ごとの案内履歴 |
| `unmatched_maker_announcements.json` | 公式サイトから取得したが、既存・深掘り・手動登録を含むいずれのCSV品目にも一致しなかった確認待ち案内 |
| `maker_collection_health.json` | 収集元ごとの取得件数・エラー |
| `manual_announcements.json` | 自動照合が難しい案内の共通手動登録 |
| `manual_announcement_groups.json` | 1つの公式文書に複数品目が掲載される場合の対象品目一覧 |
| `maker_links.json` | Web・iOS共通のメーカー公式供給情報ページ |
| `featured_products.json` | Web・iOS共通の注目製品と検索語 |
| `industry_topics.json` | Web・iOS共通の業界トピック |

代表案内と履歴の `event_type` は次のいずれか。

- `discontinued`: 製品全体の販売・製造中止
- `package_discontinued`: 一部包装の中止
- `stopped`: 供給・出荷停止
- `limited`: 限定出荷・出荷調整
- `resumed`: 出荷再開・限定出荷解除
- `supply`: その他の供給案内
- `other`: 上記以外

「他社品販売中止に伴う限定出荷」は `limited` とし、自社品の販売中止にしない。
同じ品目に複数の案内がある場合、製品全体の販売中止、一部包装の中止、一時的な
供給案内の順に代表案内を選ぶ。同じ種別では新しい案内を優先する。代表に選ばれない
旧報・続報も照合済みとして扱い、未照合一覧には残さない。

## 日次処理

`.github/workflows/update_drugs.yml` が毎日以下を実行する。

1. 厚労省データを更新
2. メーカー欄に混入した医療用ガス共通文書の説明を除去（実在会社名は保持）
3. CSVの列・件数・必須値・供給区分・YJコード・日付・鮮度を検査
4. 前回のメーカー補足・ライフサイクルから新CSVに存在しない参照を除き、再検証
5. CSVから生成する品目別・日別・注目製品ページを更新し、検証済み厚労省コアを先にpush
6. メーカー公式サイトから案内を一時領域へ収集
7. メーカー名・正規化商品名・規格を照合し、一時領域の4 JSONをまとめて検証
8. 検証成功時だけ代表案内、履歴、未マッチ一覧、収集状態を置換して追加push

メーカー補足情報は厚労省コアとは独立した任意の更新である。取得元の一時障害、
HTML変更、または品質検査の失敗時は、前回の完全な検証済み4 JSONを維持し、すでに
検証した最新の厚労省CSV・version・CSV由来ページの公開を継続する。初回構築などで
前回の4 JSONが揃っていない場合は、安全なフォールバックがないため処理を失敗させる。
前回値はコア公開前に `scripts/reconcile_optional_data.py` が新CSVとの参照整合性を確認する。
手動登録元の `manual_announcement_groups.json` に削除済み品目が残っていても、この
コア整合処理は失敗させない。手動登録の厳格検査は後段のメーカー補足更新と通常CIで行う。
ネットワーク更新に失敗して前回値を採用した日は、メーカー情報から派生するライフサイクル・
注目製品ページ・包装抽出を再実行せず、コア公開時点の検証済み成果物を維持する。この境界は
`scripts/update_maker_enrichment.py` のGitHub Actions出力が担う。

供給状況の変化ログから作る `resolution_stats.json` と、全品目から算出する
`crisis_index.json` も日次コミットの対象に含める。計算だけ実行してGitの追加対象から
漏らすと公開値が更新されないため、ワークフローの生成処理と `git add` は同時に更新する。

収集元の複数同時失敗や総取得件数の急減は処理を失敗させる。単一メーカーの一時障害は
`maker_collection_health.json` に残し、他のデータ更新は継続する。

GitHub ActionsはUTCで動くが、公開データの確認日・生成日・日次統計は利用者と厚労省
データの基準に合わせて `Asia/Tokyo` の暦日で記録する。収集元ページで同じPDFが
複数箇所に掲載されていても、メーカーとURLの組み合わせで一意化し、取得件数や
未マッチ確認待ちを水増ししない。総取得件数が前回の50%未満、または各収集元が
前回の20%未満へ急減した場合も、少量だけ取得できた状態を成功扱いせず更新を停止する。

## 手動登録

自動収集が難しい案内は `manual_announcements.json` に追加する。商品名は
`drugs_app_ready.csv` の表記と完全一致させ、メーカー公式のHTTPS URLを使用する。
手動登録は自動照合結果より優先され、Web版・iOS版で共通利用される。
1つのPDFに複数品目が掲載され、タイトルだけでは対象規格を特定できない場合は
`manual_announcement_groups.json` の `products` に対象商品名を列挙し、共通の案内を
`announcement` に1回だけ記録する。個別登録はグループ登録より優先される。

## 検証

```sh
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 scripts/validate_supply_data.py --csv drugs_app_ready.csv
python3 scripts/validate_maker_announcements.py --min-count 300
python3 scripts/validate_shared_content.py
```

Pull Requestとmainへのpushでは `.github/workflows/validate.yml` が同じ検証を実行する。
日次更新ではさらに、収集確認日が日本時間の実行日と一致することを検査する。代表案内と
履歴の参照整合性、収集状態の型・件数、未マッチ案内の重複URLも公開前に検査する。
メーカー案内の `announced_at` は一次資料の精度を保持し、実在する `YYYY-MM` または
`YYYY-MM-DD` を許可する。`checked`、`first_seen`、`last_checked` は日次運用の時刻なので
引き続き実在する `YYYY-MM-DD` のみを許可する。
