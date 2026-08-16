import Foundation
import Observation

/// 打卡界面视图模型 —— 聚合账号、日志、进度步骤与执行状态，
/// 作为 ContentView / AccountListView / CheckinView 之间共享的单一数据源。
@Observable
final class CheckinViewModel {
    var accounts: [Account]
    var records: [CheckinRecord]
    var selectedUsernames: Set<String> = []
    var steps: [CheckinStep] = []
    var results: [CheckinResult] = []
    var isRunning = false

    private let accountStore = AccountStore()
    private let logStore = LogStore()

    init() {
        accounts = accountStore.accounts
        records = logStore.records
        selectedUsernames = Set(accounts.filter(\.enabled).map(\.username))
    }

    /// 从底层 store 重新同步账号与日志。
    func reload() {
        accounts = accountStore.accounts
        records = logStore.records
    }

    // MARK: - 账号管理

    func addAccount(username: String, password: String, enabled: Bool) {
        accountStore.add(username: username, password: password, enabled: enabled)
        reload()
        selectedUsernames.insert(username)
    }

    func updateAccount(username: String, password: String?, enabled: Bool) {
        accountStore.update(username: username, password: password, enabled: enabled)
        reload()
    }

    func removeAccount(username: String) {
        accountStore.remove(username: username)
        reload()
        selectedUsernames.remove(username)
    }

    func setEnabled(username: String, enabled: Bool) {
        accountStore.setEnabled(username: username, enabled: enabled)
        reload()
    }

    /// 指定账号「今日」的打卡记录（最新一条），无则返回 nil。
    func todayStatus(for username: String) -> CheckinRecord? {
        let today = AppConfig.dateFormatter.string(from: Date())
        return records.last { $0.account == username && $0.date == today }
    }

    // MARK: - 执行打卡

    @MainActor
    func checkin() async {
        guard !isRunning else { return }
        isRunning = true
        steps.removeAll()
        results.removeAll()
        defer { isRunning = false }

        // 勾选的启用账号；若未勾选任何账号，则回退到全部启用账号。
        let selected = accounts.filter { $0.enabled && selectedUsernames.contains($0.username) }
        let targets = selected.isEmpty ? accounts.filter(\.enabled) : selected

        for account in targets {
            let password = accountStore.password(for: account.username)
            let engine = CheckinEngine()
            let result = await engine.run(username: account.username, password: password) { step in
                Task { @MainActor in
                    self.steps.append(step)
                }
            }
            results.append(result)
            appendRecord(for: result)
        }

        reload()
    }

    private func appendRecord(for result: CheckinResult) {
        let now = Date()
        let record = CheckinRecord(
            date: AppConfig.dateFormatter.string(from: now),
            time: AppConfig.timeFormatter.string(from: now),
            timestamp: AppConfig.dateTimeFormatter.string(from: now),
            account: result.account,
            success: result.success,
            message: result.message,
            alreadyChecked: result.alreadyChecked,
            fortune: result.fortune?.resultText,
            durationSeconds: result.durationSeconds,
            trigger: "manual"
        )
        logStore.append(record)
        records = logStore.records
    }
}
