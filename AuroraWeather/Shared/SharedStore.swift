import Foundation

/// アプリとウィジェットで選択地点を共有するためのストア。
/// App Group が設定されていればそのコンテナを、なければ各ターゲットの
/// UserDefaults を使う(その場合ウィジェットは既定の東京にフォールバック)。
enum SharedStore {
    /// Signing & Capabilities で App Group を追加する場合はこの ID を使う
    static let appGroupID = "group.com.tkiyo1007.soradama"
    static let lastPlaceKey = "aurora.lastPlace"

    private static var stores: [UserDefaults] {
        var result: [UserDefaults] = [.standard]
        if let shared = UserDefaults(suiteName: appGroupID) {
            result.append(shared)
        }
        return result
    }

    static func saveLastPlace(_ place: SavedPlace) {
        guard let data = try? JSONEncoder().encode(place) else { return }
        for store in stores {
            store.set(data, forKey: lastPlaceKey)
        }
    }

    static func lastPlace() -> SavedPlace {
        for store in stores.reversed() {
            if let data = store.data(forKey: lastPlaceKey),
               let place = try? JSONDecoder().decode(SavedPlace.self, from: data) {
                return place
            }
        }
        return .fallback
    }
}
