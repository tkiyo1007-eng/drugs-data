import Foundation

/// RainViewer(無料・APIキー不要)の雨雲レーダータイル情報。
/// 過去約1時間 + 今後約30分のフレーム一覧を取得する。
struct RadarFrame: Identifiable, Equatable {
    let time: Int          // Unix 秒
    let path: String       // タイルパス
    let isForecast: Bool   // 予測フレームか

    var id: Int { time }
    var date: Date { Date(timeIntervalSince1970: Double(time)) }
}

struct RadarService {
    private struct MapsResponse: Decodable {
        let host: String
        let radar: Radar

        struct Radar: Decodable {
            let past: [Entry]
            let nowcast: [Entry]?
        }
        struct Entry: Decodable {
            let time: Int
            let path: String
        }
    }

    /// - Returns: タイルホスト URL と時系列フレーム
    func fetchFrames() async throws -> (host: String, frames: [RadarFrame]) {
        guard let url = URL(string: "https://api.rainviewer.com/public/weather-maps.json") else {
            throw URLError(.badURL)
        }
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
        let decoded = try JSONDecoder().decode(MapsResponse.self, from: data)

        var frames = decoded.radar.past.suffix(7).map {
            RadarFrame(time: $0.time, path: $0.path, isForecast: false)
        }
        for entry in decoded.radar.nowcast ?? [] {
            frames.append(RadarFrame(time: entry.time, path: entry.path, isForecast: true))
        }
        return (decoded.host, frames)
    }

    /// MKTileOverlay 用の URL テンプレートを組み立てる
    static func tileTemplate(host: String, frame: RadarFrame) -> String {
        "\(host)\(frame.path)/256/{z}/{x}/{y}/2/1_1.png"
    }
}
