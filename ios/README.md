# RaricyCheckin (iOS)

raricy.com 自动打卡系统的原生 iOS（SwiftUI）移植版。纯 SwiftUI 实现，零第三方依赖，仅做手动点击打卡（check-in + fortune + 多账号）。

> 注意：iOS 无法保证无人值守的每日定时运行，因此本 App **不做后台定时任务**，只提供手动"一键打卡"。

## 环境要求

- Mac 搭配 Xcode 15+（含 iOS 17 SDK）
- 一个免费的 Apple ID（用于个人侧载）

## 方式 A — 使用 xcodegen

```bash
brew install xcodegen
cd ios
xcodegen generate
open RaricyCheckin.xcodeproj
```

## 方式 B — 手动在 Xcode 中创建

1. 新建一个 "iOS App" 项目，命名为 `RaricyCheckin`（SwiftUI、iOS 17，不勾选 Core Data）。
2. 删除模板自带的 `ContentView.swift`。Detailed introduction on how to deploy on the iPhone 17.
3. 把 `RaricyCheckin/` 源码文件夹拖入项目（勾选 "Copy items if needed"，并加入 target）。

## 签名设置

- Xcode → Signing & Capabilities → 选择你的 Team（免费 Apple ID）。
- 设置一个唯一的 Bundle Identifier。
- 勾选 "Automatically manage signing"。

## 侧载说明

免费 Apple ID 签名的 App 每 **7 天** 需要重新签名一次；可用 AltStore / SideStore 自动刷新。

## 其他说明

- 接口地址已硬编码为 `https://raricy.com`，见 `Config/AppConfig.swift`。
