import SwiftUI

/// 10 日間予報。週全体の最高/最低に対する各日のレンジをグラデーションバーで表す。
struct DailyForecastCard: View {
    let weather: WeatherBundle
    let degrees: (Double) -> String

    private var weekMin: Double { weather.days.map(\.tempMin).min() ?? 0 }
    private var weekMax: Double { weather.days.map(\.tempMax).max() ?? 1 }

    var body: some View {
        GlassCard(title: "10日間予報", systemImage: "calendar") {
            VStack(spacing: 0) {
                ForEach(Array(weather.days.enumerated()), id: \.element.id) { index, day in
                    DailyRow(
                        day: day,
                        isToday: index == 0,
                        weekMin: weekMin,
                        weekMax: weekMax,
                        currentTemperature: index == 0 ? weather.temperature : nil,
                        timeZone: weather.timeZone,
                        degrees: degrees
                    )
                    if index < weather.days.count - 1 {
                        Divider()
                            .overlay(Color.white.opacity(0.12))
                    }
                }
            }
        }
    }
}

private struct DailyRow: View {
    let day: DayForecast
    let isToday: Bool
    let weekMin: Double
    let weekMax: Double
    let currentTemperature: Double?
    let timeZone: TimeZone
    let degrees: (Double) -> String

    var body: some View {
        HStack(spacing: 12) {
            Text(isToday ? "今日" : day.date.weekdayLabel(in: timeZone))
                .font(.callout.weight(isToday ? .bold : .medium))
                .foregroundStyle(.white)
                .frame(width: 44, alignment: .leading)

            VStack(spacing: 1) {
                Image(systemName: day.kind.symbolName(isDay: true))
                    .symbolRenderingMode(.multicolor)
                    .font(.body)
                    .frame(height: 22)
                if let probability = day.precipitationProbability, probability >= 20 {
                    Text("\(Int(probability))%")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(Color(red: 0.55, green: 0.85, blue: 1.0))
                }
            }
            .frame(width: 40)

            Text(degrees(day.tempMin))
                .font(.callout.weight(.medium))
                .foregroundStyle(.white.opacity(0.6))
                .frame(width: 38, alignment: .trailing)

            TemperatureRangeBar(
                weekMin: weekMin,
                weekMax: weekMax,
                dayMin: day.tempMin,
                dayMax: day.tempMax,
                marker: currentTemperature
            )
            .frame(height: 5)

            Text(degrees(day.tempMax))
                .font(.callout.weight(.semibold))
                .foregroundStyle(.white)
                .frame(width: 38, alignment: .trailing)
        }
        .padding(.vertical, 11)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityText)
    }

    private var accessibilityText: String {
        var text = isToday ? "今日" : "\(day.date.weekdayLabel(in: timeZone))曜日"
        text += "、\(day.kind.label)、最低\(degrees(day.tempMin))、最高\(degrees(day.tempMax))"
        if let probability = day.precipitationProbability, probability >= 20 {
            text += "、降水確率\(Int(probability))パーセント"
        }
        return text
    }
}

/// 週レンジの中での、その日の最低〜最高気温を示すバー
private struct TemperatureRangeBar: View {
    let weekMin: Double
    let weekMax: Double
    let dayMin: Double
    let dayMax: Double
    let marker: Double?

    var body: some View {
        GeometryReader { proxy in
            let width = proxy.size.width
            let span = max(weekMax - weekMin, 0.1)
            let start = ((dayMin - weekMin) / span).clamped(to: 0...1) * width
            let end = ((dayMax - weekMin) / span).clamped(to: 0...1) * width

            ZStack(alignment: .leading) {
                Capsule()
                    .fill(Color.black.opacity(0.25))

                Capsule()
                    .fill(
                        LinearGradient(
                            colors: gradientColors,
                            startPoint: .leading,
                            endPoint: .trailing
                        )
                    )
                    .frame(width: max(end - start, 6))
                    .offset(x: start)

                if let marker {
                    let position = ((marker - weekMin) / span).clamped(to: 0...1) * width
                    Circle()
                        .fill(.white)
                        .frame(width: 7, height: 7)
                        .overlay(Circle().stroke(Color.black.opacity(0.3), lineWidth: 1))
                        .offset(x: position - 3.5)
                }
            }
        }
    }

    private var gradientColors: [Color] {
        let average = (dayMin + dayMax) / 2
        switch average {
        case ..<0:   return [Color(red: 0.45, green: 0.70, blue: 1.0), Color(red: 0.60, green: 0.90, blue: 1.0)]
        case 0..<12: return [Color(red: 0.40, green: 0.80, blue: 0.95), Color(red: 0.55, green: 0.90, blue: 0.65)]
        case 12..<22: return [Color(red: 0.55, green: 0.90, blue: 0.65), Color(red: 1.0, green: 0.85, blue: 0.40)]
        case 22..<30: return [Color(red: 1.0, green: 0.85, blue: 0.40), Color(red: 1.0, green: 0.55, blue: 0.30)]
        default:     return [Color(red: 1.0, green: 0.55, blue: 0.30), Color(red: 0.95, green: 0.30, blue: 0.25)]
        }
    }
}
