# Mobile 书架行式目录验收 · 2026-08-27

## 实现范围

Android Compose / iOS SwiftUI 的书架根页、全部/书架/合集筛选、完整目录搜索、合集成员二级页、书架图书分页与既有 Book 导航、普通书架/合集新建 Sheet。数据来自现有 API；未修改后端和 Web 合同，未向真实账号加入测试内容。

参考：[设计决定](../mobile-shelves-row-layout.md)。本轮保留工作区中既有 Reader、图书目录导航、下载等修改。

## 已执行

- KMP `compileKotlinIosArm64`、Android `compileDebugKotlin` 通过。
- 共享层新加 8 项目录合同/筛选/预览/创建/授权测试，Android 新加 5 项状态/失败/分页/授权测试，均通过。既有 membership 测试更新为真实合集无 bookIds 合同。
- 最近一次完整 JVM 单元测试：共享层 278 项、Android 143 项，0 failures / errors / skipped；Android `assembleDebug` 已成功产出 APK。
- iOS 新增 6 项书架单元测试在物理 iPhone 通过（`/tmp/ermao-shelves-final-tests.xcresult`）。随后单独重跑 2 项真机 UI 流程全部通过（`/tmp/ermao-shelves-journey-retry.xcresult`）：三 scope、合集只含成员、合集→书架→既有图书详情→逐层返回、搜索无匹配。没有跳过或放宽断言。
- [隔离 fixture 根页](../assets/mobile-shelves-v2/ios-fixture-root.png)与[合集二级页](../assets/mobile-shelves-v2/ios-fixture-collection.png)仅证明布局结构和交互；fixture 没有封面，不能作为图像还原完成证据。测试后已正常冷启动回真实账号，不保留 fixture 会话。
- 两端各 28 组新增双语文案齐全；iOS 占位符一致。Android 数量采用可观察 locale。
- 签名 `iphoneos` 构建、iPhone 17 Pro Max 数据保留安装和冷启动通过，安装版本为 1.0.0 (1)。设备 connected/paired、Developer Mode enabled、无需解锁密码；没有使用模拟器。
- 真机真实账号进入书架根页并取得[空状态截图](../assets/mobile-shelves-v2/ios-live-empty.png)，1320 × 2868 px。真实账号当前没有书架，不能把这个状态当作有封面列表的视觉验收。
- `git diff --check` 通过。

## 阻塞与待验

- iOS 完整测试最初被既有 `DownloadStoreTests.swift:78` 的 Swift 6 发送隔离错误阻塞。后续工作区更新后书架测试已可执行；本任务未修改或削弱下载测试，也未宣称整个 iOS 测试集通过。
- 专项 `ShelvesUI` scheme 保留原完整 scheme；首次真机 UI 运行取得根页截图后以 signal kill 结束。当时同一 iPhone 上另有 Reader 测试进程运行，不能认定书架完整流程已通过。
- 随后第一次合集测试期间 App PID 从 35420 变为 35421，界面由英文 fixture 变为真实中文空账号，导致成员断言失败。未更改业务逻辑或减弱断言；避免并发运行后再次执行，2 项 UI 流程通过。
- Android 未连接可用物理设备；不能执行 replace-install、冷启动、TalkBack、返回/旋转/分屏和视觉验收。没有自动启动 AVD。
- 初次 Android assemble/lint 与另一构建同时写入 intermediates，出现缺失 global synthetics/lint-provisional 产物；已重新运行，不采用禁用追踪/删基线方式绕过。
- Web `pnpm i18n:check` 失败：既有管理员用户管理事件的 4 个新增中/英文键缺失、6 个旧键过期；本轮没有改 Web 文案。
- Android Lint 最终剩余 4 个既有错误：`AndroidCoverSelectionReader` 两处 ExifInterface、`work_quick_remove_download` 和 `management_regenerate_cover_message` 未用资源。书架新增的可观察 locale / 未用文案项已修正，最终报告无 ShelfCatalog / shelves_ 错误；未修改 lint 基线或禁用规则。
- 待验：非空列表真实封面、创建表单真机交互、Dynamic Type/深色/VoiceOver、Android 真机全流程。合集→书架→图书→返回、搜索/三 scope 已由隔离 fixture 真机测试通过，但不替代真实授权/封面证据。

## 视觉 QA

- Source：`docs/assets/mobile-shelves-v2/root-approved.png`、`collection-approved.png`，853 × 1844 px 的图像设计稿，约 390 × 844 逻辑画布。
- Implementation：`docs/assets/mobile-shelves-v2/ios-live-empty.png`，1320 × 2868 px，440 × 956 pt @3x。
- State：设计为非空目录，真实截图为空目录；状态和画布不同，未进行虚假的 1:1 相似度评价，也未生成假封面或填充真实账号。
- 字体/排版：代码使用系统字体与 Warm Page 标题、headline、caption；空状态可读，非空行尚需同状态视觉验证。
- 间距：连续行和分隔线，标准封面 52 × 78，行最小 116；大字减少到单张封面。非空密度和长名称未做真机定论。
- 颜色：使用 Warm Page canvas / text / divider / accent 语义令牌；iOS 系统搜索、分段选择器和 Tab 的外观由平台提供。
- 图片：真实 API 的完整 2:3 封面，认证缓存按 namespace 隔离；当前空状态不构成封面质量验证。
- 文案：28 组新文案双语检查通过；动态书架/书名原样保留。
- Comparison history：第一次仅取得空状态，非空源图与实现不匹配，完整比较阻塞。尚无非空完整视图或局部对照，不宣称还原验收通过。

final result: blocked

## 2026-08-28 补充复验：Web i18n / Android lint

以上失败记录保留为历史证据。本次仅处理 catalog 与 lint，不修改书架、Reader
流程或 API 合同。

- 旧报告中的 4 条事件翻译、AndroidX ExifInterface 和 2 个未用资源问题已由
  `9fcadcda` 修复。但 6 条被判为过期的管理员错误仍会返回前端；提取器漏识别
  `UserAdministrationError` 的 message 参数，导致英文错误仍显示中文。本次复用
  现有提取规则与翻译入口，恢复双语条目及历史英文译文，并补齐回归测试。
- Android 当前剩余错误是下载失败边界的 `LogNotTimber`；改用项目已有的
  `java.util.logging.Logger`，保留事件、资源标识和错误码，不改取消与恢复行为，
  不新增日志依赖或豁免。
- Web lint、typecheck、400 项测试及 2053 条双语 catalog 校验通过。PDF 类型与
  测试失败来自本机未应用已有补丁，冻结锁文件安装后通过；未改锁文件或依赖版本。
- 离线契约、设计令牌、KMP 322 项测试和 Android JVM 146 项测试通过，无失败或
  跳过；未改动的 KMP 在最终增量运行中为 up-to-date。Android lint 为
  `No issues found.`，`git diff --check` 通过。Android 门禁使用单次非并行 Gradle 调用。
- ADB 仍无设备，未执行保留数据安装、冷启动、真实下载失败及恢复、双语 UI、
  TalkBack 或生命周期验收，未启动模拟器；此前书架真机待验项仍保留。本次未运行
  iOS 或 Web 浏览器 UI 验收。
- 初次诊断的 SDK XML v3/v4 警告未在最终增量日志中重现，但未调整 SDK 工具链，
  不能据此宣称全新环境的兼容性问题已修复。

补充结果：catalog 与 lint 阻塞已解除；整体真机运行与视觉验收仍未完成。
