import Foundation

enum WeatherServiceError: LocalizedError {
    case badURL
    case badResponse

    var errorDescription: String? {
        switch self {
        case .badURL:      return "リクエストの生成に失敗しました。"
        case .badResponse: return "天気データの取得に失敗しました。通信環境をご確認ください。"
        }
    }
}

struct WeatherService {
    private let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 20
        return URLSession(configuration: config)
    }()

    func fetch(latitude: Double, longitude: Double) async throws -> WeatherBundle {
        var components = URLComponents(string: "https://api.open-meteo.com/v1/forecast")
        components?.queryItems = [
            .init(name: "latitude", value: String(latitude)),
            .init(name: "longitude", value: String(longitude)),
            .init(name: "current", value: "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m,wind_direction_10m,pressure_msl,uv_index"),
            .init(name: "hourly", value: "temperature_2m,weather_code,precipitation_probability,uv_index,visibility"),
            .init(name: "daily", value: "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,precipitation_probability_max"),
            .init(name: "timezone", value: "auto"),
            .init(name: "timeformat", value: "unixtime"),
            .init(name: "forecast_days", value: "10"),
            .init(name: "wind_speed_unit", value: "ms"),
        ]
        guard let url = components?.url else { throw WeatherServiceError.badURL }

        let (data, response) = try await session.data(from: url)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw WeatherServiceError.badResponse
        }
        let decoded = try JSONDecoder().decode(ForecastResponse.self, from: data)
        return Self.bundle(from: decoded)
    }

    static func bundle(from response: ForecastResponse) -> WeatherBundle {
        let now = Date(timeIntervalSince1970: response.current.time)
        let isDay = response.current.isDay == 1

        // 現在時刻以降 24 時間分の毎時予報
        var hours: [HourForecast] = []
        let hourly = response.hourly
        for index in hourly.time.indices {
            let date = Date(timeIntervalSince1970: hourly.time[index])
            guard date >= now.addingTimeInterval(-1800), hours.count < 25 else { continue }
            guard index < hourly.temperature.count, index < hourly.weatherCode.count else { break }
            let probability = hourly.precipitationProbability?.indices.contains(index) == true
                ? hourly.precipitationProbability?[index] : nil
            hours.append(HourForecast(
                id: index,
                date: date,
                temperature: hourly.temperature[index],
                kind: WeatherKind(wmoCode: hourly.weatherCode[index]),
                isDay: Self.isDaytime(date, response: response),
                precipitationProbability: probability ?? nil
            ))
        }

        var days: [DayForecast] = []
        let daily = response.daily
        for index in daily.time.indices {
            guard index < daily.weatherCode.count,
                  index < daily.temperatureMax.count,
                  index < daily.temperatureMin.count else { break }
            let probability = daily.precipitationProbabilityMax?.indices.contains(index) == true
                ? daily.precipitationProbabilityMax?[index] : nil
            days.append(DayForecast(
                id: index,
                date: Date(timeIntervalSince1970: daily.time[index]),
                kind: WeatherKind(wmoCode: daily.weatherCode[index]),
                tempMax: daily.temperatureMax[index],
                tempMin: daily.temperatureMin[index],
                precipitationProbability: probability ?? nil
            ))
        }

        // UV / 視程は current に無い場合、直近の毎時データで補完する
        let nearestHourIndex = hourly.time.indices.min { lhs, rhs in
            abs(hourly.time[lhs] - response.current.time) < abs(hourly.time[rhs] - response.current.time)
        }
        var uv = response.current.uvIndex ?? 0
        var visibility: Double?
        if let index = nearestHourIndex {
            if response.current.uvIndex == nil, let values = hourly.uvIndex, values.indices.contains(index) {
                uv = values[index] ?? 0
            }
            if let values = hourly.visibility, values.indices.contains(index) {
                visibility = values[index]
            }
        }

        let sunrise = daily.sunrise.first.map { Date(timeIntervalSince1970: $0) } ?? now
        let sunset = daily.sunset.first.map { Date(timeIntervalSince1970: $0) } ?? now

        return WeatherBundle(
            fetchedAt: now,
            timeZoneID: response.timezone,
            temperature: response.current.temperature,
            apparentTemperature: response.current.apparentTemperature,
            kind: WeatherKind(wmoCode: response.current.weatherCode),
            isDay: isDay,
            humidity: response.current.humidity,
            windSpeed: response.current.windSpeed,
            windDirection: response.current.windDirection,
            pressure: response.current.pressure,
            uvIndex: uv,
            visibility: visibility,
            sunrise: sunrise,
            sunset: sunset,
            hours: hours,
            days: days
        )
    }

    /// その時刻がどの日の日の出〜日の入りに含まれるかで昼夜を判定する
    private static func isDaytime(_ date: Date, response: ForecastResponse) -> Bool {
        let timestamp = date.timeIntervalSince1970
        for index in response.daily.sunrise.indices where index < response.daily.sunset.count {
            if timestamp >= response.daily.sunrise[index] && timestamp <= response.daily.sunset[index] {
                return true
            }
        }
        return false
    }
}
