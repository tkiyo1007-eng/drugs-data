import SwiftUI
import MapKit

// MARK: - 雨雲レーダーシート

struct RadarSheet: View {
    let place: SavedPlace
    @Environment(\.dismiss) private var dismiss

    @State private var host: String?
    @State private var frames: [RadarFrame] = []
    @State private var frameIndex = 0
    @State private var isPlaying = false
    @State private var loadFailed = false

    private var currentFrame: RadarFrame? {
        frames.indices.contains(frameIndex) ? frames[frameIndex] : nil
    }

    private var tileTemplate: String? {
        guard let host, let frame = currentFrame else { return nil }
        return RadarService.tileTemplate(host: host, frame: frame)
    }

    var body: some View {
        NavigationStack {
            ZStack(alignment: .bottom) {
                RadarMapView(
                    latitude: place.latitude,
                    longitude: place.longitude,
                    tileTemplate: tileTemplate
                )
                .ignoresSafeArea(edges: .bottom)

                if loadFailed {
                    failedBanner
                } else if frames.isEmpty {
                    ProgressView("レーダーを読み込み中…")
                        .padding(20)
                        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16))
                        .padding(.bottom, 40)
                } else {
                    controls
                }
            }
            .navigationTitle("雨雲レーダー")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("閉じる") { dismiss() }
                }
            }
        }
        .task { await load() }
        .task(id: isPlaying) {
            guard isPlaying else { return }
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 650_000_000)
                if Task.isCancelled { return }
                guard !frames.isEmpty else { continue }
                frameIndex = (frameIndex + 1) % frames.count
            }
        }
    }

    private var controls: some View {
        VStack(spacing: 10) {
            if let frame = currentFrame {
                HStack(spacing: 8) {
                    Text(frame.date.timeLabel(in: .current))
                        .font(.headline.monospacedDigit())
                    Text(frame.isForecast ? "予測" : "実況")
                        .font(.caption.weight(.bold))
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(
                            (frame.isForecast ? Color.orange : Color.blue).opacity(0.25),
                            in: Capsule()
                        )
                }
            }
            HStack(spacing: 14) {
                Button {
                    isPlaying.toggle()
                    Haptics.selection()
                } label: {
                    Image(systemName: isPlaying ? "pause.fill" : "play.fill")
                        .font(.title3)
                        .frame(width: 40, height: 40)
                        .background(.thinMaterial, in: Circle())
                }
                .accessibilityLabel(isPlaying ? "一時停止" : "再生")

                Slider(
                    value: Binding(
                        get: { Double(frameIndex) },
                        set: { frameIndex = Int($0.rounded()); isPlaying = false }
                    ),
                    in: 0...Double(max(frames.count - 1, 1)),
                    step: 1
                )
                .accessibilityLabel("時刻の選択")
            }
        }
        .padding(16)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .padding(.horizontal, 16)
        .padding(.bottom, 12)
    }

    private var failedBanner: some View {
        VStack(spacing: 10) {
            Text("レーダーデータを取得できませんでした")
                .font(.callout)
            Button("再試行") {
                loadFailed = false
                Task { await load() }
            }
            .buttonStyle(.borderedProminent)
        }
        .padding(20)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16))
        .padding(.bottom, 40)
    }

    private func load() async {
        do {
            let result = try await RadarService().fetchFrames()
            host = result.host
            frames = result.frames
            // 最新の実況フレームから開始
            frameIndex = max(frames.lastIndex(where: { !$0.isForecast }) ?? 0, 0)
        } catch {
            loadFailed = true
        }
    }
}

// MARK: - MapKit ラッパー

struct RadarMapView: UIViewRepresentable {
    let latitude: Double
    let longitude: Double
    let tileTemplate: String?

    func makeUIView(context: Context) -> MKMapView {
        let map = MKMapView()
        map.delegate = context.coordinator
        map.overrideUserInterfaceStyle = .dark
        map.pointOfInterestFilter = .excludingAll
        map.showsCompass = false
        map.region = MKCoordinateRegion(
            center: CLLocationCoordinate2D(latitude: latitude, longitude: longitude),
            span: MKCoordinateSpan(latitudeDelta: 2.4, longitudeDelta: 2.4)
        )

        let pin = MKPointAnnotation()
        pin.coordinate = CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
        map.addAnnotation(pin)
        return map
    }

    func updateUIView(_ map: MKMapView, context: Context) {
        guard context.coordinator.currentTemplate != tileTemplate else { return }
        context.coordinator.currentTemplate = tileTemplate

        map.removeOverlays(map.overlays)
        if let tileTemplate {
            let overlay = MKTileOverlay(urlTemplate: tileTemplate)
            overlay.canReplaceMapContent = false
            overlay.tileSize = CGSize(width: 256, height: 256)
            map.addOverlay(overlay, level: .aboveRoads)
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator: NSObject, MKMapViewDelegate {
        var currentTemplate: String?

        func mapView(_ mapView: MKMapView, rendererFor overlay: MKOverlay) -> MKOverlayRenderer {
            if let tile = overlay as? MKTileOverlay {
                let renderer = MKTileOverlayRenderer(tileOverlay: tile)
                renderer.alpha = 0.7
                return renderer
            }
            return MKOverlayRenderer(overlay: overlay)
        }
    }
}
