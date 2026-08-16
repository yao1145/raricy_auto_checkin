import Foundation

/// 宽松取整数：兼容 Int / String / NSNumber。
/// 对应 Python 端对响应字段的宽松比较，如 `data.get("code") == 200`。
func intValue(_ any: Any?) -> Int? {
    if let i = any as? Int { return i }
    if let s = any as? String { return Int(s) }
    if let n = any as? NSNumber { return n.intValue }
    return nil
}
