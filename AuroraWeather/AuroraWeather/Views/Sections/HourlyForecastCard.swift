import SwiftUI

/// 24 時間分の毎時予報を横スクロールで表示するカード
struct HourlyForecastCard: View {
    let weather: WeatherBundle
    let degrees: (Double) -> String

    var body: some View {
        GlassCard(title: "時間ごとの予報", systemImage: "clock") {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 20) {
                    ForEach(Array(weather.hours.enumerated()), id: \.element.id) { index, hour in
                        VStack(spacing: 10) {
                            Text(index == 0 ? "今" : hour.date.hourLabel(in: weather.timeZone))
                                .font(.footnote.weight(index == 0 ? .bold : .medium))
                                .foregroundStyle(.white.opacity(index == 0 ? 1 : 0.75))

                            VStack(spacing: 3) {
                                Image(systemName: hour.kind.symbolName(isDay: hour.isDay))
                                    .symbolRenderingMode(.multicolor)
                                    .font(.title3)
                                    .frame(height: 26)

                                if let probability = hour.precipitationProbability, probability >= 20 {
                                    Text("\(Int(probability))%")
                                        .font(.caption2.weight(.semibold))
                                        .foregroundStyle(Color(red: 0.55, green: 0.85, blue: 1.0))
                                } else {
                                    Text(" ")
                                        .font(.caption2)
                                }
                            }

                            Text(degrees(hour.temperature))
                                .font(.callout.weight(.semibold))
                                .foregroundStyle(.white)
                        }
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel(accessibilityText(index: index, hour: hour))
                    }
                }
                .padding(.vertical, 2)
            }
        }
    }

    private func accessibilityText(index: Int, hour: HourForecast) -> String {
        var text = index == 0 ? "現在" : hour.date.hourLabel(in: weather.timeZone)
        text += "、\(hour.kind.label)、\(degrees(hour.temperature))"
        if let probability = hour.precipitationProbability, probability >= 20 {
            text += "、降水確率\(Int(probability))パーセント"
        }
        return text
    }
}
