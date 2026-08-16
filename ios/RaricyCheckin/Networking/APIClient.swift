import Foundation

/// 网络客户端 —— 对应 client.py 的 requests.Session + build_session()。
/// 每个实例持有一个全新的一次性内存 Cookie 容器（ephemeral，不落盘），
/// 因此「每个账号 / 每次引擎执行」都应新建一个 APIClient 以获得全新会话。
final class APIClient {

    // MARK: - 底层 URLSession（内存 Cookie，无磁盘持久化）

    let session: URLSession

    init() {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 15        // 对应 Python timeout=15
        config.timeoutIntervalForResource = 30
        config.httpShouldSetCookies = true
        config.httpCookieAcceptPolicy = .always
        self.session = URLSession(configuration: config)
    }

    // MARK: - 通用请求

    /// 发送请求：先应用 AppConfig.defaultHeaders，再叠加调用方 headers（后者覆盖前者），
    /// 随后按需设置 Content-Type 与 httpBody。与 Python 端 build_session() 的
    /// 默认头 + 每次请求头合并逻辑一致。
    func request(
        method: String,
        url: URL,
        headers: [String: String] = [:],
        body: Data? = nil,
        contentType: String? = nil
    ) async throws -> (data: Data, response: HTTPURLResponse) {
        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = method

        for (key, value) in AppConfig.defaultHeaders {
            urlRequest.setValue(value, forHTTPHeaderField: key)
        }
        for (key, value) in headers {
            urlRequest.setValue(value, forHTTPHeaderField: key)
        }
        if let contentType {
            urlRequest.setValue(contentType, forHTTPHeaderField: "Content-Type")
        }
        urlRequest.httpBody = body

        let (data, response) = try await session.data(for: urlRequest)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw CheckinError.network("无效的 HTTP 响应")
        }
        return (data, httpResponse)
    }

    // MARK: - 便捷方法

    /// GET 请求。
    func get(_ url: URL, headers: [String: String] = [:]) async throws -> (data: Data, response: HTTPURLResponse) {
        try await request(method: "GET", url: url, headers: headers)
    }

    /// 表单 POST —— Content-Type: application/x-www-form-urlencoded。
    func postForm(
        _ url: URL,
        params: [String: String],
        headers: [String: String] = [:]
    ) async throws -> (data: Data, response: HTTPURLResponse) {
        let body = Self.formEncode(params)
        return try await request(
            method: "POST",
            url: url,
            headers: headers,
            body: body,
            contentType: "application/x-www-form-urlencoded"
        )
    }

    /// JSON POST —— Content-Type: application/json。
    func postJSON(
        _ url: URL,
        json: [String: Any],
        headers: [String: String] = [:]
    ) async throws -> (data: Data, response: HTTPURLResponse) {
        let body = try JSONSerialization.data(withJSONObject: json)
        return try await request(
            method: "POST",
            url: url,
            headers: headers,
            body: body,
            contentType: "application/json"
        )
    }

    // MARK: - 表单编码（对应 Python urllib.parse.urlencode / quote_plus）

    /// 百分号编码白名单：字母数字 + `-_.*`。其余字符按 UTF-8 百分号编码，
    /// 空格随后替换为 `+`（与 Python requests 的 urlencode 行为一致）。
    private static let formAllowedCharacters = CharacterSet(
        charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.*"
    )

    private static func percentEncode(_ string: String) -> String {
        guard let encoded = string.addingPercentEncoding(withAllowedCharacters: formAllowedCharacters) else {
            return string
        }
        return encoded.replacingOccurrences(of: "%20", with: "+")
    }

    private static func formEncode(_ params: [String: String]) -> Data {
        let pairs = params.map { key, value in
            "\(percentEncode(key))=\(percentEncode(value))"
        }
        return pairs.joined(separator: "&").data(using: .utf8) ?? Data()
    }
}
