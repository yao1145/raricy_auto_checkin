import Foundation

/// 账号存储 —— 列表存 UserDefaults（JSON 编码 `[Account]`），密码存 Keychain。
/// 对应后端 accounts.json 拆分设计：load_config 合并账号 / save_config 将密码分离。
/// 密码以 username 为键写入 Keychain，列表中仅保留 `{username, enabled}`。
final class AccountStore {

    // MARK: - 常量

    /// UserDefaults 存储键。
    private static let storageKey = "accounts_v1"

    // MARK: - 属性

    /// 当前账号列表（密码不在其中）。
    private(set) var accounts: [Account]

    // MARK: - 初始化

    /// 从 UserDefaults 加载账号列表；解析失败时回退为空列表。
    init() {
        if let data = UserDefaults.standard.data(forKey: Self.storageKey),
           let decoded = try? JSONDecoder().decode([Account].self, from: data) {
            accounts = decoded
        } else {
            accounts = []
        }
    }

    // MARK: - 增删改查

    /// 新增账号：用户名已存在时静默忽略；密码写入 Keychain 后追加到列表。
    func add(username: String, password: String, enabled: Bool) {
        guard !accounts.contains(where: { $0.username == username }) else { return }
        KeychainStore.set(password, for: username)
        accounts.append(Account(username: username, enabled: enabled))
        save()
    }

    /// 更新账号：密码非 nil 且不等于掩码 "****" 时写回 Keychain
    /// （"****" 表示未修改，保留原密码）；更新启用状态并保存。
    func update(username: String, password: String?, enabled: Bool) {
        guard let index = accounts.firstIndex(where: { $0.username == username }) else { return }
        if let password, password != "****" {
            KeychainStore.set(password, for: username)
        }
        accounts[index].enabled = enabled
        save()
    }

    /// 仅切换账号启用状态。
    func setEnabled(username: String, enabled: Bool) {
        guard let index = accounts.firstIndex(where: { $0.username == username }) else { return }
        accounts[index].enabled = enabled
        save()
    }

    /// 删除账号：同时清除 Keychain 中的密码。
    func remove(username: String) {
        KeychainStore.delete(username)
        accounts.removeAll { $0.username == username }
        save()
    }

    /// 读取账号密码；未存储时返回空串。
    func password(for username: String) -> String {
        KeychainStore.get(username) ?? ""
    }

    // MARK: - 私有工具

    /// 持久化账号列表到 UserDefaults（JSON 编码）。
    private func save() {
        if let data = try? JSONEncoder().encode(accounts) {
            UserDefaults.standard.set(data, forKey: Self.storageKey)
        }
    }
}
