import Foundation

/// 地点ごとの最終取得データをディスクに保存するオフラインキャッシュ。
/// 圏外や API 障害時にも、最後に取得できた天気を表示できるようにする。
struct WeatherCache {
    private let fileURL: URL

    init() {
        let directory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        fileURL = directory.appendingPathComponent("weather-cache.json")
    }

    func load() -> [String: WeatherBundle] {
        guard let data = try? Data(contentsOf: fileURL),
              let decoded = try? JSONDecoder().decode([String: WeatherBundle].self, from: data) else {
            return [:]
        }
        return decoded
    }

    func save(_ bundles: [String: WeatherBundle]) {
        guard let data = try? JSONEncoder().encode(bundles) else { return }
        try? data.write(to: fileURL, options: .atomic)
    }
}
