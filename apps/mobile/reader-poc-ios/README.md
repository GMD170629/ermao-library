# AZW3 → Readium Publication → EPUB Navigator iOS POC

这是一个与正式 Mobile 工程隔离的 iOS 16+ 技术验证 Harness。运行时链路只有：

```text
MOBI6 / KF8 / AZW3 文件
→ vendored libmobi v0.12 C target
→ 强类型 Swift 提取结果
→ InMemoryMobiContainer
→ Readium Publication
→ EPUBNavigatorViewController
```

运行时不会创建 EPUB、ZIP 或临时解包目录，也不会调用 Calibre 或 Readium EPUB Parser。Calibre 9.11.0 只用于从自制的、已提交的源夹具生成固定 MOBI/AZW3 测试文件。

## 目录

- `Dependencies/LibMobi`：固定到 libmobi v0.12 / commit `85dcfe803fc2a21020ddcf15c3eb66b93d388add` 的本地 Swift Package C target 和所有权安全的 C bridge。
- `ReaderPOC/Infrastructure`：原生提取、内存 Container、Readium Manifest/Publication 适配、资源与 fragment 预检。
- `ReaderPOC/Application`：OPF spine、NCX 层级 TOC 和路径规则。
- `ReaderPOC/Harness`：夹具选择、清单/Manifest/TOC、Navigator、DOM 探针、500 次翻页和 JSON 报告。
- `ReaderPOCTests`：路径、OPF/NCX、Container/Publication 及 10 本夹具 golden 测试。
- `ReaderPOCUITests`：真机冷启动、Navigator/DOM、翻页、旋转和前后台压力套件。
- `Fixtures/Sources/Generated`：10 本测试书的已提交源树；`Fixtures/Sources/SHA256SUMS` 固定其内容。
- `ReaderPOC/Resources/Fixtures`：固定 `.mobi/.azw3`、golden 和 SHA-256。
- `Evidence`：已执行的真机证据、未闭合门槛和阶段性技术结论。

## 固定依赖

- Readium Swift Toolkit `3.11.0`（SwiftPM exact pin）
- libmobi `v0.12`（本地源码，系统 zlib，内置 XML writer）
- iOS deployment target `16.0`
- arm64 / `iphoneos` only for acceptance
- Calibre `9.11.0`（仅夹具编译器）
- XcodeGen `2.46.0`（生成工程）

`ReaderPOC.xcodeproj` 和 SwiftPM `Package.resolved` 已提交。修改 `project.yml` 后重新运行：

```bash
cd apps/mobile/reader-poc-ios
xcodegen generate
```

## 重新生成固定夹具

脚本会拒绝任何非 9.11.0 的 Calibre。若 Calibre 位于只读挂载卷：

```bash
cd apps/mobile/reader-poc-ios
CALIBRE_APP=/Volumes/calibre-9.11.0/calibre.app ./Tools/generate-fixtures.sh
```

生成后必须评审并提交源树、二进制夹具和两份 `SHA256SUMS`。Calibre 输出可能包含工具生成的非语义字节差异，因此仓库中的 SHA-256 固定的是本次评审过的成品，不宣称跨主机二进制可复现。

## 真机构建与测试

本工程禁止 Simulator。先从 `xcodebuild -showdestinations` 取得已配对、解锁并启用 Developer Mode 的物理设备 ID，然后执行：

```bash
cd apps/mobile/reader-poc-ios

xcodebuild \
  -project ReaderPOC.xcodeproj \
  -scheme ReaderPOC \
  -configuration Debug \
  -sdk iphoneos \
  -destination 'platform=iOS,id=<PHYSICAL_DEVICE_ID>' \
  test \
  -only-testing:ReaderPOCTests

xcodebuild \
  -project ReaderPOC.xcodeproj \
  -scheme ReaderPOC \
  -configuration Release \
  -sdk iphoneos \
  -destination 'platform=iOS,id=<PHYSICAL_DEVICE_ID>' \
  test \
  -only-testing:ReaderPOCUITests/ReaderPOCStressUITests
```

UI 套件内也有 `targetEnvironment(simulator)` 硬失败保护。Harness 的 500 次翻页会把解析、首屏、延迟、内存、资源失败和 DOM 探针写入应用 Documents 下的 `ReaderPOCReports/*.json`。

## 支持边界

只接受无 DRM 的 MOBI6/KF8/AZW3。DRM、KFX、AZW4、损坏 PDB 和缺少正文会返回明确错误，不做静默降级。当前 POC 不包含正式阅读器 UI、服务端、账户、下载、同步、书签、批注或 TTS。

libmobi 使用 LGPL-3.0-or-later。POC 源码保留了上游许可证和版本信息；任何正式分发前仍必须完成链接方式、可替换性及源代码提供义务的法务评审。
