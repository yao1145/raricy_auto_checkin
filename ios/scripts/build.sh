#!/usr/bin/env bash
# 在 macOS 上本地构建未签名 IPA（无需开发者账号）。
# 产物 ios/RaricyCheckin.ipa 交由 AltStore/SideStore 重签名安装。
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v xcodegen >/dev/null 2>&1; then
  echo "未检测到 xcodegen，正在通过 Homebrew 安装..." >&2
  brew install xcodegen
fi

xcodegen generate

xcodebuild archive \
  -project RaricyCheckin.xcodeproj \
  -scheme RaricyCheckin \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  -archivePath build/RaricyCheckin.xcarchive \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO

mkdir -p build/Payload
cp -R "build/RaricyCheckin.xcarchive/Products/Applications/RaricyCheckin.app" build/Payload/
cd build
ditto -c -k --sequesterRsrc --keepParent Payload ../RaricyCheckin.ipa

echo "✅ 构建完成：ios/RaricyCheckin.ipa"
