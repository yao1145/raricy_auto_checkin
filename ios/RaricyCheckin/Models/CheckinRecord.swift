import Foundation

/// 打卡日志记录 —— 对应 scheduler.py write_log 写入 checkin_log.json 的 entry。
struct CheckinRecord: Identifiable, Codable {
    var id = UUID()
    let date: String          // "yyyy-MM-dd"
    let time: String          // "HH:mm:ss"
    let timestamp: String     // "yyyy-MM-dd HH:mm:ss"
    let account: String
    let success: Bool
    let message: String
    let alreadyChecked: Bool
    let fortune: String?
    let durationSeconds: Double
    let trigger: String       // "manual"
}
