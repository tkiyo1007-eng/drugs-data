import SwiftUI
import Charts

/// Swift Charts による 24 時間の気温カーブ
struct TemperatureChartCard: View {
    let weather: WeatherBundle
    let units: UnitSystem

    private var points: [(date: Date, value: Double)] {
        weather.hours.map { ($0.date, units.convert($0.temperature)) }
    }

    var body: some View {
        GlassCard(title: "気温の推移", systemImage: "chart.xyaxis.line") {
            let values = points.map(\.value)
            let lower = (values.min() ?? 0) - 2
            let upper = (values.max() ?? 1) + 2

            Chart {
                ForEach(Array(points.enumerated()), id: \.offset) { _, point in
                    AreaMark(
                        x: .value("時刻", point.date),
                        yStart: .value("下限", lower),
                        yEnd: .value("気温", point.value)
                    )
                    .interpolationMethod(.catmullRom)
                    .foregroundStyle(
                        LinearGradient(
                            colors: [Color.white.opacity(0.32), Color.white.opacity(0.02)],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )

                    LineMark(
                        x: .value("時刻", point.date),
                        y: .value("気温", point.value)
                    )
                    .interpolationMethod(.catmullRom)
                    .lineStyle(StrokeStyle(lineWidth: 2.5, lineCap: .round))
                    .foregroundStyle(
                        LinearGradient(
                            colors: [Color(red: 1.0, green: 0.85, blue: 0.4), Color(red: 1.0, green: 0.55, blue: 0.35)],
                            startPoint: .leading,
                            endPoint: .trailing
                        )
                    )
                }
            }
            .chartYScale(domain: lower...upper)
            .chartXAxis {
                AxisMarks(values: .stride(by: .hour, count: 6)) { value in
                    AxisGridLine()
                        .foregroundStyle(.white.opacity(0.12))
                    AxisValueLabel {
                        if let date = value.as(Date.self) {
                            Text(date.hourLabel(in: weather.timeZone))
                                .font(.caption2)
                                .foregroundStyle(.white.opacity(0.6))
                        }
                    }
                }
            }
            .chartYAxis {
                AxisMarks(position: .trailing) { value in
                    AxisGridLine()
                        .foregroundStyle(.white.opacity(0.12))
                    AxisValueLabel {
                        if let temperature = value.as(Double.self) {
                            Text("\(Int(temperature))°")
                                .font(.caption2)
                                .foregroundStyle(.white.opacity(0.6))
                        }
                    }
                }
            }
            .frame(height: 160)
        }
    }
}
