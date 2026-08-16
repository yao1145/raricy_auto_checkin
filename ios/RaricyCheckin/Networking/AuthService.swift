import Foundation

/// 登录服务 —— 移植 client.py 的 login() / _verify_login() / _extract_csrf()。
/// 与后端策略一致：先 GET 登录页提取 CSRF token，再表单 POST（form-first），
/// 验证失败后回退 JSON POST（json-fallback）。
struct AuthService {
    let client: APIClient

    // MARK: - 登录（对应 client.login）

    /// 使用用户名密码登录。成功后 client 的 Cookie 容器已持有认证会话，
    /// 可供后续打卡 / 运势 API 复用。
    func login(username: String, password: String) async throws {
        // 1. GET 登录页，提取 CSRF token
        let loginPage: (data: Data, response: HTTPURLResponse)
        do {
            loginPage = try await client.get(AppConfig.loginURL)
        } catch {
            throw CheckinError.network("无法访问登录页: \(error.localizedDescription)")
        }
        guard loginPage.response.statusCode < 400 else {
            throw CheckinError.network("无法访问登录页: \(loginPage.response.statusCode)")
        }
        let html = String(data: loginPage.data, encoding: .utf8) ?? ""

        // 2. 提取 CSRF token
        let csrfToken = extractCSRF(html)

        // 3. 表单 POST（form-first）
        var params = [
            "username": username,
            "password": password,
            "next": "",
        ]
        if let csrfToken {
            params["csrf_token"] = csrfToken
        }
        do {
            _ = try await client.postForm(
                AppConfig.loginURL,
                params: params,
                headers: ["Referer": AppConfig.loginURL.absoluteString]
            )
        } catch {
            throw CheckinError.network("登录请求失败: \(error.localizedDescription)")
        }

        // 4. 验证登录
        if await verifyLogin() { return }

        // 5. JSON POST 回退（json-fallback）
        do {
            _ = try await client.postJSON(
                AppConfig.loginURL,
                json: ["username": username, "password": password],
                headers: [
                    "Referer": AppConfig.loginURL.absoluteString,
                    "X-Requested-With": "XMLHttpRequest",
                ]
            )
        } catch {
            throw CheckinError.loginFailed("登录失败: \(error.localizedDescription)")
        }

        // 6. 再次验证登录
        if await verifyLogin() { return }
        throw CheckinError.loginFailed("登录失败：账号 \(username) 的用户名或密码错误")
    }

    // MARK: - 登录验证（对应 client._verify_login）

    /// GET 打卡页并检查是否仍停留在登录页。
    /// 重定向后的最终 URL 含 /auth/login 或 /login，或正文含登录表单 id="loginform" 视为未登录。
    func verifyLogin() async -> Bool {
        let page: (data: Data, response: HTTPURLResponse)
        do {
            page = try await client.get(AppConfig.checkinURL)
        } catch {
            return false
        }

        // 最终 URL（重定向后）落入登录页则未登录
        let finalURL = page.response.url?.absoluteString.lowercased() ?? ""
        if finalURL.contains("/auth/login") || finalURL.contains("/login") {
            return false
        }

        // 页面正文含登录表单则未登录
        let body = String(data: page.data, encoding: .utf8)?.lowercased() ?? ""
        if body.contains("id=\"loginform\"") {
            return false
        }

        return true
    }

    // MARK: - CSRF 提取（对应 client._extract_csrf）

    /// 按顺序尝试 4 个正则（均忽略大小写），返回第一个命中的捕获组 1。
    func extractCSRF(_ html: String) -> String? {
        let patterns = [
            #"<input[^>]+name=["']csrf_token["'][^>]+value=["']([^"']+)"#,
            #"<meta[^>]+name=["']csrf-token["'][^>]+content=["']([^"']+)"#,
            #"name=["']_csrf_token["'][^>]+value=["']([^"']+)"#,
            #"csrf_token\s*[:=]\s*["']([^"']+)"#,
        ]
        for pattern in patterns {
            guard let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else {
                continue
            }
            let range = NSRange(html.startIndex..<html.endIndex, in: html)
            guard let match = regex.firstMatch(in: html, options: [], range: range),
                  match.numberOfRanges > 1 else {
                continue
            }
            if let swiftRange = Range(match.range(at: 1), in: html) {
                return String(html[swiftRange])
            }
        }
        return nil
    }
}
