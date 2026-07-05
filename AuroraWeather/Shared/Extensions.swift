import Foundation

extension Date {
    /// 指定タイムゾーンでの時刻表示("15時" 形式)
    func hourLabel(in timeZone: TimeZone) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "ja_JP")
        formatter.timeZone = timeZone
        formatter.dateFormat = "H時"
        return formatter.string(from: self)
    }

    /// "5:03" のような短い時刻
    func timeLabel(in timeZone: TimeZone) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "ja_JP")
        formatter.timeZone = timeZone
        formatter.dateFormat = "H:mm"
        return formatter.string(from: self)
    }

    /// 曜日("月" など)
    func weekdayLabel(in timeZone: TimeZone) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "ja_JP")
        formatter.timeZone = timeZone
        formatter.dateFormat = "E"
        return formatter.string(from: self)
    }

    func isSameDay(as other: Date, in timeZone: TimeZone) -> Bool {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        return calendar.isDate(self, inSameDayAs: other)
    }
}

extension Comparable {
    func clamped(to range: ClosedRange<Self>) -> Self {
        min(max(self, range.lowerBound), range.upperBound)
    }
}
