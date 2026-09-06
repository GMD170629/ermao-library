# 移动 App 第四阶段：当前 Warm Page 视觉合同

> 文件名沿用历史阶段编号；正文是当前实现摘要。精确数值只来自 [`packages/design-contracts/visual-tokens.json`](../packages/design-contracts/visual-tokens.json)，不要从截图或本文复制数值。

## 权威边界

| 决策 | 所有者 |
|---|---|
| 颜色、间距、圆角、字体、组件度量 | `visual-tokens.json` 及其生成绑定 |
| 页面顺序、密度、Book/Resource 内容组合 | 当前 Phase 5–7 与实现；内容身份和阅读行为见 [`mobile-reader-architecture.md`](mobile-reader-architecture.md) |
| Navigation、Tab、Sheet、Menu、Dialog、Picker、权限 | 平台原生行为与 [`mobile-app-development-global-guidelines.md`](mobile-app-development-global-guidelines.md) |
| PNG、真机截图、QA runs | 视觉证据；不拥有功能、身份或令牌 |

## 当前页面语法

页面先给出平台标题和当前任务，再呈现连续内容区、一个主要动作和必要状态。Book 根页按身份/封面/元数据/进度/内容浏览器排列；目录节点只显示面包屑、排序、分页和子项；Resource detail 显示资源信息、章节或媒体轨道及 Reader/播放动作。Loading、empty、error、permission、pagination 等状态原位出现并提供一个明确的恢复动作。

内容是视觉第一层：使用稳定左轴、排版和留白建立层级；避免装饰性渐变、封面模糊背景、重复进度和把业务状态画成工具面板。每页只保留一个最高对比的强动作，次要动作降级到原生 Menu/Sheet 或次级按钮。

## 视觉角色

- App Shell 当前为 light-only；`actionAccent` 是全页唯一实心 CTA 与交互文字的品牌角色，v1.2.0 按用户批准的 Web 手机端亮橙色统一。品牌色不承担错误语义，危险操作使用平台 danger 角色。
- Reader 有 Day、Warm、Green、Night、Black 主题，并支持 Reader 自己的 System 模式；Reader 主题不改变 App Shell 的 light-only 约束。
- Cover 使用服务器内容和 2:3 视觉比例，按 token radius/裁切规则渲染；读取进度、下载进度和播放进度分别表达。
- 标题、正文、label、caption 和按钮层级使用生成 typography；布局节奏、圆角、阴影、进度高度和触控尺寸从生成合同读取。

## 组件所有权

系统拥有的导航、Tab、Sheet、Menu、Dialog、Picker、Switch、Slider、键盘、权限和返回手势必须用平台 API。Native-themed 搜索、输入、开关、滑杆和加载控件只做语义着色。Cover、内容身份、业务状态、进度和 Reader 内容是 App-owned，并通过 token 组合。不要以 Web CSS/DOM 或自绘全屏 overlay 取代平台容器。

## 两端映射与验证

Android 由 `ui/theme/WarmPageTheme.kt`、`WarmPageTokens.kt`、`ui/components/WarmPage*` 和 feature-owned 内容组件实现；iOS 由 `Design/AppTheme.swift`、`BrandedControls.swift`、`ContentComponents.swift` 及 feature views 实现。紧凑底部导航仍有平台差异：Android `WarmPageNavigationSuite` 和 iOS `RootTabControls` 需保留系统 inset、返回和无障碍语义。

所有可见状态支持 `zh-CN`/`en-US`，iOS 触控目标至少 44pt、Android 至少 48dp，动态字体、键盘、VoiceOver/TalkBack、Reduced Motion 和对比度行为不能被视觉还原破坏。Android 视觉夹具在 `apps/mobile/androidApp/.../visual/VisualFixtureActivity.kt`；iOS Reader、系统覆盖层和视觉验收使用真机。当前 Reader v5 的真机一致性仍以架构文档和 `apps/mobile/design-qa` 运行记录为准。
