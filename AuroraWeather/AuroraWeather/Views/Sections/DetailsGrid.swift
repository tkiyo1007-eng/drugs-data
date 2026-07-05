import SwiftUI

/// 詳細情報のグリッド: 日の出アーク・風向コンパス・UV・湿度・体感温度・気圧・視程
struct DetailsGrid: View {
    let weather: WeatherBundle
    let degrees: (Double) -> String

    private let columns = [GridItem(.flexible(), spacing: 14), GridItem(.flexible(), spacing: 14)]

    var body: some View {
        LazyVGrid(columns: columns, spacing: 14) {
            GlassCard(title: "日の出・日の入り", systemImage: "sunrise") {
                SunArcView(sunrise: weather.sunrise, sunset: weather.sunset, now: Date(), timeZone: weather.timeZone)
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("日の出 \(weather.sunrise.timeLabel(in: weather.timeZone))、日の入り \(weather.sunset.timeLabel(in: weather.timeZone))")
            GlassCard(title: "風", systemImage: "wind") {
                WindCompassView(direction: weather.windDirection, speed: weather.windSpeed)
            }
            GlassCard(title: "UV指数", systemImage: "sun.max") {
                UVGaugeView(value: weather.uvIndex)
            }
            GlassCard(title: "湿度", systemImage: "humidity") {
                HumidityView(value: weather.humidity)
            }
            GlassCard(title: "体感温度", systemImage: "thermometer.medium") {
                VStack(alignment: .leading, spacing: 6) {
                    Text(degrees(weather.apparentTemperature))
                        .font(.system(size: 34, weight: .semibold, design: .rounded))
                        .foregroundStyle(.white)
                    Text(apparentComment)
                        .font(.footnote)
                        .foregroundStyle(.white.opacity(0.7))
                    Spacer(minLength: 0)
                }
                .frame(maxWidth: .infinity, minHeight: 110, alignment: .topLeading)
            }
            GlassCard(title: "気圧", systemImage: "gauge.with.needle") {
                VStack(alignment: .leading, spacing: 6) {
                    Text("\(Int(weather.pressure.rounded()))")
                        .font(.system(size: 34, weight: .semibold, design: .rounded))
                        .foregroundStyle(.white)
                    + Text(" hPa")
                        .font(.footnote.weight(.medium))
                        .foregroundStyle(.white.opacity(0.7))
                    Text(pressureComment)
                        .font(.footnote)
                        .foregroundStyle(.white.opacity(0.7))
                    Spacer(minLength: 0)
                }
                .frame(maxWidth: .infinity, minHeight: 110, alignment: .topLeading)
            }
        }
        if let visibility = weather.visibility {
            GlassCard(title: "視程", systemImage: "eye") {
                HStack(alignment: .firstTextBaseline, spacing: 4) {
                    Text(String(format: "%.1f", visibility / 1000))
                        .font(.system(size: 34, weight: .semibold, design: .rounded))
                        .foregroundStyle(.white)
                    Text("km")
                        .font(.footnote.weight(.medium))
                        .foregroundStyle(.white.opacity(0.7))
                    Spacer()
                    Text(visibility >= 10_000 ? "とてもクリアな視界です" : visibility >= 4_000 ? "おおむね良好な視界です" : "視界が悪くなっています")
                        .font(.footnote)
                        .foregroundStyle(.white.opacity(0.7))
                }
            }
        }
    }

    private var apparentComment: String {
        let difference = weather.apparentTemperature - weather.temperature
        if difference >= 2 { return "実際より暖かく感じます" }
        if difference <= -2 { return "実際より寒く感じます" }
        return "実際の気温とほぼ同じ体感です"
    }

    private var pressureComment: String {
        if weather.pressure >= 1020 { return "高気圧・安定した天気" }
        if weather.pressure <= 1005 { return "低気圧・天気の崩れに注意" }
        return "標準的な気圧です"
    }
}

// MARK: - 日の出・日の入りアーク

struct SunArcView: View {
    let sunrise: Date
    let sunset: Date
    let now: Date
    let timeZone: TimeZone

    private var progress: Double {
        let total = sunset.timeIntervalSince(sunrise)
        guard total > 0 else { return 0 }
        return (now.timeIntervalSince(sunrise) / total).clamped(to: 0...1)
    }

    var body: some View {
        VStack(spacing: 6) {
            GeometryReader { proxy in
                let width = proxy.size.width
                let height = proxy.size.height
                let arcCenter = CGPoint(x: width / 2, y: height)
                let radius = min(width / 2 - 8, height - 6)

                ZStack {
                    // 地平線
                    Path { path in
                        path.move(to: CGPoint(x: 0, y: height - 0.5))
                        path.addLine(to: CGPoint(x: width, y: height - 0.5))
                    }
                    .stroke(Color.white.opacity(0.25), lineWidth: 1)

                    // アーク
                    Path { path in
                        path.addArc(center: arcCenter, radius: radius, startAngle: .degrees(180), endAngle: .degrees(0), clockwise: false)
                    }
                    .stroke(
                        LinearGradient(
                            colors: [Color(red: 1.0, green: 0.65, blue: 0.35), Color(red: 1.0, green: 0.85, blue: 0.45), Color(red: 1.0, green: 0.65, blue: 0.35)],
                            startPoint: .leading,
                            endPoint: .trailing
                        ),
                        style: StrokeStyle(lineWidth: 2.5, lineCap: .round, dash: [1, 5])
                    )

                    // 太陽の現在位置
                    let angle = Double.pi * (1 - progress)
                    let sunPosition = CGPoint(
                        x: arcCenter.x + radius * cos(angle),
                        y: arcCenter.y - radius * sin(angle)
                    )
                    Circle()
                        .fill(Color(red: 1.0, green: 0.88, blue: 0.55))
                        .frame(width: 12, height: 12)
                        .shadow(color: Color(red: 1.0, green: 0.8, blue: 0.4).opacity(0.9), radius: 8)
                        .position(sunPosition)
                }
            }
            .frame(height: 62)

            HStack {
                VStack(alignment: .leading, spacing: 1) {
                    Text("日の出")
                        .font(.caption2)
                        .foregroundStyle(.white.opacity(0.6))
                    Text(sunrise.timeLabel(in: timeZone))
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(.white)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 1) {
                    Text("日の入り")
                        .font(.caption2)
                        .foregroundStyle(.white.opacity(0.6))
                    Text(sunset.timeLabel(in: timeZone))
                        .font(.callout.weight(.semibold))
                        .foregroundStyle(.white)
                }
            }
        }
        .frame(minHeight: 110)
    }
}

// MARK: - 風向コンパス

struct WindCompassView: View {
    let direction: Double // 風が「吹いてくる」方角(度)
    let speed: Double     // m/s

    /// 16方位の日本語名(VoiceOver 用)
    static func directionName(_ degrees: Double) -> String {
        let names = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
                     "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]
        let index = Int(((degrees + 11.25) / 22.5).rounded(.down)) % 16
        return names[index]
    }

    var body: some View {
        HStack {
            Spacer(minLength: 0)
            ZStack {
                // 目盛り
                ForEach(0..<36, id: \.self) { tick in
                    Capsule()
                        .fill(Color.white.opacity(tick % 9 == 0 ? 0.7 : 0.25))
                        .frame(width: 1.5, height: tick % 9 == 0 ? 8 : 4)
                        .offset(y: -46)
                        .rotationEffect(.degrees(Double(tick) * 10))
                }
                // 方位ラベル
                ForEach([(0, "N"), (90, "E"), (180, "S"), (270, "W")], id: \.0) { degreesValue, label in
                    Text(label)
                        .font(.caption2.weight(.bold))
                        .foregroundStyle(.white.opacity(degreesValue == 0 ? 1 : 0.55))
                        .offset(y: -33)
                        .rotationEffect(.degrees(Double(degreesValue)))
                }
                // 矢印(風が吹いていく方向を指す)
                Image(systemName: "location.north.fill")
                    .font(.system(size: 15))
                    .foregroundStyle(Color(red: 0.55, green: 0.85, blue: 1.0))
                    .offset(y: -46)
                    .rotationEffect(.degrees(direction + 180))
                    .animation(.spring(duration: 1.0), value: direction)

                // 中心の風速
                VStack(spacing: 0) {
                    Text(String(format: "%.0f", speed))
                        .font(.system(size: 24, weight: .semibold, design: .rounded))
                        .foregroundStyle(.white)
                    Text("m/s")
                        .font(.caption2)
                        .foregroundStyle(.white.opacity(0.6))
                }
            }
            .frame(width: 110, height: 110)
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(Self.directionName(direction))の風、秒速\(Int(speed.rounded()))メートル")
    }
}

// MARK: - UV ゲージ

struct UVGaugeView: View {
    let value: Double

    private var level: (String, Color) {
        switch value {
        case ..<3:  return ("低い", Color(red: 0.45, green: 0.85, blue: 0.55))
        case 3..<6: return ("中程度", Color(red: 1.0, green: 0.85, blue: 0.40))
        case 6..<8: return ("強い", Color(red: 1.0, green: 0.60, blue: 0.30))
        case 8..<11: return ("非常に強い", Color(red: 0.95, green: 0.35, blue: 0.30))
        default:    return ("極端に強い", Color(red: 0.75, green: 0.40, blue: 0.95))
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("\(Int(value.rounded()))")
                .font(.system(size: 34, weight: .semibold, design: .rounded))
                .foregroundStyle(.white)
            Text(level.0)
                .font(.callout.weight(.semibold))
                .foregroundStyle(level.1)

            GeometryReader { proxy in
                let position = (value / 11).clamped(to: 0...1) * proxy.size.width
                ZStack(alignment: .leading) {
                    Capsule()
                        .fill(
                            LinearGradient(
                                colors: [
                                    Color(red: 0.45, green: 0.85, blue: 0.55),
                                    Color(red: 1.0, green: 0.85, blue: 0.40),
                                    Color(red: 1.0, green: 0.60, blue: 0.30),
                                    Color(red: 0.95, green: 0.35, blue: 0.30),
                                    Color(red: 0.75, green: 0.40, blue: 0.95),
                                ],
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                        .frame(height: 5)
                    Circle()
                        .fill(.white)
                        .frame(width: 9, height: 9)
                        .overlay(Circle().stroke(Color.black.opacity(0.3), lineWidth: 1))
                        .offset(x: position - 4.5)
                }
                .frame(maxHeight: .infinity, alignment: .center)
            }
            .frame(height: 10)
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, minHeight: 110, alignment: .topLeading)
    }
}

// MARK: - 湿度

struct HumidityView: View {
    let value: Double

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("\(Int(value.rounded()))%")
                .font(.system(size: 34, weight: .semibold, design: .rounded))
                .foregroundStyle(.white)

            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule()
                        .fill(Color.black.opacity(0.25))
                        .frame(height: 5)
                    Capsule()
                        .fill(
                            LinearGradient(
                                colors: [Color(red: 0.45, green: 0.75, blue: 1.0), Color(red: 0.30, green: 0.55, blue: 0.95)],
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                        .frame(width: (value / 100).clamped(to: 0...1) * proxy.size.width, height: 5)
                }
                .frame(maxHeight: .infinity, alignment: .center)
            }
            .frame(height: 10)

            Text(value >= 75 ? "蒸し暑く感じられます" : value <= 35 ? "乾燥しています" : "快適な湿度です")
                .font(.footnote)
                .foregroundStyle(.white.opacity(0.7))
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, minHeight: 110, alignment: .topLeading)
    }
}
