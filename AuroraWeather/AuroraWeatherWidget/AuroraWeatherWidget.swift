import WidgetKit
import SwiftUI

// MARK: - タイムライン

struct WeatherEntry: TimelineEntry {
    let date: Date
    let placeName: String
    let weather: WeatherBundle?

    static let placeholder = WeatherEntry(date: .now, placeName: "東京", weather: nil)
}

struct WeatherTimelineProvider: TimelineProvider {
    private let service = WeatherService()

    func placeholder(in context: Context) -> WeatherEntry {
        .placeholder
    }

    func getSnapshot(in context: Context, completion: @escaping (WeatherEntry) -> Void) {
        Task {
            completion(await makeEntry())
        }
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<WeatherEntry>) -> Void) {
        Task {
            let entry = await makeEntry()
            // 30 分ごとに更新
            let next = Calendar.current.date(byAdding: .minute, value: 30, to: Date()) ?? Date().addingTimeInterval(1800)
            completion(Timeline(entries: [entry], policy: .after(next)))
        }
    }

    private func makeEntry() async -> WeatherEntry {
        let place = SharedStore.lastPlace()
        let weather = try? await service.fetch(latitude: place.latitude, longitude: place.longitude)
        return WeatherEntry(date: Date(), placeName: place.name, weather: weather)
    }
}

// MARK: - ウィジェット定義

struct AuroraWeatherWidget: Widget {
    let kind = "AuroraWeatherWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: WeatherTimelineProvider()) { entry in
            AuroraWeatherWidgetView(entry: entry)
        }
        .configurationDisplayName("現在の天気")
        .description("選択中の地点の天気と気温をひと目で。")
        .supportedFamilies([
            .systemSmall, .systemMedium,
            .accessoryCircular, .accessoryRectangular, .accessoryInline,
        ])
    }
}

// MARK: - ビュー

struct AuroraWeatherWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: WeatherEntry

    private var kind: WeatherKind { entry.weather?.kind ?? .partlyCloudy }
    private var isDay: Bool { entry.weather?.isDay ?? true }

    private var isAccessory: Bool {
        switch family {
        case .accessoryCircular, .accessoryRectangular, .accessoryInline:
            return true
        default:
            return false
        }
    }

    var body: some View {
        content
            .containerBackground(for: .widget) {
                if isAccessory {
                    AccessoryWidgetBackground()
                } else {
                    LinearGradient(
                        colors: kind.skyColors(isDay: isDay),
                        startPoint: .top,
                        endPoint: .bottom
                    )
                }
            }
    }

    @ViewBuilder
    private var content: some View {
        switch family {
        case .systemMedium:
            mediumView
        case .accessoryInline:
            inlineView
        case .accessoryCircular:
            circularView
        case .accessoryRectangular:
            rectangularView
        default:
            smallView
        }
    }

    // MARK: - ロック画面ウィジェット

    private var inlineView: some View {
        Label(
            "\(degrees(entry.weather?.temperature)) \(kind.label)",
            systemImage: kind.symbolName(isDay: isDay)
        )
    }

    private var circularView: some View {
        VStack(spacing: -1) {
            Image(systemName: kind.symbolName(isDay: isDay))
                .font(.system(size: 16, weight: .medium))
            Text(degrees(entry.weather?.temperature))
                .font(.system(size: 17, weight: .semibold, design: .rounded))
        }
        .widgetAccentable()
    }

    private var rectangularView: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(entry.placeName)
                .font(.caption2)
                .opacity(0.8)
                .lineLimit(1)
            HStack(spacing: 5) {
                Image(systemName: kind.symbolName(isDay: isDay))
                    .font(.caption)
                Text(degrees(entry.weather?.temperature))
                    .font(.headline)
                    .widgetAccentable()
            }
            if let weather = entry.weather {
                Text("↑\(degrees(weather.todayMax)) ↓\(degrees(weather.todayMin)) \(kind.label)")
                    .font(.caption2)
                    .opacity(0.85)
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var smallView: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(entry.placeName)
                .font(.footnote.weight(.semibold))
                .lineLimit(1)

            Text(degrees(entry.weather?.temperature))
                .font(.system(size: 40, weight: .light))

            Spacer(minLength: 0)

            Image(systemName: kind.symbolName(isDay: isDay))
                .symbolRenderingMode(.multicolor)
                .font(.title3)
            Text(kind.label)
                .font(.caption.weight(.medium))
                .lineLimit(1)
            if let weather = entry.weather {
                Text("最高\(degrees(weather.todayMax)) 最低\(degrees(weather.todayMin))")
                    .font(.caption2)
                    .opacity(0.85)
            }
        }
        .foregroundStyle(.white)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }

    private var mediumView: some View {
        HStack(alignment: .center, spacing: 14) {
            VStack(alignment: .leading, spacing: 2) {
                Text(entry.placeName)
                    .font(.footnote.weight(.semibold))
                    .lineLimit(1)
                Text(degrees(entry.weather?.temperature))
                    .font(.system(size: 40, weight: .light))
                Image(systemName: kind.symbolName(isDay: isDay))
                    .symbolRenderingMode(.multicolor)
                    .font(.title3)
                Text(kind.label)
                    .font(.caption.weight(.medium))
                    .lineLimit(1)
            }
            .frame(maxHeight: .infinity, alignment: .top)

            Spacer(minLength: 0)

            if let weather = entry.weather {
                HStack(spacing: 14) {
                    ForEach(hourSample(weather)) { hour in
                        VStack(spacing: 5) {
                            Text(hour.date.hourLabel(in: weather.timeZone))
                                .font(.caption2)
                                .opacity(0.8)
                            Image(systemName: hour.kind.symbolName(isDay: hour.isDay))
                                .symbolRenderingMode(.multicolor)
                                .font(.callout)
                            Text("\(Int(hour.temperature.rounded()))°")
                                .font(.caption.weight(.semibold))
                        }
                    }
                }
            }
        }
        .foregroundStyle(.white)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func hourSample(_ weather: WeatherBundle) -> [HourForecast] {
        // 2 時間おきに 4 コマ
        let candidates = weather.hours.dropFirst()
        return Array(candidates.enumerated().filter { $0.offset % 2 == 0 }.map(\.element).prefix(4))
    }

    private func degrees(_ celsius: Double?) -> String {
        guard let celsius else { return "--°" }
        return "\(Int(celsius.rounded()))°"
    }
}
