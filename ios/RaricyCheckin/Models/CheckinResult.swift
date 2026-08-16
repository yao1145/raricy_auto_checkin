import Foundation

/// 步骤状态 —— 对应 result["steps"][].status（running / done / error）。
enum StepStatus: String {
    case running
    case done
    case error
}

/// 单条进度步骤 —— 对应 result["steps"] 中的一项。
struct CheckinStep: Identifiable {
    let id = UUID()
    let status: StepStatus
    let message: String
    let time: Date
}

/// 运势抽取结果 —— 对应 checkin.py _api_claim_fortune 返回的 fortune_result。
struct FortuneResult {
    var handled: Bool
    var cardSelected: Int
    var totalCards: Int
    var resultValue: String?   // 如 "大吉"
    var resultText: String
    var pool: [String]?
}

/// 一次打卡的完整结果 —— 对应 checkin.py execute() 返回的 result 字典。
struct CheckinResult: Identifiable {
    let id = UUID()
    var success: Bool
    var message: String
    var alreadyChecked: Bool
    var totalDays: Int?
    var fortune: FortuneResult?
    var steps: [CheckinStep]
    var durationSeconds: Double
    var account: String
    var timestamp: Date
}
