import Foundation

struct GeocodingService {
    func search(_ query: String) async throws -> [GeoPlace] {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count >= 1 else { return [] }

        var components = URLComponents(string: "https://geocoding-api.open-meteo.com/v1/search")
        components?.queryItems = [
            .init(name: "name", value: trimmed),
            .init(name: "count", value: "12"),
            .init(name: "language", value: "ja"),
            .init(name: "format", value: "json"),
        ]
        guard let url = components?.url else { return [] }

        let (data, response) = try await URLSession.shared.data(from: url)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { return [] }
        let decoded = try JSONDecoder().decode(GeocodingResponse.self, from: data)
        return decoded.results ?? []
    }
}

extension GeoPlace {
    var detailText: String {
        [admin1, country].compactMap { $0 }.joined(separator: " / ")
    }

    var asSavedPlace: SavedPlace {
        SavedPlace(name: name, detail: detailText, latitude: latitude, longitude: longitude)
    }
}
