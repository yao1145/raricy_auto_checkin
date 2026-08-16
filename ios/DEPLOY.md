# 无 Mac 安装到 iPhone（Option B）

Swift 源码必须编译成 `.ipa` 才能安装，而编译需要 Xcode（macOS）。**无需自备 Mac**——
用 GitHub Actions 的云端 macOS 跑编译，再用 AltStore（AltServer 有 Windows 版）装到手机。

## 总体流程

```
推送仓库 → GitHub Actions 云端构建 → 下载未签名 .ipa
        → 电脑装 AltServer(Windows) → 手机装 AltStore
        → AltStore 用免费 Apple ID 重签名并安装 .ipa
```

## 一、云端构建（已配置好，推送即触发）

仓库已含 `.github/workflows/build-ipa.yml`，推送到 `main` 会自动在 macOS runner 上：

1. 安装 xcodegen，`xcodegen generate` 生成 Xcode 工程；
2. `xcodebuild archive`（`CODE_SIGNING_ALLOWED=NO`，未签名）；
3. 打包为 `Payload/` → `ios/RaricyCheckin.ipa`；
4. 作为构建产物上传。

手动构建：仓库页 **Actions → Build iOS IPA → Run workflow**。

下载产物：运行成功后点进该 run，找到 **Artifacts → RaricyCheckin-ipa** 下载并解压，得到 `RaricyCheckin.ipa`。

> 若未来 GitHub 移除 `macos-15` runner，把 workflow 里的 `runs-on: macos-15` 改成 `macos-latest` 即可。

## 二、在 Windows 上安装 AltStore

1. 安装 **iTunes** 和 **iCloud** —— 务必从苹果官网下载「Windows 版」，**不要**用 Microsoft Store 版本（AltServer 依赖其 USB 驱动）。
2. 到 altstore.io 下载 **AltServer for Windows** 并安装。
3. 用 USB-C 线连接 iPhone，解锁手机并点「信任」。
4. 在系统托盘点 AltServer 图标 → **Install AltStore → 你的 iPhone** → 输入你的 Apple ID 与密码。
5. 手机上出现 **AltStore** 图标；首次打开会提示「未受信任的开发者」，到
   **设置 → 通用 → VPN 与设备管理 → 你的 Apple ID → 信任**。

## 三、用 AltStore 安装打卡 App

1. 把 `RaricyCheckin.ipa` 传到手机（AirDrop、iCloud 云盘、邮件、微信均可）。
2. 手机打开 **AltStore** → **My Apps** 右上角 **+** → 选中该 `.ipa`。
3. AltStore 用你的免费 Apple ID 重签名并安装。
4. 首次打开同样需要到 **设置 → 通用 → VPN 与设备管理** 信任该应用。

## 四、7 天重签（免费 Apple ID 的限制）

免费账号签名的应用 **7 天后失效**。AltStore 会在手机与电脑同一 Wi-Fi、且 AltServer
运行时自动续签，基本无需手动操作。若失效，重开 AltStore → My Apps → 点应用 → Refresh All。

## 五、iPhone 首次使用前的准备

- **开启开发者模式**：`设置 → 隐私与安全性 → 开发者模式` → 开启并重启。
- 应用内置账号与密码（Keychain 存储），打开 App →「添加」账号 →「立即打卡」。

## 备注

- 应用最低支持 **iOS 17**，iPhone 17（iOS 26）可直接运行；仅构建侧需要 Xcode ≥ 15（云端已满足）。
- 端点硬编码在 `ios/RaricyCheckin/Config/AppConfig.swift`，无需配置。
