import SwiftUI
import Observation
import CoreLocation

// MARK: - Watch 用ビューモデル

@Observable
final class WatchWeatherModel {
    var weather: WeatherBundle?
    var placeName: String = SharedStore.lastPlace().name
    var failed = false
    var isLoading = false

    private let service = WeatherService()
    private let locationService = LocationService()

    @MainActor
    func load() async {
        guard !isLoading else { return }
        isLoading = true
        defer { isLoading = false }
        failed = false

        // 現在地が取れればそれを、ダメなら前回の地点(既定: 東京)を使う
        var place = SharedStore.lastPlace()
        if let location = try? await locationService.currentLocation() {
            place = SavedPlace(
                name: "現在地",
                detail: "",
                latitude: location.coordinate.latitude,
                longitude: location.coordinate.longitude,
                isCurrentLocation: true
            )
        }
        placeName = place.name

        do {
            weather = try await service.fetch(latitude: place.latitude, longitude: place.longitude)
        } catch {
            if weather == nil { failed = true }
        }
    }
}

// MARK: - メイン画面

struct WatchWeatherView: View {
    @State private var model = WatchWeatherModel()

    var body: some View {
        Group {
            if let weather = model.weather {
                content(weather)
            } else if model.failed {
                VStack(spacing: 10) {
                    Image(systemName: "wifi.exclamationmark")
                        .font(.title2)
                    Text("取得に失敗しました")
                        .font(.footnote)
                    Button("再試行") {
                        Task { await model.load() }
                    }
                }
            } else {
                ProgressView("取得中…")
            }
        }
        .task { await model.load() }
    }

    private func content(_ weather: WeatherBundle) -> some View {
        ZStack {
            LinearGradient(
                colors: weather.kind.skyColors(isDay: weather.isDay),
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()

            ScrollView {
                VStack(spacing: 10) {
                    header(weather)
                    hourlyCard(weather)
                    dailyCard(weather)

                    Button {
                        Task { await model.load() }
                    } label: {
                        Label("更新", systemImage: "arrow.clockwise")
                            .font(.caption2)
                    }
                    .buttonStyle(.bordered)
                    .tint(.white.opacity(0.4))
                }
                .padding(.horizontal, 4)
            }
        }
        .foregroundStyle(.white)
    }

    private func header(_ weather: WeatherBundle) -> some View {
        VStack(spacing: 1) {
            Text(model.placeName)
                .font(.footnote.weight(.medium))
                .opacity(0.85)
            Text("\(Int(weather.temperature.rounded()))°")
                .font(.system(size: 46, weight: .light))
            HStack(spacing: 5) {
                Image(systemName: weather.kind.symbolName(isDay: weather.isDay))
                    .symbolRenderingMode(.multicolor)
                Text(weather.kind.label)
            }
            .font(.footnote)
            Text("最高 \(Int(weather.todayMax.rounded()))°  最低 \(Int(weather.todayMin.rounded()))°")
                .font(.caption2)
                .opacity(0.85)
                .padding(.top, 1)
        }
        .accessibilityElement(children: .combine)
    }

    private func hourlyCard(_ weather: WeatherBundle) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            ForEach(Array(weather.hours.dropFirst().prefix(6))) { hour in
                HStack {
                    Text(hour.date.hourLabel(in: weather.timeZone))
                        .font(.caption2)
                        .opacity(0.8)
                        .frame(width: 42, alignment: .leading)
                    Image(systemName: hour.kind.symbolName(isDay: hour.isDay))
                        .symbolRenderingMode(.multicolor)
                        .font(.caption)
                    Spacer()
                    if let probability = hour.precipitationProbability, probability >= 20 {
                        Text("\(Int(probability))%")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(Color(red: 0.55, green: 0.85, blue: 1.0))
                    }
                    Text("\(Int(hour.temperature.rounded()))°")
                        .font(.caption.weight(.semibold))
                        .frame(width: 32, alignment: .trailing)
                }
                .accessibilityElement(children: .combine)
            }
        }
        .padding(10)
        .background(.white.opacity(0.13), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }

    private func dailyCard(_ weather: WeatherBundle) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            ForEach(Array(weather.days.prefix(5))) { day in
                HStack {
                    Text(day.date.weekdayLabel(in: weather.timeZone))
                        .font(.caption2)
                        .opacity(0.8)
                        .frame(width: 26, alignment: .leading)
                    Image(systemName: day.kind.symbolName(isDay: true))
                        .symbolRenderingMode(.multicolor)
                        .font(.caption)
                    Spacer()
                    Text("\(Int(day.tempMin.rounded()))°")
                        .font(.caption2)
                        .opacity(0.65)
                    Text("\(Int(day.tempMax.rounded()))°")
                        .font(.caption.weight(.semibold))
                        .frame(width: 30, alignment: .trailing)
                }
                .accessibilityElement(children: .combine)
            }
        }
        .padding(10)
        .background(.white.opacity(0.13), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

#Preview {
    WatchWeatherView()
}
