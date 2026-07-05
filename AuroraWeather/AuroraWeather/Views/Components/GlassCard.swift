import SwiftUI

/// アプリ全体で使うガラスモーフィズムのカード。
/// うっすらとしたハイライトの縁取りで、背景のグラデーションに溶け込む。
struct GlassCard<Content: View>: View {
    var title: String?
    var systemImage: String?
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let title {
                HStack(spacing: 6) {
                    if let systemImage {
                        Image(systemName: systemImage)
                            .font(.footnote.weight(.semibold))
                    }
                    Text(title)
                        .font(.footnote.weight(.semibold))
                        .kerning(1.5)
                }
                .foregroundStyle(.white.opacity(0.65))
            }
            content
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .strokeBorder(
                    LinearGradient(
                        colors: [.white.opacity(0.35), .white.opacity(0.05)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    ),
                    lineWidth: 1
                )
        )
        .shadow(color: .black.opacity(0.18), radius: 18, y: 10)
    }
}

#Preview {
    ZStack {
        LinearGradient(colors: [.blue, .cyan], startPoint: .top, endPoint: .bottom)
            .ignoresSafeArea()
        GlassCard(title: "時間ごとの予報", systemImage: "clock") {
            Text("コンテンツ")
                .foregroundStyle(.white)
        }
        .padding()
    }
}
