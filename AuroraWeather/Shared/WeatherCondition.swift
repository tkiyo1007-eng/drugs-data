import SwiftUI

/// WMO 天気コードをデザイン上の「天候の種類」へマッピングする。
/// 背景グラデーション・パーティクル・SF Symbols をすべてここから導出する。
enum WeatherKind: String, Codable {
    case clear
    case partlyCloudy
    case cloudy
    case fog
    case drizzle
    case rain
    case snow
    case thunderstorm

    init(wmoCode: Int) {
        switch wmoCode {
        case 0:            self = .clear
        case 1, 2:         self = .partlyCloudy
        case 3:            self = .cloudy
        case 45, 48:       self = .fog
        case 51...57:      self = .drizzle
        case 61...67:      self = .rain
        case 71...77:      self = .snow
        case 80...82:      self = .rain
        case 85, 86:       self = .snow
        case 95...99:      self = .thunderstorm
        default:           self = .cloudy
        }
    }

    /// 日本語の天気ラベル
    var label: String {
        switch self {
        case .clear:         return "晴れ"
        case .partlyCloudy:  return "晴れ時々くもり"
        case .cloudy:        return "くもり"
        case .fog:           return "霧"
        case .drizzle:       return "霧雨"
        case .rain:          return "雨"
        case .snow:          return "雪"
        case .thunderstorm:  return "雷雨"
        }
    }

    func symbolName(isDay: Bool) -> String {
        switch self {
        case .clear:         return isDay ? "sun.max.fill" : "moon.stars.fill"
        case .partlyCloudy:  return isDay ? "cloud.sun.fill" : "cloud.moon.fill"
        case .cloudy:        return "cloud.fill"
        case .fog:           return "cloud.fog.fill"
        case .drizzle:       return "cloud.drizzle.fill"
        case .rain:          return "cloud.rain.fill"
        case .snow:          return "cloud.snow.fill"
        case .thunderstorm:  return "cloud.bolt.rain.fill"
        }
    }

    /// 空のグラデーション(上 → 下)
    func skyColors(isDay: Bool) -> [Color] {
        switch (self, isDay) {
        case (.clear, true):
            return [Color(red: 0.10, green: 0.42, blue: 0.86),
                    Color(red: 0.33, green: 0.66, blue: 0.96),
                    Color(red: 0.62, green: 0.85, blue: 0.98)]
        case (.clear, false):
            return [Color(red: 0.02, green: 0.03, blue: 0.12),
                    Color(red: 0.07, green: 0.10, blue: 0.28),
                    Color(red: 0.15, green: 0.20, blue: 0.42)]
        case (.partlyCloudy, true):
            return [Color(red: 0.16, green: 0.42, blue: 0.78),
                    Color(red: 0.40, green: 0.62, blue: 0.86),
                    Color(red: 0.66, green: 0.79, blue: 0.90)]
        case (.partlyCloudy, false):
            return [Color(red: 0.04, green: 0.06, blue: 0.16),
                    Color(red: 0.12, green: 0.16, blue: 0.32),
                    Color(red: 0.22, green: 0.27, blue: 0.44)]
        case (.cloudy, true), (.fog, true):
            return [Color(red: 0.35, green: 0.42, blue: 0.53),
                    Color(red: 0.51, green: 0.58, blue: 0.67),
                    Color(red: 0.68, green: 0.73, blue: 0.79)]
        case (.cloudy, false), (.fog, false):
            return [Color(red: 0.09, green: 0.11, blue: 0.16),
                    Color(red: 0.17, green: 0.20, blue: 0.27),
                    Color(red: 0.26, green: 0.30, blue: 0.38)]
        case (.drizzle, true), (.rain, true):
            return [Color(red: 0.20, green: 0.28, blue: 0.42),
                    Color(red: 0.32, green: 0.42, blue: 0.56),
                    Color(red: 0.45, green: 0.55, blue: 0.66)]
        case (.drizzle, false), (.rain, false):
            return [Color(red: 0.04, green: 0.06, blue: 0.12),
                    Color(red: 0.10, green: 0.14, blue: 0.24),
                    Color(red: 0.17, green: 0.23, blue: 0.34)]
        case (.snow, true):
            return [Color(red: 0.55, green: 0.63, blue: 0.75),
                    Color(red: 0.70, green: 0.77, blue: 0.86),
                    Color(red: 0.85, green: 0.89, blue: 0.94)]
        case (.snow, false):
            return [Color(red: 0.08, green: 0.11, blue: 0.20),
                    Color(red: 0.16, green: 0.21, blue: 0.33),
                    Color(red: 0.28, green: 0.34, blue: 0.47)]
        case (.thunderstorm, _):
            return [Color(red: 0.05, green: 0.04, blue: 0.12),
                    Color(red: 0.13, green: 0.11, blue: 0.26),
                    Color(red: 0.24, green: 0.20, blue: 0.38)]
        }
    }

    /// パーティクル演出の種類
    var particle: ParticleKind {
        switch self {
        case .rain, .thunderstorm: return .rain
        case .drizzle:             return .drizzle
        case .snow:                return .snow
        default:                   return .none
        }
    }

    var hasCloudLayer: Bool {
        switch self {
        case .clear: return false
        default:     return true
        }
    }
}

enum ParticleKind {
    case none, rain, drizzle, snow
}
