import Foundation

/// 打卡日志存储 —— 存 UserDefaults（JSON 编码 `[CheckinRecord]`）。
/// 对应 backend/scheduler.py 的 write_log / read_logs（本端用 UserDefaults 替代 JSON 文件）。
final class LogStore {

    // MARK: - 常量

    /// UserDefaults 存储键。
    private static let storageKey = "checkin_log_v1"

    // MARK: - 属性

    /// 当前日志记录列表。
    private(set) var records: [CheckinRecord]

    // MARK: - 初始化

    /// 从 UserDefaults 加载日志；解析失败时回退为空列表。
    init() {
        if let data = UserDefaults.standard.data(forKey: Self.storageKey),
           let decoded = try? JSONDecoder().decode([CheckinRecord].self, from: data) {
            records = decoded
        } else {
            records = []
        }
    }

    // MARK: - 写入

    /// 追加一条日志并持久化。
    func append(_ record: CheckinRecord) {
        records.append(record)
        save()
    }

    // MARK: - 私有工具

    /// 持久化日志列表到 UserDefaults（JSON 编码）。
    private func save() {
        if let data = try? JSONEncoder().encode(records) {
            UserDefaults.standard.set(data, forKey: Self.storageKey)
        }
    }
}
