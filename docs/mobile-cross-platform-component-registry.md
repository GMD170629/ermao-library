# Mobile 跨平台视觉组件注册表

> Registry ID：`mobile-visual-components@1.0.0`
> 状态：`IN_PROGRESS`
> 目标：让 Android 与 iOS 的 App 自有内容区收敛到 Web 主视觉语义，同时保留各平台原生系统组件行为
> 数值令牌：[`packages/design-contracts/visual-tokens.json`](../packages/design-contracts/visual-tokens.json)
> 视觉语言与所有权：[`mobile-app-phase-4-visual-master.md`](mobile-app-phase-4-visual-master.md)

## 1. 权威边界

本注册表把已经建立的跨平台数值契约落到可实施组件，不创建第二套颜色、间距、排版、圆角或状态规则。

| 决策 | 权威来源 |
|---|---|
| 颜色、间距、圆角、排版、Cover、Progress、最小触控尺寸 | `packages/design-contracts/visual-tokens.json` |
| App 自有视觉语言、组件所有权、平台边界 | `docs/mobile-app-phase-4-visual-master.md` |
| 页面构图与密度 | 当前有效的 Phase 5–7 页面合同与高保真锚点 |
| Book Detail 的对象、动作、权限与内容顺序 | Web `book-detail-page.tsx`、`book-content-browser.tsx`、`resource-detail-view.tsx` |
| Android/iOS Navigation、Tab、Menu、Sheet、Dialog、Picker、Switch、Slider、Search | 各平台原生组件与行为 |

“统一到 Web 主视觉”只表示以下 `must-match` 轴一致：内容顺序、视觉重心、信息层级、语义颜色、排版角色、间距节奏、Cover/Progress 语义、主次动作、业务状态和 Reader palette。它不要求系统控件逐像素相同。

## 2. 状态与验收标记

| 标记 | 含义 |
|---|---|
| `REUSE` | 已有稳定共享实现，可直接作为平台实现 owner |
| `CONSOLIDATE` | 行为已存在，但散落在页面私有函数或多个相近组件中；应迁移到一个语义 owner |
| `ADD` | 缺少可复用语义组件 |
| `NATIVE` | 只建立语义适配器，外壳和交互由平台原生组件拥有 |
| `RETIRE` | 与视觉/平台所有权契约冲突，迁移消费者后删除 |

组件完成的最小条件：拥有明确 owner、slots、状态、令牌、双端 mapping、无障碍、Compact/Expanded、本地化和视觉回归区域；至少两个真实消费者出现前，不提取业务中立的通用组件。

## 3. P0：视觉边界与页面骨架

这些组件先于页面迁移完成，否则后续只能继续堆积页面级样式。

这里的 P0 是实施依赖细化，不改写 Phase 4 §20 的产品迁移优先级：`SemanticIcon`、`ContentFlow`、`ContentSection` 仍属于 Phase 4 P1 的“组件合同”，本阶段只先冻结名称、API 边界和平台 owner；实现与消费者迁移仍计入 P1。

| ID / 组件 | Owner / 对齐轴 | Web 事实源 | Android 映射与现状 | iOS 映射与现状 | 动作 |
|---|---|---|---|---|---|
| `P0-01 SemanticIcon` | A/C；语义和状态 `must-match`，字形 `platform-adapted` | Web 图标用途与动作集合；不复制 Lucide 路径 | `WarmSettingsIcons` 与 Material icons 已有一部分，仍有 feature 直接选图标：`CONSOLIDATE` | SF Symbols 分散在 feature：`ADD` 语义注册表 | 以 `nav.* / tab.* / action.* / state.* / media.*` 注册；禁止 API 暴露资源名 |
| `P0-02 AppScaffold` | A/C；内容 inset、Canvas、标题角色 `must-match`；导航几何 `platform-adapted` | `components/layout/app-shell.tsx` 的信息层级与 Shell surface | `WarmPageScaffold` + `WarmPageNavigationSuite`：`CONSOLIDATE`，退役固定 top bar/compact nav 几何 | `AppRootView` + `MainTabView` + `NavigationStack/TabView`：`CONSOLIDATE`；自绘 `RootTabControls` 需 P0 裁决 | 统一安全区、真实底部占位、Tab/mini player 连续 Surface；禁止硬编码系统栏/Tab 高度 |
| `P0-03 ContentFlow` | C；内容轴、区块顺序、节奏、首屏折叠 `must-match` | Book Detail 与各主页面的连续内容流 | 各 screen 的 `Column/Lazy*` 私有组合：`ADD` | `WorkDetailView`/各页面私有 `VStack/List`：`ADD` | 提供单一内容左轴、区块间距、滚动底部 inset 和 Compact/Expanded slot；不拥有导航 |
| `P0-04 ContentSection` | C；标题层级、可选动作、连续 Surface `must-match` | 页面内 `section/h2` 语义，避免复制硬编码 class | `WarmPageSectionHeader` 仅覆盖 header：`CONSOLIDATE` | 页面内 section 组合：`ADD` | slots：title、optional action、content、footer；普通 section 禁止独立卡片化 |
| `P0-05 PlatformOverlayHost` | A/B；动作语义 `must-match`；几何/材质/动效 `platform-adapted` | Web action/permission 集合，不复制 DOM 弹层 | `DropdownMenu` / `ModalBottomSheet` / `AlertDialog`：`NATIVE`；`WarmPageFloatingActionMenu`：`RETIRE` | `Menu` / `.sheet` / `.confirmationDialog` / `Alert`：`NATIVE` | 少量即时动作进 Menu；表单或超过 7 个命令进 Sheet/Page；危险动作使用系统 destructive 语义 |

### P0 退役项

- Android `WarmPageFloatingActionMenu` 使用全屏 `Dialog`、自算锚点、自定义模糊/圆角/阴影，违反平台 Menu 所有权；当前代码搜索未发现实际调用，只剩 Work Detail 的陈旧 import，应复核后删除 import、实现和专属 metrics。
- Android `WarmPageScaffold` 的 Root 标题仍使用 `display` 且 Root/Detail 强制 72/64dp top bar；紧凑 `WarmPageNavigationSuite` 仍自绘固定高度、padding 和圆角。这些几何必须交还平台，不作为可复用视觉资产。
- iOS Regular 已使用 `TabView`，但 Compact 另有自绘 `RootTabControls` 承载四 Tab 与 mini player；必须先证明它保留系统 Tab 所有权并去除固定几何，否则迁回原生 `TabView`。
- Feature 内的原始十六进制颜色、任意 dp/pt、平台图标资源名和系统区域固定高度不能作为 Web 视觉对齐手段。
- Web 页面中现存的硬编码 Tailwind 色值是待迁移实现细节，不是新的跨平台 token 来源。
- 普通 Book Hero 不允许封面模糊、封面取色、装饰渐变或玻璃效果；若旧页面锚点仍展示该效果，以 Warm Page v2 禁止项为准。

### Web 基线先行校正

当前 Web 视觉实现还没有完全服从新机器契约，因此不能把现有 DOM/CSS 逐值当成移动端目标：

- `app/layout.tsx` 仍声明 `colorScheme: 'light dark'`，与 App Shell `lightOnly` 冲突；登录、Setup、Offline 若保留独立外观，必须登记为流程例外。
- `components/ui/button.tsx` 的 primary 仍使用 `brandAccent`，而唯一实心 CTA 应使用 `actionAccent`。
- `components/book/cover.tsx` 默认 16px 圆角，fallback 仍使用 `object-cover`；契约要求 compact 8、hero 12 和统一 `contain`。
- `components/ui/progress.tsx` 默认 8px 高且没有 progress ARIA 语义；阅读进度应为 3px，并提供可访问 value。Cover progress 的视觉层可以 `aria-hidden`，前提是所属内容项提供等价状态文本。
- 代码搜索在 `apps/web` 的 78 个 TypeScript/CSS 文件中找到 1,757 个 raw hex 命中；应先按组件 owner 分批迁移，不能把这些散落值带到 Android/iOS。

## 4. P1：Book Detail、Library 与 Reader 核心组件

| ID / 组件 | 语义合同与状态 | Web 事实源 | Android 映射与现状 | iOS 映射与现状 | 动作 |
|---|---|---|---|---|---|
| `P1-01 CoverArtwork` | 2:3 `contain`；compact/hero；placeholder/loading/error；可选 CoverProgress | `components/book/cover.tsx`、`cover-reading-progress.tsx` | `BookCover` / `ContentCover` / `CoverProgress`：`REUSE` | `BookCoverView` / `CoverProgressView`：`REUSE` | 把阴影、圆角、占位和 authenticated load 约束留在组件；Comic/PDF 预览另设 variant |
| `P1-02 ContentIdentity` | cover/artwork、title、creator/series、必要 metadata、状态；default 未读不重复 | Web Book Detail identity 区 | `IdentityHeader`、`WorkIdentityText` 等为页面私有：`CONSOLIDATE` | `WorkDetailView.identity/cover/creatorSeriesLine` 为页面私有：`CONSOLIDATE` | 抽取共同 slots 和顺序；Book/Resource identity 使用显式 variant，不用 boolean 模式堆叠 |
| `P1-03 PrimaryContentAction` | 全页唯一实心 CTA；idle/loading/unavailable；文案保留，禁用显示原因 | `Button` primary 与 Book Detail 主动作 | `WarmPagePrimaryAction`：`REUSE`；Auth/Servers 重复按钮：`CONSOLIDATE` | `PrimaryActionButton`：`REUSE` | 补齐同一状态矩阵和测试；组件不拥有业务动作选择 |
| `P1-04 SecondaryActionStrip` | 最多三个高频动作加“更多”；default/selected/loading/disabled/destructive-in-menu | Book Detail 的下载、阅读状态、加入、更多 | `WarmPageSecondaryAction` 已有 primitive，`WorkDetailActionRow` 私有：`CONSOLIDATE` | `WorkDetailView.detailActions` 私有：`CONSOLIDATE` | 组件负责重排和视觉层级；权限过滤与动作集合仍由 feature application/model 提供 |
| `P1-05 ReadingProgressSummary` | percentage + position；none/in-progress/completed；与下载进度分离 | Web `Progress` 与当前位置表达 | `ReadingProgressTrack` 可复用，`BookReadingProgress/ReadingSummary` 私有：`CONSOLIDATE` | `ProgressView` 与 `progressSummary/bookReadingProgress` 私有：`CONSOLIDATE` | 建立可访问 label/value；100% 使用完成 glyph；禁止用 Slider 展示只读进度 |
| `P1-06 ContentCollection` | grid/list/rail；loading/empty/error/pagination；stable item identity | `BookCard`、`Bookshelf*`、Library 结果 | `BookGridItem` / `BookListItem`：`REUSE`，分组行仍为 feature-owned | `WorkGrid` / `WorkList`：`REUSE`，分组行仍为 feature-owned | 统一 Cover、标题、作者、进度和响应列数；不把 Shelf/Collection 业务规则塞入通用组件 |
| `P1-07 ResourceRail` | ReadableResource/目录缩略图、选择、分页、失败；状态不只靠颜色 | `BookContentBrowser`、`ResourceDetailView` | `WorkContentBrowser` 与 item/preview/row 私有：`CONSOLIDATE` | `contentBrowserSection` 与 item/preview/row 私有：`CONSOLIDATE` | 共享语义合同，不共享业务数据加载；Compact rail/list 与 Expanded split 保持同一选中状态 |
| `P1-08 MetadataList` | 低优先级 label/value；empty/long/path/date；完整无障碍值 | Book/Resource metadata 区 | `SelectedResourceMetadata` 私有：`ADD` | `selectedResourceMetadata` 私有：`ADD` | 建立只读键值组件；路径可视觉截断但需可完整读取/查看；日期和数字按 Locale |
| `P1-09 BusinessStateView` | loading/empty/error/offline/permission/conflict/stale；最多一主一次动作 | Web 页面状态与 PWA offline 语义 | `WarmPageLoading/Empty/Error/Permission*`：`CONSOLIDATE`，缺 conflict/stale 稳定 variant | `ContentStatusView`、Settings/Administrative 状态多套：`CONSOLIDATE` | 合并状态 taxonomy 和布局；错误码决定 variant，禁止按本地化文案分支 |
| `P1-10 PaginationState` | loading/error/idle/end；原位恢复且不导致布局跳动 | Library/Book content pagination | `WarmPagePaginationLoading/Error`：`REUSE` | `PaginationStatusView`：`REUSE` | 统一占位高度、重试语义和可访问 announcement |
| `P1-11 ReaderChrome` | hidden/visible/panel-open/loading/error；内容 palette 与 controls 一致 | `reader-shell.tsx` + `reader-control-primitives.tsx` | `ReaderControlOverlay` / `ReaderBottomConsole` / sheets 为页面私有：`CONSOLIDATE` | `IosReaderControls` + `ReaderControlSheets`：`CONSOLIDATE` | 保留平台返回、Slider、Sheet；共享 panel/state/label/token 合同；Reader content 始终是第一视觉层 |
| `P1-12 ReaderControlAction` | nav/quick/selected/disabled；icon + label 一个语义节点 | Web `ReaderControlNavButton` / `ReaderQuickActionButton` | Reader 内私有按钮组合：`ADD` 或从现有实现抽取 | `ReaderControlButton`：`CONSOLIDATE` | 统一 4 个底部动作和 panel selected 语义；满足 48dp/44pt 触控目标 |
| `P1-13 ReaderChoiceControl` | single-choice/segmented/slider；enabled/disabled；Dynamic Type | Web `ReaderSegmentedControl` 与系统 range input | `WarmPageSegmentedControl`：`NATIVE`，移除 72/128dp 文字高度分支；私有自绘 `ReaderSlider`：`RETIRE`，迁到 Material Slider | `Picker(.segmented)` + `ReaderValueSlider`：`NATIVE` | 共享选项和值域，不共享 thumb、track、焦点或手势几何 |

## 5. P2：全局复用与后续页面

| ID / 组件 | 消费页面 | Android | iOS | 对齐要求 |
|---|---|---|---|---|
| `P2-01 SearchField` | Library、Shelves、Downloads、管理列表 | `WarmPageSearchField`：`REUSE` | `.searchable`：`NATIVE` | 搜索范围、placeholder、提交/清除/加载语义一致；外壳平台适配 |
| `P2-02 FilterAndSortControl` | Library、Facet、管理列表 | `WarmPageCatalogHeader`、DropdownMenu、filter sheet：`CONSOLIDATE` | `.searchable`、Menu、Sheet：`NATIVE` | 活动筛选摘要和结果上下文 `must-match`；Menu/Sheet 外形不匹配 Web |
| `P2-03 SettingsScaffold` | Me 与管理设置 | `WarmSettingsScaffold`：`REUSE` | `SettingsScreen/List/Form`：`REUSE` | 分组、标题角色、Canvas、底部动作可见性一致；Navigation/List/Form 平台适配 |
| `P2-04 SettingsSection` | Me 与管理设置 | `WarmSettingsSection`：`REUSE` | `SettingsSection`：`REUSE`，`SettingsColors.rowBackground` 需改用契约 Surface | 连续分组、header、Divider；禁止每行独立大胶囊 |
| `P2-05 SettingsRow` | navigation/value/toggle/choice/field/action | `WarmSettings*Row`：`REUSE` | `Settings*Row`：`REUSE` | icon-title-detail-control 语义一致；Switch/Picker/TextField 为平台控件 |
| `P2-06 SettingsIdentity` | Me、账户、服务器 | `WarmSettingsIdentityHeader`：`REUSE` | `SettingsAvatarView` / 页面身份区：`CONSOLIDATE` | 用户/服务器身份只出现一次；动态字段不翻译 |
| `P2-07 BottomActionBar` | 长表单、批量与管理任务 | settings/action screen 局部实现：`CONSOLIDATE` | `SettingsBottomActionBar` / `AdministrativeBottomAction` 两套：`CONSOLIDATE` | 真实 safe-area inset；单一主动作；键盘和大字体下可达 |
| `P2-08 TransientFeedback` | 全 App mutation 结果 | `WarmPageSnackbarHost`：`REUSE` | Alert/overlay/页面私有反馈：`ADD` 明确 owner | success/info/error 语义与恢复动作一致；不泄露内部错误或路径 |
| `P2-09 AudioMiniPlayer` | Home、Library、Shelves、Me、Book Detail、Downloads | `AudioMiniPlayer` + NavigationSuite 连续底部 Surface：`REUSE` | `AudioMiniPlayer` + `MainTabView`：`REUSE` | 会话、标题、播放状态和折叠动作一致；Reader 中隐藏；安全区平台适配 |
| `P2-10 DownloadProgressRow` | Downloads、Book Detail 下载状态 | Download screen 私有 rows：`CONSOLIDATE` | Download screen 私有 rows：`CONSOLIDATE` | queued/running/paused/failed/completed；4pt determinate progress；阅读进度绝不复用 |

## 6. 组件 API 边界

每个平台实现都应接受语义模型而不是页面布尔开关或 Web 样式参数。推荐的公共输入形态：

```text
ComponentState = Loading | Ready | Empty | Failed(errorCode) | Unavailable(reasonCode)
ActionState = Idle | Loading | Disabled(reasonCode)
SelectionState = Unselected | Selected | Completed
LayoutMode = Compact | Expanded
```

禁止暴露：`sheetCornerRadius`、`tabHeight`、`backAnimationDuration`、`sliderThumbShape`、原始 hex、任意平台图标名、系统栏高度或 Web className。

状态模型只表达视图需要的稳定语义；数据获取、权限判断、事务和导航仍由各 capability 的 application/model owner 负责。

## 7. 视觉回归区域与通过条件

| 区域 | 类型 | 必须验证 |
|---|---|---|
| App Shell + ContentFlow | 完整产品 | light-only Canvas、系统栏、安全区、Tab/mini player 连续占位、首屏折叠 |
| ContentIdentity + actions + progress | C 类组件 fixture + 完整 Book Detail | 同数据下的视觉重心、单一主 CTA、Secondary 重排、无进度/有进度/完成 |
| ContentCollection + ResourceRail | C 类组件 fixture + Library/Book Detail | Compact 列数、长标题、选择、分页、加载/空/错误、Expanded |
| BusinessStateView | 组件 fixture + 真实入口 | 七种业务状态、恢复动作、焦点/announcement、错误码语义 |
| ReaderChrome | 完整 Reader | controls hidden/visible、四个 panel、五个手动主题、System Day/Night、内容与控件同 palette |
| Settings | 完整 Me/管理页 | 连续分组、行高、原生控件、大字体、键盘、安全区 |
| Platform overlays | 完整产品 | Menu/Sheet/Dialog 关闭顺序、焦点恢复、返回手势、destructive 语义 |

Primary 门禁固定为：物理设备、`zh-CN`、light App Shell、正常字号、同一测试数据、同一流程入口与滚动位置。Primary 通过后再扩展 `en-US`、最大字号、Compact/Expanded、Reduced Motion、Reduced Transparency 和 Reader System appearance。

## 8. 实施顺序与完成定义

1. `P0-01` 至 `P0-05`：建立 icon、scaffold、flow、section、overlay 边界；复核无调用后删除 `WarmPageFloatingActionMenu`。
2. `P1-01` 至 `P1-10`：先迁移 Book Detail，再迁移 Library；每个页面只允许一个视觉 owner。
3. `P1-11` 至 `P1-13`：统一 Reader chrome 与 choice/action primitives，不触碰 Reader 安全/导航业务合同。
4. `P2-01` 至 `P2-10`：按 Home、Shelves、Downloads、Me/Settings、Audio 顺序迁移直接消费者。
5. 每批先跑静态/单元/组件门禁，再在同一物理设备冷启动复拍；候选同时对比 Web/高保真目标与上一版已接受基线，任一 `must-match` 轴变差即拒绝。

本注册表只有在以下条件全部满足时才能从 `IN_PROGRESS` 改为 `PASS`：所有条目都有唯一平台 owner；页面私有重复实现已迁移或有明确保留理由；`RETIRE` 项及消费者已删除；Android/iOS 同状态真机证据齐全；实施者复审与独立审查对同一未变化构建均无可行动问题。

## 9. 当前缺口摘要

- 数值 token 和 Reader palette 已跨 Web/Android/iOS 建立，但组件级 registry 尚未由代码/测试强制执行。
- Android 的 Cover、按钮、状态、分页、设置和 Shell primitive 较完整；最大缺口是页面私有的 ContentFlow/Identity/ResourceRail/Metadata/ReaderChrome、固定系统组件几何，以及自绘浮层菜单退役。`WarmPageColors` 仍未暴露全部机器 token 角色，错误色也有残留 raw hex。
- iOS 的 Cover、主按钮、内容列表、分页、设置和 Reader controls 已存在；最大缺口是把 Work Detail 与状态组件从页面私有实现合并到稳定语义 owner，并消除 Settings/Administrative 两套近似状态与底部动作实现。
- Web Book Detail 仍包含较多 inline JSX 与硬编码视觉 class；它是当前对象、动作、权限和内容顺序的事实源，但移动端不得复制其 DOM、CSS 或系统控件几何。
- 当前跨平台视觉 run 的 Android 证据已通过；iOS 构建、测试和物理设备截图仍未完成，因此整体状态保持 `IN_PROGRESS`。旧 target contract 中的 Simulator build/tests 要求已被仓库“iOS 仅真机”政策取代，不得执行或作为证据。
