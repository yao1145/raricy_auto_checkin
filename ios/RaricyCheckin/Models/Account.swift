import Foundation

/// 账号元数据 —— 对应 accounts.json 中的 `{username, enabled}`。
/// 密码不在此处存储，单独存于 Keychain（以 username 为键），避免明文落盘。
struct Account: Identifiable, Codable, Equatable {
    var id: String { username }
    var username: String
    var enabled: Bool
}
