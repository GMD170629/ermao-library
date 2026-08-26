# 移动 App 第四阶段：Warm Page 视觉系统 v2

> Spec ID：`warm-page@2.0.0`
> 状态：已采纳的 Mobile 视觉系统
> 版本：2.0.0
> 决策日期：2026-08-25
> 取代：Warm Page v1.1
> 适用范围：`apps/mobile` 的 iOS/Android 高保真设计、语义组件、主题、页面实现、原型、视觉回归和所有可见状态
> 唯一数值令牌源：[`apps/mobile/design/tokens.json`](../apps/mobile/design/tokens.json)
> 横切实现规范：[`mobile-app-development-global-guidelines.md`](mobile-app-development-global-guidelines.md)

## 1. 目的

Warm Page v2 保留 v1 的暖白色板、8pt 节奏、2:3 Cover、中文优先排版、单一主 CTA 和原生组件边界，但重新定义一套可以直接约束页面组合的设计语言。

v2 解决的不是“换一套皮肤”，而是以下系统性问题：

- 页面拥有令牌，却仍由各功能自行决定标题、容器、动作、图标和状态表达；
- 内容详情同时混合海报、工具面板、卡片、长列表和悬浮控件，缺少一条稳定的信息叙事；
- 平台 Menu、Navigation、Tab 等系统组件被页面稿冻结为自绘外壳；
- 同一状态被进度、颜色、文字、图标和大色块重复强调；
- 高保真资产、页面合同、ADR 和机器令牌的权威边界不清楚。

核心目标：

> **让内容成为第一视觉层，让组件退到任务之后；一屏只回答一个主要问题，一页只保留一个强动作。**

## 2. 决策权威按维度划分

不再使用“日期较新或页面稿更具体就覆盖全局规范”的隐式规则。每类决策只有一个所有者：

| 决策维度 | 唯一所有者 |
|---|---|
| 功能、API、权限、数据身份、离线与安全 | Phase 1，以及明确取代它的 Accepted ADR；Mobile 当前身份以 ADR 0020 的 `Book / ReadableResource / ResourceAsset` 为准 |
| 页面树、导航、返回与覆盖层类型 | Phase 2 |
| 用户任务、内容顺序、动作优先级和状态位置 | Phase 3 |
| 全局视觉语义、信息流语法和 C/App-owned 组件合同 | 本文件 |
| 精确颜色、间距、圆角、排版、Cover 和 Progress 数值 | `apps/mobile/design/tokens.json` |
| A/B 类原生组件所有权、平台行为、无障碍和验收 | 全局开发规范 |
| 页面构图和密度 | 当前有效的 Phase 5–7 页面合同与高保真锚点 |
| PNG、竞品截图和真机截图 | 视觉证据；不拥有功能、数据身份、系统组件外壳或令牌数值 |

页面补充合同不得冻结 Navigation、Tab、Menu、Sheet、Dialog、Picker、Slider、Switch 等平台拥有的几何、材质、阴影、转场或手势。若发生冲突，本文件与全局开发规范在各自维度内优先。

## 3. 设计方向：内容流，而不是组件展览

Warm Page v2 的视觉关键词：

- 内容优先；
- 连续信息流；
- 单一视觉锚点；
- 单一主任务；
- 安静、温暖、原生；
- 少量、稳定、可预测的组件；
- 通过排版、对齐、亮度和留白建立层级；
- 通过渐进披露控制复杂度。

参考优秀媒体详情页时，只吸收以下结构原则：

1. 内容身份先于工具；
2. 标题与必要元数据帮助用户迅速判断对象；
3. 主动作是全页唯一最高对比组件；
4. 次要动作主动降级；
5. 简介和具体内容按阅读顺序自然出现；
6. 下一内容区在首屏末端或滚动早期露出，形成继续探索的方向。

不得照搬影音产品的纯黑影院外观、横向剧照模型、五项底栏、视频专属元数据或明亮图片上的裸白工具图标。

## 4. 全局页面语法

### 4.1 根页面

根页面使用以下顺序：

```text
平台 Large Title / Large Top App Bar
当前页面的首要任务或状态
一个或多个连续内容区
适用的业务空态/错误态
平台 Tab / Navigation Suite
```

规则：

- 根页面标题由平台 Large Title 语义拥有，不用 `display` 强制替换系统导航字号；
- 页面可以有多个内容区，但每个区只承担一个清楚意图；
- 普通内容使用连续 Surface 和 Divider，不把每行包装成独立卡片；
- 只有独立任务对象，例如“继续阅读”，可以使用轻量任务容器；
- 当前 Tab 的选中形态由系统组件拥有，App 只提供语义图标和 Accent。

### 4.2 二级详情页

内容详情统一使用一条连续叙事链：

```text
系统返回 / 折叠标题 / 平台工具项
内容身份
必要元数据
进度与当前位置（适用时）
唯一 Primary Action
Secondary Actions
可选简介
可读资源、目录或资源内章节/曲目等内容导航
选中内容或列表
低优先级元数据与管理信息
```

用户进入详情后依次回答：

1. 这是什么内容？
2. 我上次到哪里？
3. 我现在最可能做什么？
4. 还有哪些次要操作？
5. 内容讲什么？
6. 具体可进入哪些资源？

规则：

- Hero 可见时不长期重复“图书详情”与大型内容标题；折叠后才由系统导航显示内容标题；
- 首屏只允许一个强 Primary Action；
- Secondary Actions 最多显示三个高频动作加“更多”；
- 没有简介时整个简介区消失，不显示“暂无简介”占位；
- 同一状态不能同时用大色块、进度、图标和重复文案多次强调；
- 低优先级文件路径、来源和技术元数据不得挤占首屏；
- 内容必须能完整滚动到 Tab、mini player、键盘和安全区之上，不硬编码底栏高度。

### 4.3 设置与管理页面

- 优先使用平台 `List`、`Form`、设置行、分组标题与系统控件；
- 连续相关设置组成一个分组，不把每个单行设置包装为巨大白色胶囊；
- 一个设置行固定为“图标（可选）—标题/说明—当前值/控件/chevron”；
- 管理任务超过 7 个即时命令、包含表单或需要滚动时，使用原生 Sheet 或 Page，不塞入 Menu；
- destructive 操作使用平台危险语义和系统确认，不使用品牌色弱化风险。

### 4.4 空、错与阻断状态

业务状态统一为：

```text
语义图标（可选）
一句状态标题
一句解释或恢复条件
最多一个 Primary Action
最多一个低强调 Secondary Action
```

- 空状态不能只留下大片空白；
- 错误状态说明用户能做什么，不暴露内部路径、堆栈或协议细节；
- Permission、Offline、Stale、Conflict 必须使用不同的稳定语义，不能都退化成通用错误页；
- 状态不能只靠颜色、图标或动画表达。

## 5. 内容身份与 Hero

内容身份有三种允许形态：

| 形态 | 适用对象 | 规则 |
|---|---|---|
| `coverIdentity` | 书籍、漫画、PDF、文档 | 默认形态；使用一张 2:3 Cover 或文档缩略图，配合标题和必要元数据 |
| `wideArtworkIdentity` | 服务端确实提供可安全裁切的横向主视觉 | 允许全宽图片与功能性对比遮罩；必须有焦点区域和安全裁切元数据 |
| `immersiveMediaIdentity` | Now Playing 等明确沉浸媒体页面 | 仅在对应页面合同授权时使用；不自动推广到普通详情页 |

禁止：

- 把竖版 Cover 放大、裁切或模糊成全屏背景；
- 从 Cover 自动取色生成不可预测的渐变或光晕；
- 为了“高级感”叠加玻璃、噪点、纸纹、霓虹或装饰性阴影；
- 图片和内容区突然切换成另一套卡片语言；
- 在没有合格横向主视觉时模仿视频详情页。

`wideArtworkIdentity` 可以使用唯一的功能性 scrim 保证文字对比度。scrim 必须由语义令牌定义，只用于可读性，不作为装饰渐变；当前令牌集尚未定义该角色，因此普通 Book Detail 不得提前实现该形态。

## 6. Surface 与视觉层级

每个外观只有三层通用表面，精确数值来自令牌文件：

1. `canvas`：页面与 Reader 基础平面；
2. `surface`：连续列表、局部任务区域和 Sheet 内容；
3. `surfaceRaised`：系统语义要求抬升的浮层内容背景。

规则：

- 先使用留白、对齐、字号和 Divider，再考虑容器；
- 普通列表行、设置行、Tab 和 Reader 正文不使用投影；
- 同一首屏不连续堆叠多个 Raised Surface；
- 只有 Cover 可以有轻微暖色、低扩散投影；
- 普通选中状态使用 `accentSoft + brandAccent indicator + textPrimary`，不得制造第二个与主 CTA 等强的大色块；
- Sheet、Menu、Dialog 的外形、材质、抬升、遮罩和动画完全服从平台。

## 7. 颜色职责

具体色值以令牌文件为唯一真相。本文件只冻结语义职责：

| Token | 职责 |
|---|---|
| `canvas` | 页面基础画布 |
| `surface` | 连续内容和局部任务区 |
| `surfaceRaised` | 明确浮层的内容背景 |
| `textPrimary` | 标题、正文和关键状态 |
| `textSecondary` | 作者、元数据和辅助说明 |
| `textTertiary` | 禁用或具有其他可访问说明的非关键内容 |
| `divider` | 连续内容边界和轨道背景 |
| `brandAccent` | 进度、选中 Tab、选中图标和非文字焦点 |
| `actionAccent` | 全页唯一实心 CTA、满足正文对比度的交互文字 |
| `accentSoft` | 弱选中背景和局部提示 |
| `onAction` | `actionAccent` 上的前景 |

硬规则：

- 每个页面最多一个实心 `actionAccent` CTA；
- 珊瑚红不表达 error、destructive、offline、permission 或 warning；
- 普通文字对比度至少 `4.5:1`；大文字和必要图形至少 `3:1`；
- `textTertiary` 不得独立承载操作、进度、错误或阅读状态；
- App Dark 是 Warm Page 的暖墨色派生，不是另一套产品语言。

## 8. 排版角色

精确字号、行高和字重以令牌文件为准。使用边界如下：

| Role | 使用场景 |
|---|---|
| 平台 Large Title | 根页面标题；不由 App 数值令牌强制覆盖 |
| 平台 inline/collapsing title | 二级详情导航标题 |
| `display` | 页面内容中的大型身份标题；禁止用于 Navigation/TopAppBar |
| `title` | Book、集合和主要详情身份 |
| `sectionTitle` | 内容一级区块 |
| `headline` | 行标题和任务对象标题 |
| `body` | 正文和简介 |
| `callout` | 状态与辅助说明 |
| `label` | 控件、Tab 和短标签 |
| `caption` | 格式、时间、序号和进度数字 |
| `button` | Primary/Secondary Action 文本 |
| `reader*` | Reader 专属排版，不进入 App Shell |

规则：

- 一个屏幕最多使用 regular、semibold、bold 三种字重；
- 不使用负字距压缩中文；
- 不为了固定列数或动作数量缩小字体；
- 用户标题、作者、文件名和路径保持原文；视觉截断时保留完整无障碍值；
- 最大字体下标题允许换行，Secondary Actions 自动变成 2×2 或列表，资源轨道减少可见项。

## 9. 间距、对齐与响应

间距只使用令牌文件中的 `space0` 至 `space8`。

- Compact 页面水平基线使用 `space2`；Expanded 使用 `space3` 至 `space4`；
- 相关元素之间使用 `space1` 至 `space2`；
- 内容区块之间使用 `space3`；一级章节之间使用 `space4`；
- 控件内部只使用 `space1`、`space1_5` 或 `space2`；
- 一页优先保持一条主内容左边线；只有身份图和真正的空状态可以有意居中；
- 系统导航和状态栏安全区由平台处理，页面不得复制顶部空白；
- 底部内容 inset 等于系统 Tab/rail 或 mini player 的实际占位、安全区与 `space2` 之和；
- Expanded 使用双栏时，左侧身份/主动作与右侧内容导航仍属于同一语义状态。

## 10. 动作层级

### 10.1 Primary Action

- 开始/继续阅读、打开文档或开始/继续播放；
- 全页唯一实心、高对比动作；
- 位于身份与状态之后，次要工具之前；
- Loading 时保留动作文案并附加系统 Progress；
- 不可用时同时显示真实原因，不只变灰。

### 10.2 Secondary Actions

- 最多三个高频动作加“更多”；
- 使用标准平台图标和始终可见的文字标签；
- 不使用与 Primary 相同的实心大背景；
- 已下载、已加入、已完成同时提供文字或 selected trait，不只变色；
- 大字体下允许重排，不缩小触摸目标。

### 10.3 Tertiary 与 Destructive

- 展开简介、查看全部和局部重试属于 Tertiary；
- destructive 只能进入系统 Menu/Dialog 或明确管理任务；
- ADR 0020 不以 `bookDetailManagement` 全局关闭或全局放开原生 Book Detail 管理能力；目录、资源和图书管理动作的对象范围与权限过滤直接跟随 Web Work Detail 当前实现，未授权动作不渲染，高风险动作仍使用平台危险语义与确认。

## 11. 图标系统

Feature 只能请求语义图标角色，不得自行选择平台资源名或引入新图标库。

### 11.1 平台来源

- iOS 使用 SF Symbols；
- Android 使用 Material Symbols Rounded；
- 系统导航、返回、关闭、更多、搜索、筛选、分享、下载、播放和状态图标禁止自绘；
- iOS/Android 分别映射语义，不共享同一 SVG 来制造跨平台同形。

### 11.2 最小语义注册表

```text
nav.back
nav.close
nav.more
tab.home
tab.library
tab.shelves
tab.me
action.download
action.readingStatus
action.addToShelf
action.play
action.share
state.selected
state.completed
state.offline
media.ebook
media.comic
media.audio
```

规则：

- 默认业务图标使用令牌约定的 24pt/dp 光学尺寸，Toolbar 使用 20pt/dp；
- 图标放在至少 iOS 44pt、Android 48dp 的完整触摸区内；
- 同一平台保持一致的 weight、grade、optical size 与 filled/outline 状态；
- 已选 Tab 和明确完成状态可以使用 filled，其余默认 outline；
- 图标加标签时组成一个无障碍节点；纯图标必须有 `zh-CN`/`en-US` label；
- 方向性图标支持 RTL；
- 猫 Logo 只作为品牌资产，不作为功能图标或装饰水印。

禁止：

- Emoji、Unicode 箭头、文字模拟图标；
- 同一页面混用多个图标库、不同线宽或无语义的装饰图标；
- 用统计饼图作为“阅读状态”的唯一表达；
- 同一个书本图标同时代表书库、加入书架和阅读状态；
- 仅靠颜色区分状态。

## 12. Cover 与 Progress

- Book Cover 统一使用 2:3 展示框和 `contain`；不裁掉封面文字和关键画面；
- Compact 与 Hero 使用各自语义圆角；
- Fallback Cover 与真实 Cover 使用相同尺寸和语义，不绘制误导性的假封面；
- Comic/PDF 内容页面不强制套用 Cover 比例；
- Cover Progress、普通阅读进度、下载进度和系统 Slider 是四种不同语义，不复用形态；
- 阅读进度必须同时具有可访问百分比与位置；
- 下载状态使用未下载、进行中、暂停、失败和完成的稳定语义；
- 100% 完成使用标准完成 glyph，不使用粒子、烟花或庆祝动画。

## 13. 语义组件合同

iOS 与 Android 共享组件名称、任务、状态、令牌和无障碍合同，但分别用 SwiftUI 与 Compose 原生实现。

| 组件 | Owner | 职责 |
|---|---|---|
| `AppScaffold` | A/C | 使用平台 Navigation/Tab，向内容提供安全区和真实底部 inset |
| `ContentFlow` | C | 统一内容轴、区块节奏和滚动顺序 |
| `ContentIdentity` | C | Cover/Artwork、标题和必要元数据 |
| `PrimaryContentAction` | C/B | 唯一主动作及 loading/unavailable 状态 |
| `SecondaryActionStrip` | C | 最多三个动作加更多，大字体时重排 |
| `ReadingProgressSummary` | C | 百分比、位置与业务 Progress |
| `ContentSection` | C | 区块标题、可选动作与连续内容 |
| `ResourceRail` | C | ReadableResource 封面/缩略图、选择、分页与失败 |
| `MetadataList` | C | 低优先级只读键值信息，长值可访问 |
| `BusinessStateView` | C | Loading/Empty/Error/Offline/Permission/Conflict/Stale |
| `ReaderChrome` | C/D/A | Reader 业务控制组合；导航、Slider 和系统行为仍归平台 |

每个组件注册项必须包含：

```text
owner
semantic role
content slots
states and variants
token usage
iOS mapping
Android mapping
accessibility contract
compact/expanded behavior
localization behavior
visual-regression region
```

组件 API 不得暴露 `sheetCornerRadius`、`tabHeight`、`backAnimationDuration`、`sliderThumbShape` 等平台所有参数。

## 14. 组件所有权

| 类别 | 所有者 | 典型对象 | 核心规则 |
|---|---|---|---|
| A/System-owned | 平台 | Navigation、Tab、Sheet 外壳、Menu、Dialog、Picker、权限、分享、返回手势 | App 只提供内容、语义角色、Accent 和无障碍信息；不得重绘外壳 |
| B/Native-themed | 平台行为，App 主题 | Search、TextField、Switch、Slider、Segmented control、Refresh、Loading | 允许官方 tint 与标签；禁止自绘物理、焦点和按压 |
| C/App-owned | App | Cover、内容身份、主 CTA、业务 Progress、资源轨道、状态页、Reader 内容 | 严格使用令牌和本文件组件合同；按平台分别实现 |
| D/Approved-motion | App | Reader controls、翻页 settle、程序跳页、确定型 Progress | 只使用批准参数；Reduced Motion 必须降级 |

所有权按“谁拥有行为”判断，不按“谁能修改颜色”判断。

## 15. 平台映射

### 15.1 iOS

- 使用 `NavigationStack`、`TabView`、系统 `Menu`、`Sheet`、`Alert`、`Picker`、`Search` 与原生控件；
- 使用系统 Large Title 与 inline/collapsing title，不用 Web 式自绘 Header；
- 使用 SF Symbols 与 Dynamic Type；
- 保留 edge-back、系统材质、焦点恢复、Reduced Motion/Transparency；
- App-owned 内容使用 SwiftUI 布局原语实现，不模拟 Android Material 外形。

### 15.2 Android

- 使用 Compose Material 3 与 Adaptive 的 Navigation、系统 Menu、Dialog、Sheet、Search 和控件行为；
- 使用 predictive back、Window Size Class 和真实系统 inset；
- 使用 Material Symbols Rounded 与字体缩放；
- App-owned 内容由 Warm Page 语义组件包裹，不把默认 Material 卡片语法带入产品；
- 不以全屏 `Dialog` 模拟 anchored Menu。

跨平台验收追求任务、层级、状态和品牌一致，不追求系统控件逐像素相同。

## 16. 国际化与无障碍

- 所有用户可见文本、label、value、hint 同时完成 `zh-CN` 与 `en-US`；
- 用户书名、作者、系列、标签、路径和文件名保持原文；
- 日期、数字、百分比和相对时间使用当前 Locale；
- iOS 触摸目标至少 44pt，Android 至少 48dp；
- VoiceOver/TalkBack 顺序与视觉顺序一致；
- 多个按钮不能被合并成一个无从操作的节点；
- 可交互 Resource Cover 读出标题、集合位置、选中、下载和阅读状态；
- 只有真正可调整的 Slider 声明 adjustable；
- Modal 打开后聚焦标题或首任务控件，关闭后回到触发控件；
- 最大字体不能遮挡 CTA、Tab、Sheet 动作或 Reader controls；
- Reduced Transparency 时浮层使用不透明 Surface；
- Reduced Motion 时取消位移和非必要 settle，但状态仍可理解。

## 17. 动效

Navigation、Tab、Sheet、Menu、Dialog、Picker、返回、按压、焦点、键盘和系统权限反馈使用系统动效。

允许的 App 动效仅限：

- Reader controls 短时显示/隐藏；
- Reader 手势 settle；
- Reader 程序跳页；
- 确定型 Progress 的短线性更新。

精确时长由令牌或现有批准合同拥有。禁止通用 spring、统一按压缩放、卡片悬浮、matched geometry、自定义页面转场、循环呼吸、装饰波形、粒子和 skeleton shimmer。

## 18. 禁止清单

1. Feature 内硬编码十六进制颜色、任意 dp/pt、圆角、阴影或动画时长；
2. 在 TopAppBar/NavigationBar 使用 `display` 或自定义最小高度；
3. 自绘返回、Tab、Sheet、Menu、Dialog、Picker、Switch、Slider 或 Search；
4. 用全屏 Dialog/ZStack 遮罩模拟 anchored Menu；
5. 用模糊 Cover、封面取色、装饰渐变、玻璃或纹理制造普通 Book Hero；
6. 普通行卡片化、嵌套卡片或每个设置项独立胶囊；
7. 一页多个实心品牌 CTA；
8. 用珊瑚红表达错误、危险、离线、警告或权限；
9. Feature 直接引用平台图标资源名，绕过语义图标注册表；
10. Emoji、文字箭头、混合图标库或颜色唯一状态；
11. 硬编码 Tab、导航、键盘或状态栏高度；
12. 固定高度文字容器、压缩字体或缩小触控目标来维持截图；
13. 长按、滑动、颜色或动画作为唯一入口/表达；
14. 在页面稿中冻结系统 Menu/Sheet/Dialog 的圆角、材质、阴影和转场；
15. 用跨平台逐像素相同验收 A/B 类系统组件；
16. 没有 owner、状态、无障碍合同和移除条件的视觉例外；
17. 页面级设计合同重新定义已被 Accepted ADR 取代的数据身份或 capability。

## 19. 验收门禁

### 19.1 静态政策

- 所有可见组件在注册表中具有 A/B/C/D owner 和双端 mapping；
- Feature 不出现原始色值、未登记间距、圆角、动效或平台图标资源名；
- Top bar 未应用 `display` 或自定义高度；
- Android 不以全屏 Dialog 实现 Menu，iOS 不以页面 Overlay 模拟系统 Menu；
- 每个 icon-only 控件具有中英文无障碍名称；
- 所有例外具有 owner、原因、真机测试、复审日期和移除条件。

### 19.2 视觉与响应

- C 类区域严格截图回归；A/B 类按平台与 OS 大版本建立独立基准；
- 一屏最多一个实心 Accent CTA；
- 不存在被 Tab、mini player、键盘或系统栏遮挡的内容；
- 默认字号、最大字号和长英文下没有裁切、重叠或关键动作消失；
- Light/Dark、`zh-CN`/`en-US`、Compact/Expanded 均有证据；
- Reduced Motion 和涉及浮层的 Reduced Transparency 均通过；
- 截图必须人工确认显示真实目标页面，不能只因文件存在而判定通过。

### 19.3 行为与无障碍

- iOS edge-back、Android predictive back 和覆盖层关闭顺序正确；
- Tab 独立 Stack 和返回状态可恢复；
- Menu/Sheet/Dialog 关闭后焦点回到触发控件；
- VoiceOver/TalkBack 能读出标题、资源位置、选择、进度、错误和 CTA 状态；
- Secondary Actions 在最大字体下正确重排；
- 触控目标达到 44pt/48dp；
- Reader/Now Playing 的沉浸规则与普通详情 Shell 不混用。

### 19.4 真机证据清单

每张当前验收图必须记录：

```text
visualSpecId
tokenSetVersion
screenContractId
build SHA
device model / serial
OS version
locale
appearance
font scale
reduceMotion
reduceTransparency
business state
capture timestamp
```

iOS 最终证据只接受物理设备；Android 最终证据默认物理设备。历史截图、锁屏、错误窗口、模拟 Fixture 和与当前源码不一致的图片不得作为当前通过证据。

## 20. 迁移顺序

### P0：恢复权威边界

- 以 ADR 0020 的 Book/ReadableResource/ResourceAsset 身份替代旧 Work/Version/Volume 表达；
- Book Detail 管理动作与 Web Work Detail 当前对象范围和权限过滤对齐，不再把 capability 解释为全局关闭开关；
- 退役自定义半透明控制菜单，恢复平台 Menu/Sheet 所有权；
- 修复系统导航标题、Tab/mini player inset、被遮挡内容和非标准触控目标；
- 移除普通 Book Hero 的 Cover blur、封面取色与装饰渐变。

### P1：建立组件合同

- 建立语义图标注册表；
- 实现并迁移 `ContentFlow`、`ContentIdentity`、`PrimaryContentAction`、`SecondaryActionStrip`、`ResourceRail`、`MetadataList` 和 `BusinessStateView`；
- 让 iOS/Android 各自使用原生组件，但共享语义、状态、令牌和验收合同；
- 补齐 App 与 Reader 的单一机器令牌来源。

### P2：页面迁移与证据

- 先迁移 Book Detail、Library、Reader，再迁移 Home、Shelves、Downloads、Me 与设置；
- 重新生成当前页面高保真锚点；
- 建立分层视觉回归、静态政策检查和完整真机 evidence manifest。

## 21. 版本说明

`warm-page@2.0.0` 是全局视觉系统版本；`tokens.json.schemaVersion` 是序列化结构版本；`tokenSetVersion` 是数值集合版本；页面 PNG、Book Detail 合同和 QA run 各自拥有独立版本，不再用模糊的“v2”互相覆盖。

Warm Page v1.1 的历史内容由 Git 保留。`docs/assets/mobile-app-hifi-v1/` 是稳定历史路径，目录名不表示当前全局视觉系统版本；单个资产只在当前页面合同明确选中时才具有构图证据效力。
