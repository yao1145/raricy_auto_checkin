import Foundation

/// 硬编码配置 —— 对应 Python 后端 config.json 的 `site` / `api` / `fortune` 段。
/// 个人侧载应用无需运行时编辑接口，故直接以常量形式固化。
enum AppConfig {

    // MARK: - 站点地址（config.json `site`）

    static let baseURL = URL(string: "https://raricy.com")!
    static let loginURL = URL(string: "https://raricy.com/auth/login")!
    static let checkinURL = URL(string: "https://raricy.com/checkin")!

    // MARK: - API 路径（config.json `api`）

    static let loginPath = "/auth/login"
    static let checkinPath = "/checkin/api/do-checkin"
    static let fortunePath = "/checkin/api/claim-fortune"

    // MARK: - 运势（config.json `fortune`）

    static let fortuneEnabled = true
    static let fortuneCardIndex = "random"   // "random" 或 0~4 的数字字符串
    static let fortuneTotalCards = 5

    // MARK: - 请求头（对应 client.py DEFAULT_UA + build_session）

    static let userAgent =
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
        "AppleWebKit/537.36 (KHTML, like Gecko) " +
        "Chrome/150.0.0.0 Safari/537.36"

    static var defaultHeaders: [String: String] {
        [
            "User-Agent": userAgent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Origin": "https://raricy.com",
            "Referer": "https://raricy.com/checkin",
        ]
    }

    /// 由相对路径构造绝对 URL（如 "/checkin/api/do-checkin"）。
    static func url(_ path: String) -> URL {
        URL(string: path, relativeTo: baseURL) ?? baseURL
    }

    // MARK: - 时间格式化（对应 Python datetime.strftime）

    static let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    static let timeFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f
    }()

    static let dateTimeFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return f
    }()
}
