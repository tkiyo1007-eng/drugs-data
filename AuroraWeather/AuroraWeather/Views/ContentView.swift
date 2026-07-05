import SwiftUI

struct ContentView: View {
    @State private var viewModel = WeatherViewModel()
    @State private var showSearch = false
    @State private var scrollOffset: CGFloat = 0

    /// ヘッダー折りたたみの進捗(0〜1)
    private var collapseProgress: Double {
        (Double(-scrollOffset) / 140).clamped(to: 0...1)
    }

    var body: some View {
        ZStack {
            SkyBackground(
                kind: viewModel.weather?.kind ?? .partlyCloudy,
                isDay: viewModel.weather?.isDay ?? true
            )

            switch viewModel.phase {
            case .idle, .loading:
                if viewModel.weather == nil {
                    loadingView
                }
            case .failed(let message):
                errorView(message)
            case .loaded:
                EmptyView()
            }

            if let weather = viewModel.weather {
                weatherScroll(weather)
            }

            topBar
        }
        .sheet(isPresented: $showSearch) {
            CitySearchView(viewModel: viewModel)
                .presentationDetents([.large])
        }
        .task {
            await viewModel.loadInitial()
        }
    }

    // MARK: - メインスクロール

    private func weatherScroll(_ weather: WeatherBundle) -> some View {
        ScrollView(showsIndicators: false) {
            VStack(spacing: 14) {
                // スクロール量の計測
                GeometryReader { proxy in
                    Color.clear.preference(
                        key: ScrollOffsetKey.self,
                        value: proxy.frame(in: .named("scroll")).minY
                    )
                }
                .frame(height: 0)

                CurrentHeaderView(
                    placeName: viewModel.place.name,
                    isCurrentLocation: viewModel.place.isCurrentLocation,
                    weather: weather,
                    degrees: viewModel.degrees,
                    collapseProgress: collapseProgress
                )
                .padding(.top, 54)
                .padding(.bottom, 8)

                Group {
                    HourlyForecastCard(weather: weather, degrees: viewModel.degrees)
                    TemperatureChartCard(weather: weather, units: viewModel.units)
                    DailyForecastCard(weather: weather, degrees: viewModel.degrees)
                    DetailsGrid(weather: weather, degrees: viewModel.degrees)

                    Text("データ提供: Open-Meteo.com")
                        .font(.caption2)
                        .foregroundStyle(.white.opacity(0.45))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                }
                .padding(.horizontal, 16)
            }
        }
        .coordinateSpace(name: "scroll")
        .onPreferenceChange(ScrollOffsetKey.self) { value in
            scrollOffset = value
        }
        .refreshable {
            Haptics.soft()
            await viewModel.refresh()
        }
        .transition(.opacity)
    }

    // MARK: - トップバー

    private var topBar: some View {
        VStack {
            HStack {
                Menu {
                    Picker("単位", selection: Bindable(viewModel).units) {
                        ForEach(UnitSystem.allCases) { unit in
                            Text(unit.label).tag(unit)
                        }
                    }
                } label: {
                    Image(systemName: "ellipsis.circle")
                        .font(.title3)
                        .foregroundStyle(.white)
                        .frame(width: 40, height: 40)
                        .background(.ultraThinMaterial, in: Circle())
                }

                Spacer()

                Button {
                    Haptics.selection()
                    showSearch = true
                } label: {
                    Image(systemName: "magnifyingglass")
                        .font(.title3)
                        .foregroundStyle(.white)
                        .frame(width: 40, height: 40)
                        .background(.ultraThinMaterial, in: Circle())
                }
            }
            .padding(.horizontal, 16)
            Spacer()
        }
    }

    // MARK: - ローディング / エラー

    private var loadingView: some View {
        VStack(spacing: 16) {
            Image(systemName: "cloud.sun.fill")
                .symbolRenderingMode(.multicolor)
                .font(.system(size: 56))
                .symbolEffect(.pulse)
            Text("天気を取得しています…")
                .font(.callout)
                .foregroundStyle(.white.opacity(0.85))
        }
    }

    private func errorView(_ message: String) -> some View {
        VStack(spacing: 14) {
            Image(systemName: "wifi.exclamationmark")
                .font(.system(size: 44))
                .foregroundStyle(.white.opacity(0.9))
            Text(message)
                .font(.callout)
                .foregroundStyle(.white.opacity(0.85))
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
            Button {
                Task { await viewModel.refresh() }
            } label: {
                Text("再試行")
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 24)
                    .padding(.vertical, 10)
                    .background(.ultraThinMaterial, in: Capsule())
            }
        }
    }
}

private struct ScrollOffsetKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

#Preview {
    ContentView()
}
