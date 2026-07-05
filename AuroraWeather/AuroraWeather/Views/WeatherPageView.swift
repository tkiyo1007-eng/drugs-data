import SwiftUI

/// 1つの地点の天気を表示するページ(スワイプページングの1枚)
struct WeatherPageView: View {
    let place: SavedPlace
    let viewModel: WeatherViewModel

    @State private var scrollOffset: CGFloat = 0
    @State private var showRadar = false

    private var collapseProgress: Double {
        (Double(-scrollOffset) / 140).clamped(to: 0...1)
    }

    var body: some View {
        Group {
            if let weather = viewModel.bundles[place.id] {
                content(weather)
            } else if viewModel.errors[place.id] != nil {
                ErrorStateView(message: viewModel.errors[place.id] ?? "") {
                    Task { await viewModel.ensureLoaded(place.id, force: true) }
                }
            } else {
                LoadingStateView()
            }
        }
        .sheet(isPresented: $showRadar) {
            RadarSheet(place: place)
        }
    }

    private func content(_ weather: WeatherBundle) -> some View {
        ScrollView(showsIndicators: false) {
            VStack(spacing: 14) {
                GeometryReader { proxy in
                    Color.clear.preference(
                        key: PageScrollOffsetKey.self,
                        value: proxy.frame(in: .named("weatherScroll")).minY
                    )
                }
                .frame(height: 0)

                CurrentHeaderView(
                    placeName: place.name,
                    isCurrentLocation: place.isCurrentLocation,
                    weather: weather,
                    degrees: viewModel.degrees,
                    collapseProgress: collapseProgress
                )
                .padding(.top, 54)

                if viewModel.errors[place.id] != nil {
                    OfflineBanner(fetchedAt: weather.fetchedAt, timeZone: weather.timeZone)
                        .padding(.horizontal, 16)
                }

                Group {
                    HourlyForecastCard(weather: weather, degrees: viewModel.degrees)

                    RadarCardButton { showRadar = true }

                    TemperatureChartCard(weather: weather, units: viewModel.units)
                    DailyForecastCard(weather: weather, degrees: viewModel.degrees)
                    DetailsGrid(weather: weather, degrees: viewModel.degrees)

                    Text("データ提供: Open-Meteo.com / RainViewer.com")
                        .font(.caption2)
                        .foregroundStyle(.white.opacity(0.45))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                }
                .padding(.horizontal, 16)
            }
            .padding(.bottom, 30)
        }
        .coordinateSpace(name: "weatherScroll")
        .onPreferenceChange(PageScrollOffsetKey.self) { value in
            scrollOffset = value
        }
        .refreshable {
            Haptics.soft()
            await viewModel.ensureLoaded(place.id, force: true)
        }
    }
}

private struct PageScrollOffsetKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

// MARK: - オフラインバナー

struct OfflineBanner: View {
    let fetchedAt: Date
    let timeZone: TimeZone

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "wifi.slash")
                .font(.caption)
            Text("通信できないため \(fetchedAt.timeLabel(in: timeZone)) 時点の情報を表示中")
                .font(.caption.weight(.medium))
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(Color.orange.opacity(0.45), in: Capsule())
        .accessibilityElement(children: .combine)
    }
}

// MARK: - 雨雲レーダーへの導線カード

struct RadarCardButton: View {
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            GlassCard(title: "雨雲レーダー", systemImage: "cloud.rain") {
                HStack {
                    Text("周辺の雨雲の動きと1時間先の予測を見る")
                        .font(.callout)
                        .foregroundStyle(.white)
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(.white.opacity(0.6))
                }
            }
        }
        .buttonStyle(.plain)
        .accessibilityLabel("雨雲レーダーを開く")
    }
}

// MARK: - ローディング / エラー状態

struct LoadingStateView: View {
    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "cloud.sun.fill")
                .symbolRenderingMode(.multicolor)
                .font(.system(size: 56))
                .symbolEffect(.pulse)
            Text("天気を取得しています…")
                .font(.callout)
                .foregroundStyle(.white.opacity(0.85))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct ErrorStateView: View {
    let message: String
    let retry: () -> Void

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "wifi.exclamationmark")
                .font(.system(size: 44))
                .foregroundStyle(.white.opacity(0.9))
            Text(message)
                .font(.callout)
                .foregroundStyle(.white.opacity(0.85))
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
            Button(action: retry) {
                Text("再試行")
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 24)
                    .padding(.vertical, 10)
                    .background(.ultraThinMaterial, in: Capsule())
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
