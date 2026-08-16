import Foundation
import Security

/// Keychain 封装 —— 使用 Generic Password 类型的 item。
/// 密码明文不落盘，统一以 username 为 account 键存入 Keychain。
enum KeychainStore {

    // MARK: - 常量

    /// 服务标识 —— 与 App 的 Bundle Identifier 前缀一致。
    private static let service = "com.raricy.checkin"

    // MARK: - 写入

    /// 存储字符串。先删除同键旧值再写入，保证幂等。
    static func set(_ value: String, for key: String) {
        delete(key)
        let data = Data(value.utf8)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecValueData as String: data,
        ]
        SecItemAdd(query as CFDictionary, nil)
    }

    // MARK: - 读取

    /// 读取存储的 UTF-8 字符串；不存在时返回 nil。
    static func get(_ key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    // MARK: - 删除

    /// 删除指定键的 Keychain item。
    static func delete(_ key: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
