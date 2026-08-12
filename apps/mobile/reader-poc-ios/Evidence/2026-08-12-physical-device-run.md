# 2026-08-12 iOS 真机运行记录

## 环境

- 物理设备：iPhone18,2（设备显示名 `Xiaomi 17 Pro Max`）
- 系统：iOS 26.6（23G71）
- 设备 destination ID：`00008150-0011112211A0C01C`
- Xcode：26.6（17F113）
- iPhoneOS SDK：26.5
- Readium Swift：3.11.0 / revision `d82f44f4f05d87add9e22a8b75abbd61dce745dd`
- libmobi：v0.12 / commit `85dcfe803fc2a21020ddcf15c3eb66b93d388add`
- Calibre fixture compiler：9.11.0
- 架构：`iphoneos/arm64`；未启动、创建或使用 Simulator

## 已通过证据

1. Debug 签名应用构建通过。
2. Debug `build-for-testing` 在上述物理设备 destination 上通过。
3. `ReaderPOCTests` 真机执行通过：10 个 XCTest、0 failure。测试逐本调用 libmobi，精确比对格式、reading order、资源 MIME/数量、NCX TOC 层级和目标、文本 marker，并构建和预检内存 Readium Publication。
4. `testEveryFixtureReachesAStableNavigatorViewport` 的初版真机执行通过：10 本均能进入稳定的 EPUB Navigator viewport，并完成一次翻页后关闭；总耗时 154.217 秒。
5. 百万 CJK 字符夹具通过提取文本数量断言、Publication 资源/fragment 预检和 Navigator 首屏稳定打开。
6. 真机断线后的最终源码仍通过 `iphoneos/arm64` generic destination 的 Debug 和 Release `build-for-testing`，确认 DOM 探针修复以及 Release `ENABLE_TESTABILITY` 修复均可编译；这只作为编译证据，不替代真机运行验收。

本机运行产生的原始结果包：

- `/tmp/ReaderPOC-UnitTests-Pass.xcresult`
- `/tmp/ReaderPOC-NavigatorSmoke-2.xcresult`

这些结果包包含设备诊断信息，未提交到仓库；本文件保留可评审的结论摘要。

## 尚未形成通过证据

- 新增的夹具级 DOM 探针第一次运行在 `basic-mobi6` 遇到探针脚本自身的 WebKit JavaScript 异常。脚本已改为防御式 JSON 返回并记录完整异常，但修复后的复验尚未执行。
- Release 版 `basic-kf8` 500 次翻页首次尝试在测试构建阶段被 `@testable` / `ENABLE_TESTABILITY` 配置阻断，未进入应用运行。工程已修复该配置且 Release 测试构建通过，尚待真机运行复验。
- 10 本 × 冷开关 20 次、500 次前后翻页、20 次旋转、20 次前后台的完整 Release 耐久矩阵已经编码，但尚未完整执行。
- 报告 JSON 尚未从设备 Documents 导出，因此当前没有可提交的 p50/p95、峰值内存和关闭后内存数值。

## 运行中断说明

修复 DOM 探针后复验时，物理设备的无线 CoreDevice 连接中断，Xcode 报告 `com.apple.Mercury.error 1001`，随后 `devicectl` 将设备标记为 `unavailable`。这是主机与真机测试 runner 的传输中断，不是 libmobi、Publication 或 Navigator 崩溃。遵循项目的真机限定规则，没有改用 Simulator，也没有把未执行测试记为通过。

为释放免费签名 profile 的设备应用数量，只卸载了旧的临时 UI 测试 runner `com.ermao.library.uitests.xctrunner`；正式 Mobile 应用与 POC 应用均保留。
