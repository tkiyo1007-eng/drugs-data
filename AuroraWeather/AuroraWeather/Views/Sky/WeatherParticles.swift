import SwiftUI

/// 雨・霧雨・雪のパーティクルを Canvas で描画する。
/// 各パーティクルの軌道は時刻の純関数として計算するため、状態を持たず軽量。
struct WeatherParticles: View {
    let kind: ParticleKind

    var body: some View {
        if kind == .none {
            EmptyView()
        } else {
            TimelineView(.animation) { timeline in
                Canvas { context, size in
                    let time = timeline.date.timeIntervalSinceReferenceDate
                    switch kind {
                    case .rain:
                        drawRain(context: &context, size: size, time: time, count: 110, speed: 950, length: 16, opacity: 0.55)
                    case .drizzle:
                        drawRain(context: &context, size: size, time: time, count: 60, speed: 480, length: 8, opacity: 0.35)
                    case .snow:
                        drawSnow(context: &context, size: size, time: time)
                    case .none:
                        break
                    }
                }
            }
            .allowsHitTesting(false)
        }
    }

    private func drawRain(context: inout GraphicsContext, size: CGSize, time: TimeInterval, count: Int, speed: Double, length: Double, opacity: Double) {
        var generator = SeededRandom(seed: 7)
        let slant: Double = 0.18 // 少し斜めに降らせる
        for _ in 0..<count {
            let x0 = generator.next() * size.width
            let speedJitter = 0.75 + generator.next() * 0.5
            let phase = generator.next() * size.height
            let dropOpacity = opacity * (0.5 + generator.next() * 0.5)

            let travel = (time * speed * speedJitter + phase)
            let y = travel.truncatingRemainder(dividingBy: size.height + 40) - 20
            let x = (x0 + y * slant).truncatingRemainder(dividingBy: size.width + 20)

            var path = Path()
            path.move(to: CGPoint(x: x, y: y))
            path.addLine(to: CGPoint(x: x + length * slant, y: y + length))
            context.stroke(
                path,
                with: .color(Color(red: 0.75, green: 0.85, blue: 1.0).opacity(dropOpacity)),
                style: StrokeStyle(lineWidth: 1.4, lineCap: .round)
            )
        }
    }

    private func drawSnow(context: inout GraphicsContext, size: CGSize, time: TimeInterval) {
        var generator = SeededRandom(seed: 21)
        for _ in 0..<80 {
            let x0 = generator.next() * size.width
            let speed = 34 + generator.next() * 46
            let phase = generator.next() * size.height
            let swayAmplitude = 12 + generator.next() * 22
            let swaySpeed = 0.5 + generator.next() * 0.9
            let radius = 1.4 + generator.next() * 2.4
            let flakeOpacity = 0.45 + generator.next() * 0.55

            let travel = time * speed + phase
            let y = travel.truncatingRemainder(dividingBy: size.height + 20) - 10
            let x = x0 + sin(time * swaySpeed + phase) * swayAmplitude

            let rect = CGRect(x: x - radius, y: y - radius, width: radius * 2, height: radius * 2)
            context.fill(Path(ellipseIn: rect), with: .color(.white.opacity(flakeOpacity)))
        }
    }
}

#Preview {
    ZStack {
        Color(red: 0.1, green: 0.15, blue: 0.25).ignoresSafeArea()
        WeatherParticles(kind: .snow)
    }
}
