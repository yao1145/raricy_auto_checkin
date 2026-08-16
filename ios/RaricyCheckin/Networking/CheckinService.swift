import Foundation

/// 打卡服务 —— 移植 checkin.py 的 _api_checkin() / _api_claim_fortune()。
/// 依赖调用方已通过 AuthService 完成登录（同一 APIClient 共享会话）。
struct CheckinService {
    let client: APIClient

    // MARK: - 打卡 API（对应 _api_checkin）

    /// POST /checkin/api/do-checkin，返回原始响应字典。
    /// 携带 X-Requested-With: XMLHttpRequest —— 对应 client.login 成功后
    /// `session.headers.update` 中为后续 API 请求设置的 AJAX 标识头。
    func checkin() async throws -> [String: Any] {
        let (data, response) = try await client.postJSON(
            AppConfig.url(AppConfig.checkinPath),
            json: [:],
            headers: ["X-Requested-With": "XMLHttpRequest"]
        )
        guard let dict = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            throw CheckinError.network("打卡API返回非JSON: \(response.statusCode)")
        }
        return dict
    }

    // MARK: - 运势抽取（对应 _api_claim_fortune）

    /// 抽取运势卡片。与 Python 一致：永不抛错，任何异常都折算进 resultText。
    func claimFortune(cardIndex: Int) async -> FortuneResult {
        var result = FortuneResult(
            handled: false,
            cardSelected: cardIndex,
            totalCards: AppConfig.fortuneTotalCards,
            resultValue: nil,
            resultText: "",
            pool: nil
        )

        do {
            let (data, _) = try await client.postJSON(
                AppConfig.url(AppConfig.fortunePath),
                json: ["chosen_index": cardIndex],
                headers: ["X-Requested-With": "XMLHttpRequest"]
            )
            let object = try JSONSerialization.jsonObject(with: data)
            guard let dict = object as? [String: Any] else {
                throw NSError(domain: "CheckinService", code: 0,
                              userInfo: [NSLocalizedDescriptionKey: "响应不是字典"])
            }

            if intValue(dict["code"]) == 200 {
                // fortune_value 转字符串：nil → ""，与 Python `str(v) if v is not None else ""` 一致
                let valueText = dict["fortune_value"].map { String(describing: $0) } ?? ""
                result.handled = true
                result.resultValue = valueText
                result.resultText = valueText
                result.pool = dict["pool"] as? [String]
            } else {
                result.resultText = dict["message"] as? String ?? "运势抽取失败"
            }
        } catch {
            result.resultText = "运势API请求异常: \(error.localizedDescription)"
        }

        return result
    }
}
