import SwiftUI

/// 画面上部の現在気温ヘッダー。スクロール量に応じて縮小・フェードする。
struct CurrentHeaderView: View {
    let placeName: String
    let isCurrentLocation: Bool
    let weather: WeatherBundle
    let degrees: (Double) -> String
    let collapseProgress: Double // 0 = 展開, 1 = 折りたたみ

    var body: some View {
        VStack(spacing: 4) {
            HStack(spacing: 5) {
                if isCurrentLocation {
                    Image(systemName: "location.fill")
                        .font(.subheadline)
                }
                Text(placeName)
                    .font(.title2.weight(.medium))
            }
            .foregroundStyle(.white)
            .shadow(color: .black.opacity(0.25), radius: 6, y: 2)

            ZStack {
                // 展開時: 大きな気温
                VStack(spacing: 2) {
                    Text(degrees(weather.temperature))
                        .font(.system(size: 108, weight: .thin))
                        .kerning(-2)
                        .foregroundStyle(
                            LinearGradient(
                                colors: [.white, .white.opacity(0.75)],
                                startPoint: .top,
                                endPoint: .bottom
                            )
                        )
                        .shadow(color: .black.opacity(0.20), radius: 12, y: 6)
                        .contentTransition(.numericText())

                    HStack(spacing: 8) {
                        Image(systemName: weather.kind.symbolName(isDay: weather.isDay))
                            .symbolRenderingMode(.multicolor)
                        Text(weather.kind.label)
                    }
                    .font(.title3.weight(.medium))
                    .foregroundStyle(.white.opacity(0.92))

                    HStack(spacing: 14) {
                        Text("最高 \(degrees(weather.todayMax))")
                        Text("最低 \(degrees(weather.todayMin))")
                    }
                    .font(.callout.weight(.medium))
                    .foregroundStyle(.white.opacity(0.85))
                    .padding(.top, 2)
                }
                .opacity(1 - collapseProgress * 1.6)
                .scaleEffect(1 - collapseProgress * 0.28, anchor: .top)

                // 折りたたみ時: コンパクト表示
                HStack(spacing: 8) {
                    Text(degrees(weather.temperature))
                    Text("|")
                        .foregroundStyle(.white.opacity(0.5))
                    Text(weather.kind.label)
                }
                .font(.title3.weight(.medium))
                .foregroundStyle(.white.opacity(0.95))
                .opacity((collapseProgress - 0.6) * 2.5)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 8)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(placeName)、\(weather.kind.label)、現在\(degrees(weather.temperature))、最高\(degrees(weather.todayMax))、最低\(degrees(weather.todayMin))")
    }
}
