# Aurora Weather ☀️🌙

世界最高峰のデザイン品質を目指した、SwiftUI 製の天気予報 iOS アプリ。

## デザインのこだわり

- **生きた空** — 天候(晴れ/くもり/雨/雪/雷雨/霧)× 昼夜で変化するスカイグラデーション。雨粒・雪・星のまたたき・流れる雲・稲光まで、すべて `Canvas + TimelineView` によるステートレスな 60fps 描画。
- **ガラスモーフィズム** — `ultraThinMaterial` + ハイライト縁取り + ソフトシャドウで統一したカードシステム。背景の空に溶け込む。
- **情報の美しさ**
  - 10日間予報: 週全体レンジに対する各日の気温バー(温度で色が変わるグラデーション、今日は現在気温ドット付き)
  - Swift Charts による24時間気温カーブ(サンセットカラーのライン + エリアグラデーション)
  - 風向コンパス(36目盛り + スプリングアニメーションの矢印)
  - 日の出〜日の入りアーク上を移動する太陽
  - UVゲージ・湿度バー・気圧/体感温度のコメント付きカード
- **マイクロインタラクション** — スクロールで大きな気温表示が縮んでコンパクトヘッダーへ遷移、`contentTransition(.numericText())`、ハプティクス、Pull-to-Refresh。

## 機能

- 現在地の天気(CoreLocation、拒否時は東京にフォールバック)
- 都市検索(日本語対応・デバウンス付き)とマイシティ保存(スワイプ削除)
- 現在・24時間・10日間の予報、詳細メトリクス7種
- °C / °F 切り替え(設定は永続化)
- タイムゾーン対応(検索した都市の現地時刻で表示)

## アーキテクチャ

```
AuroraWeather/
├── App/            エントリポイント
├── Models/         APIレスポンス / ドメインモデル / WMOコード→天候マッピング
├── Services/       WeatherService(Open-Meteo)/ Geocoding / Location(async/await)
├── ViewModels/     WeatherViewModel(@Observable, MVVM)
├── Views/
│   ├── Sky/        背景グラデーション・パーティクル演出
│   ├── Components/ GlassCard
│   ├── Sections/   ヘッダー / 毎時 / チャート / 10日間 / 詳細グリッド
│   └── Search/     都市検索シート
└── Utilities/      ハプティクス・日付フォーマット
```

- **API**: [Open-Meteo](https://open-meteo.com/)(無料・APIキー不要)
- **要件**: Xcode 16+ / iOS 17.0+
- **依存パッケージ**: なし(すべて標準フレームワーク)

## 実行方法

1. `AuroraWeather/AuroraWeather.xcodeproj` を Xcode で開く
2. Signing & Capabilities で自分のチームを選択
3. シミュレータまたは実機で ⌘R

初回起動時に位置情報の許可を求められます。許可しない場合は東京の天気が表示され、右上の🔍から任意の都市を検索できます。
