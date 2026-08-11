# 移动 App 全局开发规范：原生体验与设计还原

> 状态：已采纳的横切实现规范
> 版本：1.0
> 决策日期：2026-08-11
> 适用范围：`apps/mobile` 的 iOS/Android 设计交付、技术选型、组件实现、页面开发、测试与代码审查
> 产品与视觉依据：[`mobile-app-phase-1-web-to-app-functional-baseline.md`](mobile-app-phase-1-web-to-app-functional-baseline.md)、[`mobile-app-phase-2-information-architecture.md`](mobile-app-phase-2-information-architecture.md)、[`mobile-app-phase-3-user-flows-and-wireframes.md`](mobile-app-phase-3-user-flows-and-wireframes.md)、[`mobile-app-phase-4-visual-master.md`](mobile-app-phase-4-visual-master.md) 与 [`mobile-app-phase-5-high-fidelity-anchors.md`](mobile-app-phase-5-high-fidelity-anchors.md)

## 1. 目的与权威边界

本文件解决 Mobile 开发中的一个横切问题：在保留 iOS/Android 原生组件行为、系统手势和系统动效的同时，最大程度还原“暖白书页”的设计意图。

它不是新的产品阶段，也不重新定义功能、路由、内容顺序或视觉令牌。Phase 1–5 继续分别拥有以下真相：

1. Phase 1：功能、API、权限、数据、离线与阶段范围；
2. Phase 2：页面归属、导航、返回、Page/Sheet/Menu/Dialog 语义；
3. Phase 3：任务流、内容顺序、动作优先级与状态位置；
4. Phase 4：视觉令牌、排版、Cover、Progress、图标与动效规则；
5. Phase 5：已冻结页面的构图和视觉密度证据；
6. 本文件：原生组件边界、设计还原方法、平台差异、工程约束与验收方法。

发生冲突时，先按 Phase 1–4 确认产品与视觉意图，再由本文件决定如何映射到平台。Phase 5 PNG、概念板和单次截图不得覆盖文字规范、系统行为、无障碍或平台安全区。

## 2. 核心原则

> **追求设计意图一致，而不是强迫系统组件跨平台逐像素一致。**

必须同时满足：

- 业务视觉一致：信息层级、动作优先级、语义颜色、排版角色、间距节奏、Cover、Progress 和状态表达可被识别为同一产品；
- 平台体验原生：导航、返回、覆盖层、触摸反馈、焦点、键盘、系统权限、系统媒体和通用控件遵守所在平台；
- 用户设置优先：Dynamic Type/字体缩放、VoiceOver/TalkBack、Reduced Motion、Reduced Transparency、系统深浅外观与安全区不能为了截图相似度被破坏；
- 功能语义等价：iOS 与 Android 可以使用不同外形和平台容器，但任务、提交、取消、危险级别和状态恢复必须等价。

“最大程度贴近设计稿”只适用于 App 拥有的视觉区域。系统拥有的区域以组件类型、语义、位置、内容和 Accent 正确为准，不以像素相同为准。

## 3. 原生组件的判定

“原生”由行为和所有权判定，不由开发语言、组件名称或是否来自某个跨平台包判定。

一个通用控件只有在以下条件全部成立时，才可视为满足本项目的原生要求：

- 使用平台官方 UI 能力，或明确映射到相应官方能力；
- 保留系统触摸反馈、焦点、键盘、手势冲突处理和无障碍语义；
- 自动响应系统外观、字体缩放、Reduced Motion/Transparency 和平台返回机制；
- 不通过 Canvas、图片、WebView 或通用手势层仿制系统控件的外形与物理行为；
- 不需要复制系统私有动画参数或监听未公开生命周期来维持表象。

仅仅把自绘组件命名为 `NativeSheet`、`SystemSlider` 或使用平台相似图标，不构成原生实现。

## 4. 组件所有权矩阵

每个可见组件在设计交付和编码前必须归入以下一类。无法归类时先停止实现并完成所有权判断，不得先自绘再补理由。

| 类别 | 所有者 | 典型对象 | 允许定制 | 禁止事项 | 验收方式 |
|---|---|---|---|---|---|
| A. 系统容器与系统界面 | 平台 | Navigation、Tab、Sheet 外壳、Menu、Dialog、Picker、系统权限、文件/照片/分享、edge-back、predictive back | 官方 API 支持的 presentation、Accent、内容、按钮角色和无障碍信息 | 重绘外壳、复制圆角/阴影、替换返回手势、自定义系统转场 | 平台语义、行为、焦点、返回和真实设备验收 |
| B. 可主题化原生控件 | 平台行为，App 主题 | Slider、Switch、分段控件、原生 loading、原生文本输入 | 官方 API 支持的 tint/Accent、语义颜色、标签、格式、状态和布局占位 | 自绘 thumb、拖拽物理、焦点环、按压动画或私有样式注入 | 行为严格验收，外观按平台分别截图 |
| C. App 自有业务视觉 | App | Cover、作品行/网格、继续阅读、主 CTA、业务空状态、行内错误、业务 Progress、Reader 内容与控制层组合 | 严格使用 Phase 4 令牌和组件契约进行原生布局组合 | 绕过 token、复制 Web CSS、用系统控件差异解释业务布局偏差 | 内容区域视觉回归与设计锚点对照 |
| D. 明确许可的业务动效 | App | Reader controls、Reader 翻页 settle、程序跳页、确定型 Progress | 只允许 Phase 4 已列参数和 Reduced Motion 降级 | 建通用动画系统、全局 spring、卡片悬浮、庆祝动画、自定义页面转场 | 时序、状态、取消、降低动态效果验收 |

所有权按“谁拥有行为”判断，不按“谁能修改颜色”判断。例如 Sheet 内容属于 App，但 Sheet 的形状、遮罩、拖拽、detent 物理和关闭转场属于平台。

## 5. 设计还原的三种精度

### 5.1 必须精确还原

以下内容跨平台保持同一语义，并在平台可比范围内严格还原：

- Phase 3 的内容顺序、任务层级、主次动作与状态位置；
- Phase 4 的语义颜色映射、8pt 间距、排版角色、Surface 层级和对比度；
- Cover 比例、裁切策略、圆角角色、占位与业务 Progress；
- 每页最多一个强主 CTA，以及阅读/播放优先于下载和整理动作；
- loading、empty、error、offline、permission、success、conflict、stale 的业务含义；
- `zh-CN`、`en-US` 文案语义、插值内容和本地化格式；
- compact/expanded 的信息层级等价与既定适配规则。

### 5.2 必须平台适配

以下内容使用平台语义，不以跨平台同形为目标：

- 系统导航栏标题度量、状态栏、安全区和系统字体的细微差异；
- Sheet、Menu、Dialog、popover 的圆角、阴影、遮罩、位置与 presentation；
- Tab、Switch、Slider、Picker、分段控件和 loading indicator 的具体几何形态；
- SF Symbols 与 Material Symbols 的光学差异；
- iOS edge-back、Android predictive back、按压反馈、焦点、键盘和系统转场曲线；
- iPad form sheet/popover/split view 与 Android expanded navigation 的平台形态。

### 5.3 必须用户自适应

以下状态允许并要求偏离静态高保真图：

- 字体放大导致标题换行、网格降列、列表化或 Sheet 升为 full-height；
- Reduced Motion 取消位移、翻页 settle 和程序跳页动画；
- Reduced Transparency 把浮层切换为不透明 Surface；
- 长英文、RTL、横屏、分屏、键盘弹出和系统栏变化引起的重排；
- 平台系统升级带来的官方组件视觉变化。

不得通过压缩字号、缩小触摸目标、截断关键动作或关闭系统能力来维持截图相似度。

## 6. 实现模式：原生容器 + 品牌内容

### 6.1 系统容器保留平台所有权

Navigation、Tab、Sheet、Menu、Dialog 和 Picker 必须由平台创建、展示和关闭。App 只向其提供：

- 业务内容与当前状态；
- 标题、说明和本地化按钮文本；
- primary、cancel、destructive 等语义角色；
- 官方 API 支持的 detent、presentation 或选项；
- 触发控件、关闭后的焦点恢复目标和无障碍信息。

不得由页面自己模拟返回栈、遮罩层、Sheet 拖拽、Dialog 焦点陷阱或系统权限界面。

### 6.2 品牌内容使用语义令牌

系统容器内部的 App 内容必须使用 Phase 4 语义令牌，而不是从 PNG、平台默认主题或 Web CSS 复制数值。移动工程建立时，应从一个权威 token 源生成或映射 iOS/Android 主题值，并满足：

- 业务代码只引用 `canvas`、`surface`、`textPrimary`、`actionAccent`、`space.2` 等语义名；
- 平台适配层负责把语义名映射为当前外观的动态颜色和尺寸；
- 禁止在页面或业务组件中散落十六进制颜色、任意间距和平台判断；
- 系统状态色使用平台 success/warning/error，不以品牌色替代；
- token 变更必须同时验证 App Light、App Dark、Reader Paper 与 Reader Night 的适用面。

### 6.3 语义适配器而非仿原生组件

共享 UI 可以提供 `AppSheet`、`AppSlider`、`AppNavigation` 等语义入口，但适配器必须薄，并遵守：

- API 描述任务和角色，不暴露系统外壳的私有几何参数；
- 内部调用平台官方 presentation/control；
- 不统一 iOS/Android 本应不同的触摸反馈、返回行为或转场；
- 不把 feature 业务规则塞入共享控件；
- 不让页面通过布尔开关逐步把一个系统适配器变成自绘组件；
- 平台不支持的视觉参数应从适配器 API 中删除，而不是用手势层或覆盖层强行补齐。

推荐暴露 `role`、`value`、`label`、`content`、`onConfirm`、`onCancel` 等语义输入；禁止暴露 `thumbShape`、`sheetCornerRadius`、`backAnimationDuration` 等平台所有参数。

## 7. 组件专项规则

### 7.1 Navigation 与 Tab

- iOS 使用 NavigationStack/系统 presentation 语义；Android 使用平台导航目的地与 predictive back；
- 页面可以定制内容布局和官方 toolbar item，不得自绘 Web 式 header 替代系统导航；
- 返回、关闭、更多和 Tab 图标使用平台字形；
- 四个 Tab 的身份、独立 Stack 和状态恢复由 Phase 2 决定，不因平台控件差异改变；
- Tab/rail 的具体高度、背景材质和选中动效由平台拥有，App 只提供语义 Accent 和正确图标状态。

### 7.2 Sheet、Menu 与 Dialog

- 覆盖层类型严格按 Phase 2 注册表选择，不能为了更像设计稿互换；
- Sheet 外壳、拖拽柄、detent、遮罩和关闭动效由平台拥有；Sheet 内容区遵守 App 排版、间距、Divider 和 CTA 层级；
- Menu 只承载有限即时命令或简单单选，不以自制 popover 获得统一外观；
- Dialog 使用系统标题、消息、按钮角色和危险语义，不以品牌色弱化 destructive；
- iPad/expanded 的 form sheet、popover 或侧栏适配保持同一任务、提交和取消语义。

### 7.3 Slider、Switch、分段控件与输入

- 保留系统 thumb、拖拽物理、焦点、键盘、选中和按压反馈；
- 只使用官方 API 修改 Accent、轨道语义色、标签、格式与禁用状态；
- 如果平台无法安全实现设计稿中的几何细节，设计稿必须改为对应平台版本；
- 触摸区、读屏步进、错误描述和输入法行为优先于可见轨道或边框尺寸；
- Reader/Audio scrubber 不得通过视觉覆盖截断原生无障碍节点。

### 7.4 App 自有业务组件

- Cover、书目行、业务 CTA、业务 Progress、状态视图和 Reader 内容是主要设计还原区域；
- 使用平台原生布局、文本、图片和绘制基础能力组合，不复制 Web DOM/CSS 结构；
- 普通列表保持连续 Surface；只有规范允许的独立任务对象使用容器；
- 组件在 iOS/Android 上共享业务语义和 token，不要求共享完全相同的内部实现；
- 业务组件不得自行拥有导航、全局 modal、权限请求或跨页面生命周期。

## 8. 动效、反馈与手势

- Navigation、Tab、Sheet、Menu、Dialog、Picker、系统返回、按压、焦点、键盘和系统权限反馈使用系统动效；
- Reader 与 determinate Progress 只使用 Phase 4 明确许可的参数；
- 不建设通用 Mobile 动画库，不引入全局 spring、matched geometry、自定义页面转场或统一按压缩放；
- 成功、撤销和轻量更新优先使用平台反馈与 Snackbar，不增加庆祝或装饰动效；
- 业务手势不得覆盖 edge-back、predictive back、系统缩放、辅助技术手势或系统媒体手势；
- 所有自定义手势必须有可见、键盘或辅助技术可操作的等价入口；
- Reduced Motion 下动效降级后，状态变化仍必须可被文本、图标或布局理解。

## 9. 设计交付规范

每个高保真页面和组件说明必须标记组件所有权，至少包含：

- `A/System-owned`、`B/Native-themed`、`C/App-owned` 或 `D/Approved-motion`；
- 使用的 Phase 4 语义 token 与组件角色；
- iOS 与 Android 使用的原生表现形态；
- default、pressed/selected、disabled、loading、error 和适用业务状态；
- Dynamic Type/字体缩放、长英文、深色、Reduced Motion/Transparency 的变化；
- 哪些尺寸是冻结值，哪些是平台语义，哪些只是参考图表现。

设计源文件应同时提供 iOS 与 Android 参考帧，至少覆盖系统控件密集的导航、Sheet、Dialog、表单、Reader 和 Now Playing。不得在一张平台无关画板中冻结系统控件的圆角、阴影和动效，再要求两个平台共同复制。

设计审查必须先确认所有权，再讨论像素偏差。没有所有权标记的系统控件密集页面不得进入实现。

## 10. 冲突裁决与例外

当实现与设计稿不一致时，按以下顺序处理：

1. 确认差异属于 A、B、C、D 哪一类；
2. C 类差异直接按 Phase 3–4 修正实现，不能以“原生限制”解释业务布局漂移；
3. B 类优先使用平台公开主题 API，在不改变行为和无障碍的前提下接近视觉目标；
4. A 类若已满足平台语义，则修订对应平台设计参考，不重绘系统组件；
5. D 类只能在 Phase 4 已授权参数内调整；超出范围必须先修订规范；
6. 若品牌核心确实需要自定义交互，必须提交显式产品决策，而不是在组件代码中形成事实例外。

例外记录至少说明：

- 用户任务与无法由原生能力满足的具体原因；
- 官方能力和可访问替代方案的验证结果；
- iOS/Android 行为、返回、焦点、Reduced Motion 和升级兼容影响；
- 设计、产品和工程共同接受的边界；
- 自动化与真实设备测试，以及移除或复审条件。

“为了像设计稿”“跨平台看起来一致”或“组件库更方便”不是有效例外理由。

## 11. 国际化与无障碍

- 所有用户可见文本、系统按钮补充说明、accessibility label/value/hint 同时完成 `zh-CN` 与 `en-US`；
- 系统提供的通用文案优先使用平台本地化，不自行拼接仿系统文案；
- 用户提供的书名、作者、系列、书架、服务器名称和路径保持原文；
- iOS 触摸目标至少 44pt，Android 至少 48dp；
- modal 打开后焦点进入标题或首个任务元素，关闭后回到触发控件；
- Dynamic Type/字体缩放不得遮挡 CTA、Sheet 底部动作、Dialog destructive action 或 Reader controls；
- VoiceOver/TalkBack 必须读出标题、选择、进度、错误、同步和离线状态；
- 颜色、动效、位置或手势不能成为理解状态或完成任务的唯一方式。

无障碍导致的布局变化属于正确实现，不属于设计偏差。

## 12. 验收与自动化

### 12.1 分层视觉回归

- C 类 App 自有内容区域使用严格截图回归，验证 token、间距、排版、Cover、Progress、内容顺序和状态层级；
- A/B 类系统区域按平台和 OS 大版本保存独立基准，不与另一平台或概念 PNG 逐像素比较；
- 对系统动画、动态材质、字体抗锯齿和系统栏使用区域遮罩或合理容差，不能用扩大整页阈值掩盖 C 类偏差；
- Phase 5 PNG 只用于构图和视觉密度对照；实现基准必须来自受控平台版本上的真实组件；
- 系统大版本改变官方组件外观时，先验证行为和语义，再更新该平台基准，不反向仿制旧系统。

### 12.2 行为验收

至少验证：

- iOS edge-back、Android predictive back 和覆盖层关闭顺序；
- Sheet detent/展开、Menu 选择、Dialog cancel/destructive 与焦点恢复；
- Slider/Switch/分段控件的触摸、键盘和读屏操作；
- 系统文件、照片、分享、权限和媒体能力使用真实系统界面；
- App 切后台、旋转、分屏、键盘、Tab 切换和状态恢复；
- Reader 自定义手势不抢占系统返回和辅助技术手势。

### 12.3 验收矩阵

每个新增或实质修改的可见能力至少覆盖：

- iOS Compact 与 Android Compact；
- App Light 与 App Dark；Reader 另覆盖 Paper/Night/system；
- `zh-CN` 与 `en-US`；
- 默认字体与大字体；
- Reduced Motion，涉及浮层时另测 Reduced Transparency；
- loading、empty、error、offline、permission、success、conflict、stale 中适用状态；
- 至少一台真实 iOS 设备和一台真实 Android 设备上的核心任务。

### 12.4 政策检查

移动工程建立后，应增加自动化政策检查，至少阻止：

- 页面业务代码散落原始颜色、任意间距或未登记动画时长；
- 自绘或图片化的返回、Tab、Switch、Slider、Picker、Dialog 和系统状态图标；
- 绕过统一 presentation 入口创建全局 modal；
- 未本地化的可见字符串和 icon-only 控件；
- 缺少 Reduced Motion 降级的 D 类动效；
- 使用截图阈值或测试跳过掩盖业务视觉回归。

## 13. 代码审查清单

每个涉及 Mobile UI 的变更必须回答：

1. 该组件属于 A/B/C/D 哪一类，所有权是否与设计交付一致？
2. 是否使用平台官方组件和公开 API，保留系统行为与无障碍？
3. App 自有部分是否只使用 Phase 4 语义 token？
4. 是否出现为了统一外形而自绘系统组件或覆盖系统手势？
5. iOS/Android 的任务、提交、取消、返回和危险语义是否等价？
6. Dynamic Type、长英文、深色、Reduced Motion/Transparency 是否有明确结果？
7. 视觉测试是否只对 C 类区域严格比较，并对系统区域采用平台基准？
8. 是否有未记录的组件例外、动画参数或平台分支？

任一问题无法回答时，该 UI 变更未达到评审条件。

## 14. Definition of Done

Mobile 可见能力只有在以下条件全部满足时才算完成：

- 功能、IA、流程、视觉和构图分别符合 Phase 1–5；
- 每个组件完成 A/B/C/D 所有权归类；
- 系统容器和通用交互保持原生，App 自有业务视觉达到设计锚点；
- 不存在用自绘控件、私有样式或手势覆盖换取截图相似度的实现；
- iOS/Android 平台差异有设计说明和独立验收证据；
- `zh-CN`、`en-US`、大字体、读屏、Reduced Motion/Transparency 和触摸目标通过；
- 分层截图、行为测试、真实设备核心任务和适用异常状态通过；
- 没有未记录例外、临时兼容分支、被放宽的截图阈值或被跳过的测试。

最终交付的标准不是“两个平台看起来完全相同”，而是“两个平台都明显属于同一产品，并且在各自平台上表现得像一个真正的原生 App”。
