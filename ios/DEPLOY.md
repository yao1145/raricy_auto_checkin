# 无 Mac 安装到 iPhone（已验证路径）

Swift 源码必须编译成 `.ipa` 才能安装，而编译需要 Xcode（macOS）。**无需自备 Mac**——
用 GitHub Actions 的云端 macOS 跑编译，再用 **iLoader（Windows）的「Import IPA」** 直接
签名并安装到手机。

> ⚠️ 已踩过的坑（iPhone 17 / iOS 26，免费 Apple ID）：
> - **AltServer / AltStore**：2FA 登录报 `Server returned invalid response`，app-specific password 已失效 → **不可用**。
> - **SideStore**：配对文件反复报 `could not determine UDID` / `pairing file invalid` / `InvalidPairing(.rppairing UDID invalid)` → **不可用**。
> - ✅ **iLoader → Import IPA**：绕过所有配对/UDID/2FA 环节，直接签名安装，**可用**。

## 总体流程

```
推送仓库 → GitHub Actions 云端构建 → 下载未签名 .ipa
        → Windows 装 iLoader → Import IPA → 签名并安装到手机
        → 每 7 天重新 Import 一次（免费 Apple ID 的硬限制）
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

## 二、Windows 前置依赖

iLoader 需要苹果的 USB 驱动（与 AltServer 相同）：

1. 安装 **iTunes** —— 从苹果官网下载「Windows 版」独立安装包（`.exe`），**不要**用 Microsoft Store 版。
   官网默认是「Get it from Microsoft」，要选页面下方的「找其他版本 → Windows」拿到独立 `.exe`；
   或直接访问 `https://www.apple.com/itunes/download/win64`。
2. 安装 **iCloud** —— 同理，用独立 `iCloudSetup.exe`（Store 版被沙箱隔离，工具拿不到驱动）。
3. 从 Microsoft Store 安装 **Apple Devices**（iOS 26 下设备管理已从 iTunes 独立出来）。
4. 安装后**重启电脑**。

## 三、用 iLoader 安装

1. 从 `github.com/nab138/iloader` Releases 下载 **iLoader for Windows**，解压运行。
2. USB-C 连接 iPhone，解锁并点「信任」。
3. iLoader 里点 **Import IPA**，选择下载好的 `RaricyCheckin.ipa`。
4. 按提示登录你的 Apple ID（这里走的是 iLoader 自己的登录，可正常处理 2FA 验证码）。
5. iLoader 签名并安装到手机。

> iLoader 也有「安装 SideStore / LiveContainer」的按钮，但本机实测配对文件无法通过验证；
> **直接 Import IPA 是唯一稳定路径**，无需 SideStore。

## 四、信任并首次使用

1. 手机 `设置 → 通用 → VPN 与设备管理 → 你的 Apple ID → 信任`。
2. `设置 → 隐私与安全性 → 开发者模式` → 开启并重启（若 App 无法启动）。
3. 打开 App →「添加」账号 → 输入 raricy.com 用户名密码 →「立即打卡」。

## 五、7 天续期（免费 Apple ID 的硬限制）

免费账号签名的应用 **7 天后失效**。当前设备上 **没有可用的自动续期工具**（AltServer / SideStore 均不可用），
因此续期方式就是**手动重装**：

- 到期后：打开 iLoader → **Import IPA** → 重新选 `RaricyCheckin.ipa` → 重装（约 1 分钟，需 USB 连电脑）。

> LiveContainer 也不能自动续期——它只是「一个签名跑多个 app」的容器，其自身的免费签名同样 7 天过期。
> 想彻底摆脱 7 天限制，只能付费证书（Signulous / AppDB 等，约 $20/年，一年有效、无需重签、无配对文件）。

## 备注

- 应用最低支持 **iOS 17**，iPhone 17（iOS 26）可直接运行；仅构建侧需要 Xcode ≥ 15（云端已满足）。
- 端点硬编码在 `ios/RaricyCheckin/Config/AppConfig.swift`，无需配置。
- 该设备无法降级 iOS（iPhone 17 硬件最低即 26.0），也无法使用 TrollStore（需 iOS ≤ 17.0）。
