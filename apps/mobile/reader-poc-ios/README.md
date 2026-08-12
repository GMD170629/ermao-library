# AZW3 → Readium Publication → EPUB Navigator iOS POC

这是一个与正式 Mobile 工程隔离的 iOS 16+ 技术验证 Harness。运行链路为：

```text
MOBI6 / KF8 / AZW3 原文件
→ ../native/mobi-core（固定 libmobi v0.12）
→ 强类型 Swift 提取结果
→ InMemoryMobiContainer
→ Readium Publication
→ EPUBNavigatorViewController
```

POC 不生成 EPUB、ZIP 或临时解包目录。Calibre 只用于从仓库内自制源文件生成固定测试夹具，不属于运行时。

## R5 关系

- 唯一生产 libmobi 源码位于 `../native/mobi-core`，固定到 commit `85dcfe803fc2a21020ddcf15c3eb66b93d388add`。
- POC 通过公开的 `ermao_mobi_*` C ABI 使用同一核心；仓库不再保存第二份 libmobi 或旧 `shuku_mobi_*` bridge。
- 共享二进制语料、校验和及说明位于 `../../../test-data/library/mobi`。
- POC 仍会在 Swift 层把资源物化为 `Data`，仅用于既有 Readium 可行性证据；该模式不属于 R5 生产 ABI，也不得迁入 R6/R7。

## 固定依赖与验收边界

- Readium Swift Toolkit `3.11.0`（SwiftPM exact pin）
- libmobi `v0.12` / `85dcfe803fc2a21020ddcf15c3eb66b93d388add`
- iOS deployment target `16.0`
- `iphoneos/arm64` 物理设备是唯一 iOS 运行验收目标；禁止 Simulator
- XcodeGen `2.46.0`

修改 `project.yml` 后可在 macOS/Xcode 主机重新生成工程：

```bash
cd apps/mobile/reader-poc-ios
xcodegen generate
```

R5 不以“在 UI 中打开 MOBI”为完成条件；正式 Android/iOS Readium Publication adapter 分别属于 R6/R7。
