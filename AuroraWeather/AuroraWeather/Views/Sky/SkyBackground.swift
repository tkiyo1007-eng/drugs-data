import SwiftUI

/// 天候と昼夜に応じて変化する、アプリ全体の背景。
/// グラデーション + 太陽/月の光 + 流れる雲 + パーティクルを重ねる。
struct SkyBackground: View {
    let kind: WeatherKind
    let isDay: Bool

    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            LinearGradient(
                colors: kind.skyColors(isDay: isDay),
                startPoint: .top,
                endPoint: .bottom
            )
            .animation(.easeInOut(duration: 1.2), value: kind)
            .animation(.easeInOut(duration: 1.2), value: isDay)

            if isDay && (kind == .clear || kind == .partlyCloudy) {
                SunGlow()
            }
            if !isDay {
                if !reduceMotion {
                    StarField(intensity: kind == .clear ? 1.0 : 0.35)
                }
                if kind == .clear || kind == .partlyCloudy {
                    MoonView()
                }
            }
            if kind.hasCloudLayer {
                if reduceMotion {
                    StaticClouds(dark: !isDay || kind == .thunderstorm)
                } else {
                    DriftingClouds(dark: !isDay || kind == .thunderstorm)
                }
            }
            if kind == .thunderstorm && !reduceMotion {
                LightningFlash()
            }
            if !reduceMotion {
                WeatherParticles(kind: kind.particle)
            }
        }
        .ignoresSafeArea()
    }
}

// MARK: - 静止した雲(視差効果を減らす設定時)

private struct StaticClouds: View {
    let dark: Bool

    var body: some View {
        GeometryReader { proxy in
            let width = proxy.size.width
            ZStack {
                cloudBlob(width: width * 1.1, height: 130, opacity: dark ? 0.22 : 0.5)
                    .position(x: width * 0.35, y: proxy.size.height * 0.10)
                cloudBlob(width: width * 0.9, height: 110, opacity: dark ? 0.16 : 0.38)
                    .position(x: width * 0.75, y: proxy.size.height * 0.20)
            }
        }
        .allowsHitTesting(false)
    }

    private func cloudBlob(width: Double, height: Double, opacity: Double) -> some View {
        Ellipse()
            .fill(dark ? Color(white: 0.65) : Color.white)
            .frame(width: width, height: height)
            .blur(radius: 42)
            .opacity(opacity)
    }
}

// MARK: - 太陽の光

private struct SunGlow: View {
    var body: some View {
        GeometryReader { proxy in
            let center = CGPoint(x: proxy.size.width * 0.82, y: proxy.size.height * 0.10)
            ZStack {
                Circle()
                    .fill(
                        RadialGradient(
                            colors: [Color.white.opacity(0.85), Color.yellow.opacity(0.35), .clear],
                            center: .center,
                            startRadius: 6,
                            endRadius: 190
                        )
                    )
                    .frame(width: 380, height: 380)
                    .position(center)
                    .blendMode(.screen)
            }
        }
        .allowsHitTesting(false)
    }
}

// MARK: - 月

private struct MoonView: View {
    var body: some View {
        GeometryReader { proxy in
            let center = CGPoint(x: proxy.size.width * 0.80, y: proxy.size.height * 0.11)
            ZStack {
                Circle()
                    .fill(
                        RadialGradient(
                            colors: [Color.white.opacity(0.30), .clear],
                            center: .center,
                            startRadius: 20,
                            endRadius: 120
                        )
                    )
                    .frame(width: 240, height: 240)
                    .position(center)
                Circle()
                    .fill(Color(red: 0.95, green: 0.95, blue: 0.88))
                    .frame(width: 54, height: 54)
                    .overlay(
                        // クレーター
                        ZStack {
                            Circle().fill(Color.black.opacity(0.08)).frame(width: 12, height: 12).offset(x: -9, y: -6)
                            Circle().fill(Color.black.opacity(0.06)).frame(width: 8, height: 8).offset(x: 10, y: 8)
                            Circle().fill(Color.black.opacity(0.05)).frame(width: 6, height: 6).offset(x: 4, y: -12)
                        }
                    )
                    .position(center)
                    .shadow(color: .white.opacity(0.45), radius: 22)
            }
        }
        .allowsHitTesting(false)
    }
}

// MARK: - 星空

private struct StarField: View {
    let intensity: Double

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 12.0)) { timeline in
            Canvas { context, size in
                let time = timeline.date.timeIntervalSinceReferenceDate
                var generator = SeededRandom(seed: 42)
                for _ in 0..<90 {
                    let x = generator.next() * size.width
                    let y = generator.next() * size.height * 0.55
                    let radius = 0.6 + generator.next() * 1.3
                    let phase = generator.next() * .pi * 2
                    let speed = 0.4 + generator.next() * 1.1
                    let twinkle = (sin(time * speed + phase) + 1) / 2
                    let opacity = (0.25 + twinkle * 0.75) * intensity
                    let rect = CGRect(x: x - radius, y: y - radius, width: radius * 2, height: radius * 2)
                    context.fill(Path(ellipseIn: rect), with: .color(.white.opacity(opacity)))
                }
            }
        }
        .allowsHitTesting(false)
    }
}

// MARK: - 流れる雲

private struct DriftingClouds: View {
    let dark: Bool

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 20.0)) { timeline in
            GeometryReader { proxy in
                let time = timeline.date.timeIntervalSinceReferenceDate
                let width = proxy.size.width
                ZStack {
                    cloudBlob(width: width * 1.1, height: 130, opacity: dark ? 0.22 : 0.5)
                        .position(
                            x: drift(time: time, speed: 9, span: width + 400) - 200,
                            y: proxy.size.height * 0.10
                        )
                    cloudBlob(width: width * 0.9, height: 110, opacity: dark ? 0.16 : 0.38)
                        .position(
                            x: width - (drift(time: time, speed: 6, span: width + 360) - 180),
                            y: proxy.size.height * 0.20
                        )
                    cloudBlob(width: width * 0.7, height: 90, opacity: dark ? 0.12 : 0.30)
                        .position(
                            x: drift(time: time, speed: 4, span: width + 300) - 150,
                            y: proxy.size.height * 0.32
                        )
                }
            }
        }
        .allowsHitTesting(false)
    }

    private func drift(time: TimeInterval, speed: Double, span: Double) -> Double {
        (time * speed).truncatingRemainder(dividingBy: span)
    }

    private func cloudBlob(width: Double, height: Double, opacity: Double) -> some View {
        Ellipse()
            .fill(dark ? Color(white: 0.65) : Color.white)
            .frame(width: width, height: height)
            .blur(radius: 42)
            .opacity(opacity)
    }
}

// MARK: - 稲光

private struct LightningFlash: View {
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 10.0)) { timeline in
            let time = timeline.date.timeIntervalSinceReferenceDate
            // 約 6 秒周期で 0.25 秒だけ閃光を出す
            let cycle = time.truncatingRemainder(dividingBy: 6.3)
            let flash = cycle < 0.25 ? (0.25 - cycle) / 0.25 : 0
            Color.white
                .opacity(flash * 0.28)
        }
        .allowsHitTesting(false)
    }
}

// MARK: - 決定的な擬似乱数(フレーム間で星の位置を固定するため)

struct SeededRandom {
    private var state: UInt64

    init(seed: UInt64) {
        state = seed &+ 0x9E3779B97F4A7C15
    }

    mutating func next() -> Double {
        state = state &* 6364136223846793005 &+ 1442695040888963407
        let value = (state >> 33) & 0x7FFFFFFF
        return Double(value) / Double(0x7FFFFFFF)
    }
}

#Preview {
    SkyBackground(kind: .clear, isDay: false)
}
