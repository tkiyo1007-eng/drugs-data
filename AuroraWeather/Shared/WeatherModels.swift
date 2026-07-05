import Foundation

// MARK: - Open-Meteo API レスポンス(timeformat=unixtime で取得)

struct ForecastResponse: Decodable {
    let latitude: Double
    let longitude: Double
    let timezone: String
    let current: Current
    let hourly: Hourly
    let daily: Daily

    struct Current: Decodable {
        let time: Double
        let temperature: Double
        let humidity: Double
        let apparentTemperature: Double
        let isDay: Int
        let precipitation: Double
        let weatherCode: Int
        let windSpeed: Double
        let windDirection: Double
        let pressure: Double
        let uvIndex: Double?

        enum CodingKeys: String, CodingKey {
            case time
            case temperature = "temperature_2m"
            case humidity = "relative_humidity_2m"
            case apparentTemperature = "apparent_temperature"
            case isDay = "is_day"
            case precipitation
            case weatherCode = "weather_code"
            case windSpeed = "wind_speed_10m"
            case windDirection = "wind_direction_10m"
            case pressure = "pressure_msl"
            case uvIndex = "uv_index"
        }
    }

    struct Hourly: Decodable {
        let time: [Double]
        let temperature: [Double]
        let weatherCode: [Int]
        let precipitationProbability: [Double?]?
        let uvIndex: [Double?]?
        let visibility: [Double?]?

        enum CodingKeys: String, CodingKey {
            case time
            case temperature = "temperature_2m"
            case weatherCode = "weather_code"
            case precipitationProbability = "precipitation_probability"
            case uvIndex = "uv_index"
            case visibility
        }
    }

    struct Daily: Decodable {
        let time: [Double]
        let weatherCode: [Int]
        let temperatureMax: [Double]
        let temperatureMin: [Double]
        let sunrise: [Double]
        let sunset: [Double]
        let precipitationProbabilityMax: [Double?]?

        enum CodingKeys: String, CodingKey {
            case time
            case weatherCode = "weather_code"
            case temperatureMax = "temperature_2m_max"
            case temperatureMin = "temperature_2m_min"
            case sunrise
            case sunset
            case precipitationProbabilityMax = "precipitation_probability_max"
        }
    }
}

struct GeocodingResponse: Decodable {
    let results: [GeoPlace]?
}

struct GeoPlace: Decodable, Identifiable {
    let id: Int
    let name: String
    let latitude: Double
    let longitude: Double
    let country: String?
    let admin1: String?
}

// MARK: - アプリ内ドメインモデル

struct HourForecast: Identifiable, Codable {
    let id: Int
    let date: Date
    let temperature: Double
    let kind: WeatherKind
    let isDay: Bool
    let precipitationProbability: Double?
}

struct DayForecast: Identifiable, Codable {
    let id: Int
    let date: Date
    let kind: WeatherKind
    let tempMax: Double
    let tempMin: Double
    let precipitationProbability: Double?
}

/// オフラインキャッシュのため Codable。タイムゾーンは識別子文字列で保持する。
struct WeatherBundle: Codable {
    let fetchedAt: Date
    let timeZoneID: String

    var timeZone: TimeZone { TimeZone(identifier: timeZoneID) ?? .current }

    let temperature: Double
    let apparentTemperature: Double
    let kind: WeatherKind
    let isDay: Bool
    let humidity: Double
    let windSpeed: Double
    let windDirection: Double
    let pressure: Double
    let uvIndex: Double
    let visibility: Double?

    let sunrise: Date
    let sunset: Date

    let hours: [HourForecast]
    let days: [DayForecast]

    var todayMax: Double { days.first?.tempMax ?? temperature }
    var todayMin: Double { days.first?.tempMin ?? temperature }
}

// MARK: - 保存地点・設定

struct SavedPlace: Codable, Identifiable, Equatable, Hashable {
    var id: String { "\(latitude),\(longitude)" }
    let name: String
    let detail: String
    let latitude: Double
    let longitude: Double
    var isCurrentLocation: Bool = false

    static let fallback = SavedPlace(name: "東京", detail: "日本", latitude: 35.6895, longitude: 139.6917)
}

enum UnitSystem: String, Codable, CaseIterable, Identifiable {
    case celsius
    case fahrenheit

    var id: String { rawValue }
    var label: String { self == .celsius ? "摂氏 (°C)" : "華氏 (°F)" }
    var suffix: String { self == .celsius ? "°C" : "°F" }

    func convert(_ celsius: Double) -> Double {
        self == .celsius ? celsius : celsius * 9 / 5 + 32
    }
}
