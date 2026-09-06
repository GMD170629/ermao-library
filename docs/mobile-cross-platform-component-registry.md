# Mobile 跨平台组件注册表：当前实现映射

> 文件名沿用历史名称；本文是代码现状和复用入口的短表，不是新增组件计划。状态仍为 `IN_PROGRESS`：语义 owner、跨平台细节和真机证据尚未全部收口。

## 权威边界

| 决策 | 来源 |
|---|---|
| 颜色、间距、字体、圆角、组件度量 | `packages/design-contracts/visual-tokens.json` 及生成绑定 |
| Reader 状态、格式和安全 | `docs/mobile-reader-architecture.md`、`packages/reader-contracts/reader-safety-policy.json` |
| 内容数据、Book/Resource/Asset 和分页 | `apps/mobile/shared/.../modules/library` |
| 页面组合、用户任务和原生边界 | 当前 Phase 2–7、两端 feature 实现和 [`mobile-app-development-global-guidelines.md`](mobile-app-development-global-guidelines.md) |

## 当前映射

| 语义组件 | Android | iOS | owner/边界 |
|---|---|---|---|
| App Shell、Tab、导航 | `MainShell.kt`、`WarmPageNavigationSuite`、`WarmPageScaffold` | `MainTabView.swift`、`TabView`、紧凑 `RootTabControls` | 平台导航行为；页面不自绘系统容器 |
| Cover、身份、进度 | `features/content/ui/ContentComponents.kt`、`WarmPage*` | `Design/ContentComponents.swift`、`AppTheme.swift` | 读取 token；Book/Resource 身份由 feature/application 提供 |
| 主/次动作与状态 | `WarmPageActions`、feature detail、`WarmPageFeedback` | `BrandedControls`、feature detail、`ContentStatusView` | 动作集合和权限属于 feature；控件语义可复用 |
| 列表、分页、筛选 | Library/Shelves feature UI、`WarmPageInputs`/menus | Library/Shelves feature views、系统 searchable/Picker | 共享查询与错误模型；不共享业务加载副作用 |
| Reader Chrome | `features/reader/presentation` 的 controls/sheets | `Features/Reader` 的 controls/sheets | Reader v5 架构拥有状态；平台适配器拥有手势/渲染 |
| Settings 与管理 | `features/me`、`features/administrativesettings`、`WarmPageSettings` | Me/Settings/Administrative views、`SettingsComponents` | capability 和 locale 来自 shared 合同 |
| Audio 与 Downloads | `features/audio`、`features/downloads` | `Features/Audio`、`Features/Downloads` | shared runtime 拥有状态/管线，平台拥有媒体和文件适配 |

## 复用规则

- 外部只通过 feature `public` API 或 shared application port 进入；不要深引 feature 私有文件。
- 同一下载、认证、位置同步、错误映射和内容路由只能有一个实现 owner。新页面复用 `ContentRepository`、`BookContentTarget`、shared runtime 和现有状态组件。
- `Navigation`、`Tab`、`Menu`、`Sheet`、`Dialog`、`Picker`、`Slider`、`Switch` 等使用平台 API；旧的自算锚点、全屏 Dialog 或自绘浮层不得重新引入。
- Web 页面可提供数据、动作和内容顺序参考，不能作为系统控件的像素来源；PNG 只提供页面构图证据。

## 当前缺口与验证

当前需要优先收口的具体点是详情页私有 identity/action/row 组合、Settings/Administrative 状态组件的相似实现，以及两端紧凑导航的系统 inset/返回证据；需要逐步合并相同的 Cover、状态、分页和动作 slots，但不能为减少行数创建 pass-through 文件。App Shell 是 light-only，Reader 单独支持五种主题；旧文档中的暗色 Shell 约束不再适用。Reader v5 也需要跨平台真机 conformance。

视觉入口是 Android `visual/VisualFixtureActivity`、iOS 真机视图和 `apps/mobile/design-qa` manifests/runs；数值和策略分别由生成合同检查。组件变更须记录复用 owner、受影响 feature、平台差异、locale/a11y 行为和验证设备。
