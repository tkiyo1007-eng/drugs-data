# メーカー案内データ更新

厚生労働省の供給状況と、メーカーが公表する将来の販売予定は別の情報として管理する。
在庫がある間は「通常出荷」と「販売中止予定」が同時に成立するため、供給状況でメーカー案内の収集対象を絞らない。

## 生成ファイル

| ファイル | 用途 |
|---|---|
| `maker_announcements.json` | Web・iOSが参照する品目ごとの代表案内 |
| `maker_announcement_events.json` | 差し替え前を含む品目ごとの案内履歴 |
| `unmatched_maker_announcements.json` | 公式サイトから取得したがCSV品目と一致しなかった確認待ち案内 |
| `maker_collection_health.json` | 収集元ごとの取得件数・エラー |
| `manual_announcements.json` | 自動照合が難しい案内の共通手動登録 |

代表案内と履歴の `event_type` は次のいずれか。

- `discontinued`: 製品全体の販売・製造中止
- `package_discontinued`: 一部包装の中止
- `stopped`: 供給・出荷停止
- `limited`: 限定出荷・出荷調整
- `resumed`: 出荷再開・限定出荷解除
- `supply`: その他の供給案内
- `other`: 上記以外

「他社品販売中止に伴う限定出荷」は `limited` とし、自社品の販売中止にしない。

## 日次処理

`.github/workflows/update_drugs.yml` が毎日以下を実行する。

1. 厚労省データを更新
2. メーカー公式サイトから案内を収集
3. メーカー名・正規化商品名・規格を照合
4. 代表案内、履歴、未マッチ一覧、収集状態を更新
5. データ品質検査後にpush

収集元の複数同時失敗や総取得件数の急減は処理を失敗させる。単一メーカーの一時障害は
`maker_collection_health.json` に残し、他のデータ更新は継続する。

## 手動登録

自動収集が難しい案内は `manual_announcements.json` に追加する。商品名は
`drugs_app_ready.csv` の表記と完全一致させ、メーカー公式のHTTPS URLを使用する。
手動登録は自動照合結果より優先され、Web版・iOS版で共通利用される。

## 検証

```sh
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 scripts/validate_maker_announcements.py --min-count 300
```

Pull Requestとmainへのpushでは `.github/workflows/validate.yml` が同じ検証を実行する。
