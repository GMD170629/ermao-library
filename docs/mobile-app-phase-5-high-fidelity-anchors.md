# 移动 App 第五阶段：1:1 高保真视觉锚点

> 2026-08-27 书架确认稿：[行式书架目录 v2](mobile-shelves-row-layout.md) 替代旧书架锚点；参考图分别为书架根页与合集二级页，均采用左文字右三封面。

> 2026-08-27 Mobile 导航修订：[图书内容导航契约](mobile-book-content-navigation.md) 决定根节点与下级节点页面：目录推进目录页，可读资源推进独立资源详情；不按资源数量分流、不在原页切换，不修改后端或 Web。

> 横切实现规范：[`mobile-app-development-global-guidelines.md`](mobile-app-development-global-guidelines.md)

## 1. 目的与约束优先级

本文件固化方向 A“暖白书页”按画布尺寸 1:1 输出的高保真页面锚点，供后续锚点、状态变体和原生实现校准；1:1 只描述画布与构图，不要求系统组件逐像素复制。当前已覆盖 Compact 的 Home、Library、Book Detail、Shelves、Me、Downloads，以及沉浸层 Reader Paper 与 Audio Now Playing。服务器登录与管理已由 Phase 6 v3 的任务闭环接管，不再以本阶段旧版 Server Center 单页或 Phase 6 v2 网格稿为准。

约束优先级固定为：

1. Phase 1 以及明确取代它的 Accepted ADR 决定功能、API、数据与权限事实；Mobile 当前身份以 ADR 0020 为准；
2. Phase 2 决定页面归属、导航、返回和覆盖层；
3. Phase 3 决定任务流、内容顺序和动作优先级；
4. Phase 4 决定令牌、排版、Cover、Progress、图标与动效；
5. 全局开发规范决定系统组件所有权、允许定制范围、平台差异和分层视觉验收；
6. 本文件的图像只冻结页面级构图和视觉密度。

图像不得覆盖前四阶段和全局开发规范的文字约束。实现时仍须使用语义令牌与平台原生组件，不能从 PNG 采样颜色、重绘系统图标或把图像中的演示封面视为产品数据。App 自有内容区域应严格还原；系统组件区域只冻结语义、位置和内容，不冻结系统圆角、阴影、字形度量与动效。

## 2. 共同画布

- 画布：除 Book Detail 概念组外使用 `390 × 844`，不含设备外框和演示板；Book Detail 当前概念组保留带设备框的评审稿，真实平台验收截图仍按设备原生画布归档；
- 外观：Shell 页面使用 `App Light`，Reader 使用 `Paper`，Audio 使用方向 A 的暖铜沉浸外观；
- 内容：八页复用同一用户、服务器和作品身份；出现媒体内容时继续复用同一封面、作者、阅读位置和进度；
- 视觉：暖白 Canvas、黑色正文、克制珊瑚红、2:3 Cover、系统无衬线与原生图标；
- 纸感只来自背景、排版、封面和内容节奏，不增加仿纸卡片、UI 噪点或装饰纹理；
- System status bar 未纳入锚点，未来实现由原生安全区和系统状态栏接管。
- 当前 PNG 不能充当 iOS 与 Android 共用的系统组件像素基准；实现阶段必须分别生成真实平台基准。

## 3. Home

![Home App Light v1](assets/mobile-app-hifi-v1/home-app-light-v1.png)

文件：[Home App Light v1](assets/mobile-app-hifi-v1/home-app-light-v1.png)

冻结项：

- 大标题“首页”，不放搜索；
- “继续阅读”是首屏唯一独立任务容器和唯一强 CTA；
- 最近阅读与最近入库通过 Cover、标题和留白形成连续节奏，不堆叠卡片；
- 两组横向内容在 390pt 宽度下保留三个可扫描目标；
- 四项 Tab 顺序固定，首页使用 filled 选中图标与 Accent。

## 4. Library

![Library App Light v1](assets/mobile-app-hifi-v1/library-app-light-v1.png)

文件：[Library App Light v1](assets/mobile-app-hifi-v1/library-app-light-v1.png)

冻结项：

- 搜索、`全部 / 系列 / 作者`、结果上下文和作品网格按任务顺序连续排列；
- 活动筛选使用内联摘要，不使用整条彩色胶囊或筛选卡片；
- 标准 `390pt` Compact 默认三列 2:3 Cover 网格，一屏每行展示三本；
- 标题与作者各保留一个可读行，Dynamic Type 或窄屏空间不足时自适应为两列或 List，不继续压缩字体；
- 只有存在阅读进度的作品显示 Progress；
- 四项 Tab 顺序固定，书库使用 filled 选中图标与 Accent。

## 5. Book Detail

2026-08-27 真机反馈补充：下级目录进入后直接显示浏览控制、面包屑和下级封面，导航栏“更多”保留当前子树下载。仅点击图书进入的目录型根页恢复原有图书身份、当前卷册阅读区、下载状态／阅读状态／加入／更多和简介，导航栏不重复快捷菜单。操作栏由图书与卷册详情统一复用，动作归属当前页面对象；续读单独定位书中资源和位置。阅读区为卷册名称、该卷册进度条和继续按钮，无进度时只展示开始按钮；不恢复混合进度。详见 [图书内容导航契约](mobile-book-content-navigation.md)。

Book Detail 的产品和内容结构不再由 App 专属基准图定义。唯一行为来源是当前 Web Work Detail 的 `book-detail-page.tsx`、`book-content-browser.tsx` 和 `resource-detail-view.tsx`；身份只使用 ADR 0020 的 Book/ReadableResource/ResourceAsset，本节仅约束原生视觉适配。

冻结项：

- 使用系统返回与折叠标题语义，不自绘 Web 式 Header，也不在顶部显示 overflow；Book Detail 正常显示 AuthenticatedShell 四项导航，只有 Reader 隐藏；
- 只显示一张当前作品 Cover，不显示封面轮播、圆点或虚构的备用封面；Cover 与作品名组成第一视觉层，作者、系列和阅读状态依次降级；
- Cover 全局使用透明展示框，不为真实封面或 Fallback 补充背景色；详情身份区按“标题、作者 / 系列 / 当前媒介、填充背景标签、阅读状态”组织，作者与系列不再拆成独立行；
- 主 CTA 下方快捷动作固定为“下载 / 阅读状态 / 加入 / 更多”；`加入` 使用书架语义图标并打开 `shelf-picker`，`更多` 展开图书控制菜单。详情页右上角不显示三点或管理入口；
- 页面按后端节点身份决定：目录推进目录内容页，可读资源推进独立资源详情；与资源数量无关，不自动启动 Reader。返回恢复父页面原有排序、视图、分页和滚动。
- 资源详情按 `readerType` 显示章节与已读状态、漫画/PDF 页面预览或音轨信息；加载、空、导入中、导入失败和分页错误均保留稳定布局与原位反馈；
- 封面氛围背景使用约 `1.25` 缩放、`12dp/pt` 模糊与 `0.36` 顶部有效不透明度，从背景高度约 `45%` 连续淡出到底部语义页面背景；不得出现固定裁剪边缘或硬分界；
- “未开始 / 未读”是默认状态，不在身份区重复显示；只有正在阅读或已完成时显示阅读状态；
- 下载状态与阅读进度严格分离：云朵直接开始下载，环形控件可暂停/取消，勾选圆圈表示完成；详情行不显示“下载中 68%”一类文字；
- 所有受支持格式的主动作均为在线“开始/继续阅读”或“开始/继续收听”；已验证本地副本可优先使用，但不改变主按钮。云朵及下载进度只表示独立离线下载；
- 编辑、识别、封面和其他管理能力由详情页控制菜单进入聚焦 Sheet；下载、阅读状态、加入书架和更多保持详情页快捷入口。能力与权限不足时隐藏对应操作或给出真实原因，不使用伪成功状态；
- 图书、来源目录与资源的控制菜单直接采用 Web 当前动作集合和权限过滤，并使用平台原生 Menu/Sheet/Dialog 承载；

## 6. Reader Paper

![Reader Paper v1](assets/mobile-app-hifi-v1/reader-paper-v1.png)

文件：[Reader Paper v1](assets/mobile-app-hifi-v1/reader-paper-v1.png)

冻结项：

- Reader 是 Shell 之上的沉浸层，隐藏 Tab 与 mini player；
- Paper 的纸感只来自暖色、宋体、行高、段距和正文留白，不使用纸纹、噪点或装饰材质；
- controls visible 状态包含系统返回、作品上下文、书签、更多、系统 Slider 与四个底部动作；
- 正文是唯一第一视觉层，控制 Surface 使用 Divider 分隔，不形成悬浮玻璃面板；
- 目录入口只承载目录与书签，不出现笔记；Reader 返回仍须先完成本地 progress 事务且不等待网络。

## 7. Audio Now Playing

![Audio Now Playing v1](assets/mobile-app-hifi-v1/audio-now-playing-v1.png)

文件：[Audio Now Playing v1](assets/mobile-app-hifi-v1/audio-now-playing-v1.png)

冻结项：

- Now Playing 使用方向 A 的单一暖铜沉浸底色，Cover 是唯一大型图像焦点；
- 顶部折叠动作表示回到 mini player，不停止播放；全屏层不显示 Tab 或 mini player；
- 时间轴使用系统 Slider；播放控制固定为上一章、后退、播放/暂停、前进和下一章；
- 次级动作固定为当前倍速、章节、睡眠定时和查看作品，不使用卡片或胶囊；
- 不使用波形、封面旋转、装饰渐变或持续动画表达播放状态。

## 8. Shelves

![Shelves App Light v1](assets/mobile-app-hifi-v1/shelves-app-light-v1.png)

文件：[Shelves App Light v1](assets/mobile-app-hifi-v1/shelves-app-light-v1.png)

冻结项：

- 大标题“书架”，添加动作使用系统 Menu 入口，不增加搜索；
- 合集使用三本 Cover 叠放组图，书架使用三本 Cover 并列预览，依靠组图方式、层级和 Divider 区分语义；
- 合集行只显示成员书架摘要，不直接展示或操作作品；
- 智能书架只使用克制的规则 glyph 与摘要表达只读计算结果，不提供手工添加入口；
- 普通行不使用圆角卡片、彩色底板或阴影；四项 Tab 顺序固定，书架为选中项。

## 9. Me

![Me App Light v1](assets/mobile-app-hifi-v1/me-app-light-v1.png)

文件：[Me App Light v1](assets/mobile-app-hifi-v1/me-app-light-v1.png)

冻结项：

- 大标题“我的”，用户头像只出现一次；身份信息不使用独立卡片或品牌装饰；
- 账户、离线与存储、服务器、偏好和产品使用连续系统设置行、Divider 与原生 chevron；
- 下载数量、当前服务器、语言和 Web 管理域名作为次级信息，不能抢占行标题层级；
- P1 的手工导入、Kindle 设置与任务在交付前整组隐藏；
- “在 Web 管理”只表示通过系统浏览器打开当前服务器域名，不建立 App 内管理 route；四项 Tab 中“我的”为选中项。

## 10. Downloads

![Downloads App Light v1](assets/mobile-app-hifi-v1/downloads-app-light-v1.png)

文件：[Downloads App Light v1](assets/mobile-app-hifi-v1/downloads-app-light-v1.png)

冻结项：

- 使用从“我的”压入的系统导航语义，标题“下载”，右侧为选择/管理动作；
- 导航区同时提供本地已下载搜索；搜索范围只包含当前私有命名空间中的 completed 工件，并按 `Book → ReadableResource → ResourceAsset` 聚合展示，三层使用 `bookId / resourceId / assetId`，不能退化为服务器书库搜索；格式与媒体类型来自服务端 Resource/Asset 合同；
- 正常锚点同时展示存储占用、一个进行中、两个已完成和一个失败任务，不使用临时 Sheet 代替持久页面；
- determinate 下载进度为 4pt，并同时显示百分比或传输量；只有独立下载动作创建任务且完成后不自动跳转；同一 namespace 下身份归属完整且已验证完成的 ResourceAsset 可从下载中心以其 `resourceId` 直达 Reader/Now Playing，fingerprint 仅作诊断；
- Book 层封面先使用缓存或统一 fallback，占位尺寸始终稳定，再异步过渡到 authenticated cover；封面失败不折叠 Book/ReadableResource/ResourceAsset 层级，不出现跳高，也不影响本地搜索和打开；
- 下载失败使用稳定摘要和行内“重试”，不弹逐项 Dialog；移除离线副本等破坏性动作仍按 Phase 2 进入确认 Dialog；
- 页面属于 MeStack，保留四项 Tab 且“我的”为选中项；当前正常锚点不显示 offline/401 宽限 Banner 或 mini player。

## 11. Server Login / Center 替代关系

![Server Login Saved iOS App Light v3](assets/mobile-app-hifi-v1/server-login-saved-ios-app-light-v3.png)

文件：[Server Login Saved iOS App Light v3](assets/mobile-app-hifi-v1/server-login-saved-ios-app-light-v3.png) · [Server Login Saved Android App Light v3](assets/mobile-app-hifi-v1/server-login-saved-android-app-light-v3.png)

旧版 Server Center 与 Phase 6 v2 服务器网格资产均已被 Phase 6 v3 替代，不再作为实现或验收依据。服务器 Gate 与“我的 > 服务器”复用同一个登录表单和切换 Sheet 模型：

- 无有效会话时首屏直接显示服务器地址、账号、密码；首次使用为空，鉴权过期时回填最近成功 profile；
- “登录”是唯一强主动作；下方左侧“切换服务器”打开平台原生 Sheet，右侧“删除当前服务器”使用低强调 destructive 语义；
- 输入新地址并登录成功后自动保存 profile，名称取标准化 URL hostname，不提供名称输入或独立添加/编辑模式；
- Sheet 选择只回填表单，不自动登录；删除确认成功后清空三个字段，不自动选择下一台服务器；
- 填写和切换不探测网络，不展示连接状态、兼容性、TLS 或证书验证配置；
- 只有点击登录时执行探测；不可用、不兼容和不安全 SSL 分别使用平台原生提示，其中不安全 SSL 只提供“取消”与“接受风险并连接”；
- 从“我的”进入时保留 MeStack 的系统返回和 Tab；未登录 Gate 不显示 Shell 导航。iOS 与 Android 共用语义，不共用系统组件几何。

完整状态、文案、平台差异和十张视觉证据以 [`mobile-app-phase-6-server-auth-high-fidelity.md`](mobile-app-phase-6-server-auth-high-fidelity.md) 为准。

## 12. 本轮验收结论

- 本阶段主锚点使用同一用户、服务器、内容身份与视觉语言；Book Detail 使用 v6 并列 Light/Dark 评审板，其他主锚点为 `390 × 844` PNG；服务器入口资产由 Phase 6 单独管理，包含 iOS `390 × 844` 与 Android `412 × 915` 画布；
- Home 没有第二套搜索，Library 是唯一发现入口；
- Library 活动筛选已去除大面积胶囊背景；
- Home 与 Library 在标准 `390pt` Compact 宽度下均保持一行三本的信息密度；
- Book Detail 的主次动作、ReadableResource 选择和返回来源可辨认，且不出现 Version/Volume 层级；
- Reader 的正文/控制层、Paper/系统字体和沉浸导航边界可辨认；
- Audio 的折叠、播放、时间轴与次级动作没有被自定义视觉吞没；
- Shelves 的合集、静态书架与智能书架可通过层级和三封面组图区分；
- Me 的用户身份、设置分组和系统行语义清楚，头像没有重复成为装饰；
- Downloads 的存储、进行中、已完成和失败状态同时可扫描，失败恢复保持行内；
- 服务器入口已改为默认登录表单、原生切换 Sheet、当前 profile 删除，以及仅在点击登录时出现的连接、兼容性和 SSL 风险提示；
- 页面没有新增 Web-only、P1 占位或 Phase 1 排除能力；
- Home、Library、Book Detail、Shelves、Me 与 Downloads 的 App 自有内容区按严格视觉回归验收；Reader 与 Audio 的业务内容区同样严格验收；服务器入口按 Phase 6 v3 独立验收；Navigation、Tab、Slider、播放控件和 overflow 按平台独立验收，不要求跨平台同形；
- 当前锚点不代表 App Dark、Expanded、Dynamic Type 或异常状态已经验收，这些仍按 Phase 3–4 的矩阵单独制作。

服务器登录、切换与删除、按需连接与 TLS 风险、Setup 和 Reauthenticate 的高保真闭环见 [`mobile-app-phase-6-server-auth-high-fidelity.md`](mobile-app-phase-6-server-auth-high-fidelity.md)。

书库 Search、系列/作者分组、共享 Facet 与返回上下文的高保真闭环见 [`mobile-app-phase-7-library-discovery-high-fidelity.md`](mobile-app-phase-7-library-discovery-high-fidelity.md)。
