import Foundation
import UserNotifications

/// 雨の降り始めをローカル通知で知らせるサービス。
/// アプリが天気を取得したタイミングで、12時間以内の降水を検出して予約する。
struct NotificationService {
    static let rainAlertID = "soradama.rainAlert"

    func requestAuthorization() async -> Bool {
        let center = UNUserNotificationCenter.current()
        let granted = try? await center.requestAuthorization(options: [.alert, .sound])
        return granted ?? false
    }

    /// 12時間以内に降水確率50%以上の時間帯があれば、その約30分前に通知を予約する。
    /// 既存の予約は毎回入れ替える(予報の更新に追従)。
    func scheduleRainAlert(for weather: WeatherBundle, placeName: String) {
        let center = UNUserNotificationCenter.current()
        center.removePendingNotificationRequests(withIdentifiers: [Self.rainAlertID])

        let now = Date()
        let wetKinds: Set<WeatherKind> = [.rain, .drizzle, .thunderstorm, .snow]
        guard let rainHour = weather.hours.first(where: { hour in
            hour.date > now.addingTimeInterval(45 * 60) &&
            hour.date < now.addingTimeInterval(12 * 3600) &&
            (hour.precipitationProbability ?? 0) >= 50 &&
            wetKinds.contains(hour.kind)
        }) else { return }

        let fireDate = rainHour.date.addingTimeInterval(-30 * 60)
        guard fireDate > now else { return }

        let content = UNMutableNotificationContent()
        let isSnow = rainHour.kind == .snow
        content.title = isSnow ? "☃️ まもなく雪の予報" : "☔️ まもなく雨の予報"
        content.body = "\(placeName)では\(rainHour.date.hourLabel(in: weather.timeZone))ごろから\(rainHour.kind.label)の見込みです(降水確率\(Int(rainHour.precipitationProbability ?? 0))%)。"
        content.sound = .default

        let trigger = UNTimeIntervalNotificationTrigger(
            timeInterval: fireDate.timeIntervalSince(now),
            repeats: false
        )
        center.add(UNNotificationRequest(identifier: Self.rainAlertID, content: content, trigger: trigger))
    }

    func cancel() {
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: [Self.rainAlertID])
    }
}
