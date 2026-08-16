import Foundation

/// 打卡异常 —— 对应 client.py 中定义的异常层次。
/// Python 端另有 AlreadyCheckedInError，但当前引擎已改为通过响应的
/// `already_checked` 字段处理「已打卡」，不再抛出该异常，故此处不保留。
enum CheckinError: Error, Equatable {
    /// 登录失败（对应 LoginFailedError）
    case loginFailed(String)
    /// 网络超时 / 不可达（对应 NetworkError）
    case network(String)

    var message: String {
        switch self {
        case .loginFailed(let m), .network(let m):
            return m
        }
    }
}
