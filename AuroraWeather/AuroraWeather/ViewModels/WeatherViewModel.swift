import Foundation
import Observation
import CoreLocation
import WidgetKit

enum LoadPhase: Equatable {
    case idle
    case loading
    case loaded
    case failed(String)
}

@Observable
final class WeatherViewModel {
    var phase: LoadPhase = .idle
    var weather: WeatherBundle?
    var place: SavedPlace
    var savedPlaces: [SavedPlace] {
        didSet { persistPlaces() }
    }
    var units: UnitSystem {
        didSet { UserDefaults.standard.set(units.rawValue, forKey: Self.unitsKey) }
    }

    private let weatherService = WeatherService()
    private let locationService = LocationService()

    private static let placesKey = "aurora.savedPlaces"
    private static let unitsKey = "aurora.units"

    init() {
        let defaults = UserDefaults.standard
        if let raw = defaults.string(forKey: Self.unitsKey), let stored = UnitSystem(rawValue: raw) {
            units = stored
        } else {
            units = .celsius
        }
        if let data = defaults.data(forKey: Self.placesKey),
           let stored = try? JSONDecoder().decode([SavedPlace].self, from: data) {
            savedPlaces = stored
        } else {
            savedPlaces = []
        }
        place = SharedStore.lastPlace()
    }

    // MARK: - 読み込み

    @MainActor
    func loadInitial() async {
        // まず現在地を試み、拒否されたら前回の地点(既定: 東京)へフォールバック
        phase = .loading
        if let located = await resolveCurrentLocation() {
            place = located
        }
        await refresh()
    }

    @MainActor
    func refresh() async {
        if weather == nil { phase = .loading }
        do {
            let bundle = try await weatherService.fetch(latitude: place.latitude, longitude: place.longitude)
            weather = bundle
            phase = .loaded
            persistLastPlace()
        } catch {
            if weather == nil {
                phase = .failed(error.localizedDescription)
            }
        }
    }

    @MainActor
    func select(place newPlace: SavedPlace) async {
        guard newPlace != place else { return }
        place = newPlace
        weather = nil
        Haptics.selection()
        await refresh()
    }

    @MainActor
    func useCurrentLocation() async {
        phase = weather == nil ? .loading : phase
        if let located = await resolveCurrentLocation() {
            place = located
            weather = nil
            await refresh()
        } else if weather == nil {
            phase = .failed(LocationError.denied.localizedDescription)
        }
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
        guard !savedPlaces.contains(newPlace) else { return }
        savedPlaces.append(newPlace)
    }

    func removePlaces(at offsets: IndexSet) {
        savedPlaces.remove(atOffsets: offsets)
    }

    private func persistPlaces() {
        if let data = try? JSONEncoder().encode(savedPlaces) {
            UserDefaults.standard.set(data, forKey: Self.placesKey)
        }
    }

    private func persistLastPlace() {
        SharedStore.saveLastPlace(place)
        WidgetCenter.shared.reloadAllTimelines()
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
