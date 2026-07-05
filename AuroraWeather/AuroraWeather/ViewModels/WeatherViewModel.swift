import Foundation
import Observation
import CoreLocation
import WidgetKit

@Observable
final class WeatherViewModel {
    /// 表示するページ(先頭: 現在地または前回の地点、以降: マイシティ)
    private(set) var pages: [SavedPlace] = []
    /// 現在表示中のページ(SavedPlace.id)
    var selectionID: String = SavedPlace.fallback.id

    private(set) var bundles: [String: WeatherBundle] = [:]
    private(set) var loadingIDs: Set<String> = []
    /// 直近の取得に失敗した地点 → エラーメッセージ(キャッシュがあれば表示は継続する)
    private(set) var errors: [String: String] = [:]

    private(set) var savedPlaces: [SavedPlace] = []
    var units: UnitSystem = .celsius
    private(set) var rainAlertsEnabled: Bool

    private var primaryPlace: SavedPlace
    private let weatherService = WeatherService()
    private let locationService = LocationService()
    private let cache = WeatherCache()
    private let notifications = NotificationService()

    private static let placesKey = "aurora.savedPlaces"
    private static let rainAlertsKey = "aurora.rainAlerts"

    init() {
        primaryPlace = SharedStore.lastPlace()
        rainAlertsEnabled = UserDefaults.standard.bool(forKey: Self.rainAlertsKey)
        if let data = UserDefaults.standard.data(forKey: Self.placesKey),
           let stored = try? JSONDecoder().decode([SavedPlace].self, from: data) {
            savedPlaces = stored
        }
        bundles = cache.load()
        selectionID = primaryPlace.id
        rebuildPages()
    }

    // MARK: - 現在ページの便宜プロパティ

    var currentBundle: WeatherBundle? { bundles[selectionID] }
    var currentKind: WeatherKind { currentBundle?.kind ?? .partlyCloudy }
    var currentIsDay: Bool { currentBundle?.isDay ?? true }

    // MARK: - 読み込み

    @MainActor
    func loadInitial() async {
        // 現在地の解決を試み、拒否/失敗時は前回の地点(既定: 東京)を使う
        if let located = await resolveCurrentLocation() {
            primaryPlace = located
            rebuildPages()
            selectionID = located.id
        }
        await ensureLoaded(selectionID, force: true)

        // 残りのページは裏で先読みしておく
        for page in pages where page.id != selectionID {
            let id = page.id
            Task { await self.ensureLoaded(id) }
        }
    }

    /// 指定ページのデータを(未取得または30分以上古い場合に)取得する
    @MainActor
    func ensureLoaded(_ id: String, force: Bool = false) async {
        guard let place = pages.first(where: { $0.id == id }) else { return }
        if !force,
           let bundle = bundles[id],
           Date().timeIntervalSince(bundle.fetchedAt) < 1800,
           errors[id] == nil {
            return
        }
        guard !loadingIDs.contains(id) else { return }
        loadingIDs.insert(id)
        defer { loadingIDs.remove(id) }

        do {
            let bundle = try await weatherService.fetch(latitude: place.latitude, longitude: place.longitude)
            bundles[id] = bundle
            errors[id] = nil
            cache.save(bundles)
            if id == primaryPlace.id {
                SharedStore.saveLastPlace(place)
                WidgetCenter.shared.reloadAllTimelines()
                if rainAlertsEnabled {
                    notifications.scheduleRainAlert(for: bundle, placeName: place.name)
                }
            }
        } catch {
            errors[id] = error.localizedDescription
        }
    }

    /// 検索結果から地点を選択(未保存ならマイシティへ追加してからページ移動)
    @MainActor
    func selectSearched(_ place: SavedPlace) async {
        if place.id != primaryPlace.id, !savedPlaces.contains(where: { $0.id == place.id }) {
            savedPlaces.append(place)
            persistPlaces()
            rebuildPages()
        }
        selectionID = place.id
        Haptics.selection()
        await ensureLoaded(place.id)
    }

    @MainActor
    func useCurrentLocation() async {
        guard let located = await resolveCurrentLocation() else {
            errors[selectionID] = errors[selectionID] ?? LocationError.denied.localizedDescription
            return
        }
        primaryPlace = located
        rebuildPages()
        selectionID = located.id
        await ensureLoaded(located.id, force: true)
    }

    private func resolveCurrentLocation() async -> SavedPlace? {
        guard let location = try? await locationService.currentLocation() else { return nil }
        var name = "現在地"
        var detail = ""
        if let placemark = try? await CLGeocoderBox.reverseGeocode(location) {
            name = placemark.locality ?? placemark.administrativeArea ?? "現在地"
            detail = placemark.country ?? ""
        }
        return SavedPlace(
            name: name,
            detail: detail,
            latitude: location.coordinate.latitude,
            longitude: location.coordinate.longitude,
            isCurrentLocation: true
        )
    }

    // MARK: - 保存地点

    func save(place newPlace: SavedPlace) {
        guard !savedPlaces.contains(where: { $0.id == newPlace.id }) else { return }
        savedPlaces.append(newPlace)
        persistPlaces()
        rebuildPages()
    }

    func removePlaces(at offsets: IndexSet) {
        let removedIDs = offsets.map { savedPlaces[$0].id }
        savedPlaces.remove(atOffsets: offsets)
        persistPlaces()
        rebuildPages()
        // 表示中のページが消えた場合は先頭へ戻す
        if removedIDs.contains(selectionID) {
            selectionID = primaryPlace.id
        }
    }

    private func rebuildPages() {
        var result = [primaryPlace]
        for place in savedPlaces where place.id != primaryPlace.id {
            result.append(place)
        }
        pages = result
    }

    private func persistPlaces() {
        if let data = try? JSONEncoder().encode(savedPlaces) {
            UserDefaults.standard.set(data, forKey: Self.placesKey)
        }
    }

    // MARK: - 雨の通知

    @MainActor
    func setRainAlerts(_ enabled: Bool) async {
        if enabled {
            let granted = await notifications.requestAuthorization()
            rainAlertsEnabled = granted
            if granted, let bundle = bundles[primaryPlace.id] {
                notifications.scheduleRainAlert(for: bundle, placeName: primaryPlace.name)
            }
        } else {
            rainAlertsEnabled = false
            notifications.cancel()
        }
        UserDefaults.standard.set(rainAlertsEnabled, forKey: Self.rainAlertsKey)
    }

    // MARK: - 表示用フォーマット

    func degrees(_ celsius: Double) -> String {
        "\(Int(units.convert(celsius).rounded()))°"
    }
}

// MARK: - 逆ジオコーディング(名前解決)

enum CLGeocoderBox {
    static func reverseGeocode(_ location: CLLocation) async throws -> CLPlacemark? {
        let geocoder = CLGeocoder()
        let placemarks = try await geocoder.reverseGeocodeLocation(location, preferredLocale: Locale(identifier: "ja_JP"))
        return placemarks.first
    }
}
