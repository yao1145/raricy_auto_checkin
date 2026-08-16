import Foundation

/// 打卡引擎 —— 对应 backend/checkin.py 的 `CheckinEngine.execute()`。
/// 纯 requests（iOS 端由 APIClient 实现），按序完成：登录 → 打卡 API → 运势卡片。
/// 每个引擎实例持有独立的 APIClient（独立 session / cookies）。
struct CheckinEngine {

    // MARK: - 依赖

    /// 新建引擎时创建全新的 APIClient，保证独立的 session / cookies。
    private let client = APIClient()

    // MARK: - 初始化

    /// 创建一个全新的引擎实例（新 session）。
    init() {}

    // MARK: - 主流程

    /// 执行完整打卡流程（纯 HTTP，无浏览器）。
    ///
    /// 1. 登录 (POST /auth/login)
    /// 2. HTTP API 打卡 (POST /checkin/api/do-checkin)
    /// 3. HTTP API 运势卡片 (POST /checkin/api/claim-fortune)
    ///
    /// - Parameters:
    ///   - username: 登录用户名
    ///   - password: 登录密码
    ///   - onStep: 步骤回调。注意：在后台上下文（非主线程）中调用，由调用方自行切回主线程。
    /// - Returns: 打卡结果（success / message / fortune / steps 等）
    func run(
        username: String,
        password: String,
        onStep: ((CheckinStep) -> Void)? = nil
    ) async -> CheckinResult {
        let start = Date()
        var steps: [CheckinStep] = []

        // 追加一步并回调（对应 Python 的 _add_step + _progress）
        func addStep(_ status: StepStatus, _ message: String) {
            let step = CheckinStep(status: status, message: message, time: Date())
            steps.append(step)
            onStep?(step)
        }

        // 组装最终结果（对应 execute() 结尾的 result 字典）
        func finish(
            success: Bool,
            message: String,
            alreadyChecked: Bool,
            fortune: FortuneResult? = nil,
            totalDays: Int? = nil
        ) -> CheckinResult {
            let seconds = Date().timeIntervalSince(start)
            return CheckinResult(
                success: success,
                message: message,
                alreadyChecked: alreadyChecked,
                totalDays: totalDays,
                fortune: fortune,
                steps: steps,
                durationSeconds: round(seconds * 10) / 10,
                account: username,
                timestamp: Date()
            )
        }

        // 缺少用户名或密码
        guard !username.isEmpty, !password.isEmpty else {
            addStep(.error, "缺少用户名或密码")
            return finish(success: false, message: "缺少用户名或密码", alreadyChecked: false)
        }

        let auth = AuthService(client: client)
        let checkin = CheckinService(client: client)

        do {
            // ── 阶段1: 登录 ───────────────────────────────
            addStep(.running, "正在登录...")
            try await auth.login(username: username, password: password)
            addStep(.done, "登录成功")

            // ── 阶段2: 打卡 API ───────────────────────────
            addStep(.running, "正在打卡...")
            let dict: [String: Any]
            do {
                dict = try await checkin.checkin()
            } catch {
                throw CheckinError.network("打卡API请求失败: \(error.localizedDescription)")
            }

            let code = intValue(dict["code"])

            if code == 401 {
                addStep(.error, "登录已过期")
                throw CheckinError.loginFailed("登录已过期，Session 失效")
            }

            if dict["already_checked"] as? Bool == true {
                let totalDays = intValue(dict["total_count"])
                addStep(.done, "今日已打卡")
                return finish(
                    success: true,
                    message: "今日已打卡，无需重复操作",
                    alreadyChecked: true,
                    totalDays: totalDays
                )
            }

            if code != 200 {
                let msg = dict["message"] as? String ?? "打卡API返回异常"
                addStep(.error, msg)
                return finish(success: false, message: msg, alreadyChecked: false)
            }

            addStep(.done, "打卡成功")
            let successMessage = dict["message"] as? String ?? "打卡成功 ✓"

            // ── 阶段3: 运势卡片（可选）───────────────────
            var fortune: FortuneResult?
            let showFortune = dict["show_fortune"] as? Bool ?? false
            let fortunePending = dict["fortune_pending"] as? Bool ?? false

            if AppConfig.fortuneEnabled && (showFortune || fortunePending) {
                addStep(.running, "正在抽取运势卡片...")
                let f = await checkin.claimFortune(cardIndex: resolveCardIndex())
                fortune = f
                if f.handled {
                    addStep(.done, "运势卡片: \(f.resultText)")
                } else {
                    addStep(.done, "运势: \(f.resultText.isEmpty ? "未获取" : f.resultText)")
                }
            }

            addStep(.done, "打卡完成")
            return finish(
                success: true,
                message: successMessage,
                alreadyChecked: false,
                fortune: fortune
            )

        } catch let error as CheckinError {
            addStep(.error, error.message)
            return finish(success: false, message: error.message, alreadyChecked: false)
        } catch {
            let msg = "未知错误: \(error.localizedDescription)"
            addStep(.error, msg)
            return finish(success: false, message: msg, alreadyChecked: false)
        }
    }

    // MARK: - 私有工具

    /// 解析运势卡片序号 —— 对应 checkin.py `_api_claim_fortune` 的 card_index 解析。
    /// "random" → 随机 0..<totalCards；否则解析数字字符串后取模。
    private func resolveCardIndex() -> Int {
        if AppConfig.fortuneCardIndex == "random" {
            return Int.random(in: 0..<AppConfig.fortuneTotalCards)
        }
        return (Int(AppConfig.fortuneCardIndex) ?? 0) % AppConfig.fortuneTotalCards
    }
}
