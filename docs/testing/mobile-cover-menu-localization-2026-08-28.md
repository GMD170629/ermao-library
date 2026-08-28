# Mobile 封面管理中文显示修复 · 2026-08-28

## 范围与复用

- 检查封面长按管理能力：图书、目录、资源的操作菜单，编辑字段与封面草稿，识别候选与应用结果，Kindle 入口，删除确认，操作错误与完成提示。
- 复用现有 KMP `BookManagementSession`、管理 action/field 枚举和 iOS `NativeBookManagementHost` / `NativeManagementMenu` / `NativeManagementSheet`。首页、书库、分组、书架与详情的封面入口继续调用同一实现；不增加管理规则、网络实现或状态 owner。
- 保留原生 Menu / Form / Sheet / Dialog 和全部权限、取消、保存与删除流程，仅调整本功能的文案解析和缺失资源。不翻译用户书名、作者、文件名或服务端提供者名称。
- 保留工作区并行 Reader/Downloads 改动，不将其构建结果计为 Reader 功能验收。

## 根因与修复

- 真机修复前截图显示 `nativeManagement.action.Edit`、`nativeManagement.action.Recognize`、`nativeManagement.action.Rescan`、`nativeManagement.action.Delete` 原始键；同一菜单的静态“重新生成图片”“设为已读”已是中文。
- 原代码直接把插值字面量交给 `LocalizedStringKey`，SwiftUI 将其当作带占位符的翻译模式，而不是拼接完成的运行时键。统一通过本功能私有 `managementText(String)` 先接收完整字符串，再构造 `LocalizedStringKey`；菜单 action 映射返回普通 String。编辑字段、封面状态、失败阶段、通知、识别结果使用同一入口，删除原错误写法。
- 补齐六条 en / zh-Hans 资源：已应用字段、未应用字段、封面已应用、未选择封面、封面应用失败、保存后刷新失败。
- “当前”“候选”“源文件数量”原先提前用 Foundation 按系统 bundle 语言格式化，绕过账号的 SwiftUI locale。改成 SwiftUI 的原生文本插值，并替换旧的三个 catalog 键，不保留重复文案。
- 删除确认统一使用已有的“永久删除”动作文案，避免资源删除按钮误写为“删除图书”。原有对象范围警告与二次确认不变。
- 扩展真机流程还发现打开删除确认时的既有崩溃：Swift 在 `@MainActor` 初始化中创建的 UUID 回调被 KMP 后台恢复调用，触发 `_dispatch_assert_queue_fail`。改为不依赖 UI 状态的 `nonisolated` 静态函数引用；仍注入同一个 session 的操作 ID 端口，不改变删除规则或幂等键生命周期。真机回归保留删除确认断言，未跳过这条路径。

## 回归覆盖

- 扩展现有 `LocalizationTests`，从共享枚举生成 action、字段、封面草稿和保存阶段的双语资源断言，同时覆盖六条缺失键及三条插值文案。
- 扩展现有 `ContentDiscoveryUITests` 的真实账号流程：系统语言设为英文、账号仍为中文，核对长按菜单、编辑字段、移除/撤销封面草稿、识别空态和删除警告，保存截图。
- 测试不保存编辑、不选择文件、不提交识别、不点击扫描/再生成、不发送 Kindle、不确认删除；取消后保持真实图书原样。
- Android 对应 `BookManagement.kt` 的 69 个引用资源已检查，中文资源齐全；未修改 Android 管理代码。当前无 Android 真机，不将静态检查计为运行验收。

## 验证记录

- 修复前 iPhone XCTest 在“编辑”断言失败，取得原始键可见证据：`/tmp/ermao-cover-locale-before-20260828.xcresult`；导出截图位于 `/tmp/ermao-cover-locale-before-attachments`。
- iOS management / nativeManagement 共 130 个 catalog 键的 en / zh-Hans 值及插值占位符检查通过。
- Web `pnpm i18n:check`：2053 条中英文文案校验通过。
- `git diff --check` 与修改的 Swift 文件语法检查通过。
- 前两次修复后 test 构建分别因并行 Downloads 修改中缺少 `errorMessage`、新增测试中的 `ContentRequestContext` 类型歧义失败；均由 Downloads 负责任务修复。
- `/tmp/ermao-cover-locale-ui-20260828.xcresult`：书库中英文 UI 两项通过；封面菜单、编辑、封面草稿撤销和识别的中文断言通过，删除确认入口崩溃，整组仍为失败。截图导出至 `/tmp/ermao-cover-locale-ui-attachments`。崩溃报告 `/tmp/ermao-cover-delete-crash.ips` 的故障线程明确指向 `NativeBookManagementStore.init` 的操作 ID 回调及 KMP `BookManagementSession.select`。
- `/tmp/ermao-cover-locale-final-20260828.xcresult`：`LocalizationTests` 三项全部通过；UI 测试被真实微信通知横幅遮挡“取消”按钮，误打开微信后无法点击被 Sheet 遮挡的图书，未走到删除确认。测试补充上滑关闭系统通知横幅和 Sheet 关闭后的可点击断言，不改手机通知设置、不放宽功能断言。
- 最新完整封面流程 `/tmp/ermao-cover-locale-verified-20260828.xcresult`：1 项通过、0 失败，菜单、编辑、封面草稿撤销、识别空态、删除警告及禁止空确认均通过。四张最终真机截图导出至 `/tmp/ermao-cover-locale-verified-attachments`；已目视核对菜单、表单与删除警告中文，书名保持原文。
- 签名校验通过。11:11（Asia/Shanghai）保留数据安装本轮修复到同一物理 iPhone 并正常冷启动，关闭 fixture、不附加测试的语言覆盖参数；安装和启动证据为 `/tmp/ermao-cover-install-20260828.json`、`/tmp/ermao-cover-launch-20260828.json`。版本仍为开发版 `1.0.0 (1)`，未发布版本或提交工作区其他改动。
- 无 Simulator、无卸载、无清数据。未把编译成功作为真机 UI 验收。

## 验收边界

- 本次完成封面管理本地化修复及相关入口/弹窗真机回归，不代表实际保存、识别应用、Kindle 发送、文件删除等有副作用的业务全量验收；这些操作未对真实图书执行。
- 账号中文、系统英文的压力测试也暴露了范围外的书库数量摘要仍按系统语言显示（截图中的 `18 works`）。这是 `LibraryView` 既有 Foundation 格式化路径，不是长按菜单；本次不扩展为全 App 账号语言迁移。
- Android 仅完成文案静态核对；深色、大字、VoiceOver/TalkBack 和无障碍全量检查未执行。构建仍有范围外 Reader/旧视图弃用及既有 iPad 方向配置警告，未关闭或降低规则。
