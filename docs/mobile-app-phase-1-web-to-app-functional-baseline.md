# 移动 App 第一阶段：当前功能基线

> 文件名沿用历史阶段编号以保持现有链接和 AGENTS 规则稳定；正文只记录当前实现。功能和数据以代码、Accepted ADR 及机器合同为准。

## 权威来源

- 会话与服务器门控：`apps/mobile/shared/.../modules/auth`、`modules/servers`，以及 Android `bootstrap/ErmaoLibraryRoot.kt`、iOS `Application/AppRootView.swift`。
- 导航与根页面：`apps/mobile/shared/.../navigation/public.kt`、Android `features/shell/MainShell.kt`、iOS `Features/Shell/MainTabView.swift`。
- 内容模型和请求边界：`apps/mobile/shared/.../modules/library/ContentModels.kt` 与 `modules/library/infrastructure`。
- Reader v5 的启动、位置、安全和平台适配：[`mobile-reader-architecture.md`](mobile-reader-architecture.md)。
- Reader 过滤与资源预算：[`packages/reader-contracts/reader-safety-policy.json`](../packages/reader-contracts/reader-safety-policy.json)；视觉数值：[`packages/design-contracts/visual-tokens.json`](../packages/design-contracts/visual-tokens.json)。

## 产品边界

Mobile 是面向家庭 NAS 阅读的已认证客户端，提供发现、组织、阅读、播放和受控本地下载。Web 继续承载完整管理工作台；移动端只暴露当前用户和设备能力允许的设置与管理入口。Mobile 没有独立的无网络产品模式，已验证的本地下载工件可以在合适的阅读路径中使用。

根页面固定为 Home、Library、Shelves、Me 四个 Tab。辅助页面从对应 Tab 推进，音频播放可跨 Tab 保留迷你播放器，下载中心和设置从 Me 或内容动作进入。

## 当前能力

| 能力 | 当前实现与边界 |
|---|---|
| 服务器与账户 | `DefaultMobileRuntime` 负责探测、兼容性、首次设置、登录、恢复会话、重新认证、切换与删除 profile。`AppSession` 将网络失败、TLS 风险、未设置、登录失败、账户停用和已认证状态分开表达。 |
| 首页 | Android `features/home` 与 iOS `Features/Home` 读取继续阅读、最近阅读和最近加入的内容；点击进入共享内容详情。 |
| 书库发现 | `LibraryScope` 为 Books、Series、Authors；Books 支持服务端分页、搜索、排序、Grid/List 和阅读状态筛选，分组和 facet 使用相同的共享查询模型。 |
| 书架 | `modules/shelf` 与两端 `features/shelves` 支持全部、书架、合集范围，静态/合集创建和成员列表；智能书架可浏览但不在移动端创建。搜索、分页、空态、失败重试及打开内容均已接入。 |
| 内容详情 | `BookDetailSummary`、`BookContentEntry` 和 `BookContentTarget` 支持 Book 根、目录节点、资源详情三种落点。目录、资源和管理动作由服务端数据与权限决定。 |
| Reader | Reader v5 支持当前共享启动与位置同步契约；两端提供可重排内容、PDF、漫画/图片目录和文本等已接入格式的原生适配。Reader 安全细节以架构文档和生成策略为准。 |
| 音频 | 共享 audio runtime 加上 Android 服务/控制器和 iOS 播放实现，提供播放、暂停、进度、上一首/下一首、迷你播放器和 Now Playing。 |
| 下载 | 共享 `DownloadsRuntime` 与两端目录/文件适配器管理队列、暂停、恢复、重试、移除和打开。只有完整校验并原子发布的本地文件才算可读离线工件。 |
| Me 与管理 | 两端提供个人资料、语言、安全、关于、下载入口；授权用户可进入能力过滤的 library、组织、用户/队列、metadata/OPDS、备份、系统与日志设置。 |

## 身份与内容关系

当前版本的 Android/iOS 内容管理菜单统一复用 KMP `managementActions`。Book、目录和资源编辑表单只保存元数据（Book 包含标签），不选择、上传或移除封面；独立资源上传封面和重新生成封面的菜单仍按现有权限提供。详情及复用该菜单的入口隐藏“识别”，共享会话同时阻止识别加载、搜索和应用请求。本次限制不改变 Web/PWA、后端接口或管理设置中的识别配置。

客户端使用 `Book → Resource → Asset` 的真实服务器身份。`ContentModels.kt` 中的 `BookContentTarget` 由服务端节点声明决定，不能根据资源数量、文件名或客户端猜测路由。阅读状态和进度按 `bookId + resourceId` 归属；Asset 是资源的可下载或媒体载荷，不创建额外内容身份。

## 会话、授权与私有数据

`PrivateDataNamespace` 由 `serverIdentity`、`userId` 和 `authzVersion` 构成。已验证会话可以恢复正常 Shell；短暂网络故障不会把用户强制登出。明确的认证失败、账户停用、服务器身份改变或授权范围改变会退出旧 Shell，并在新命名空间下重新拉取内容。切换服务器会激活目标 profile 并重置导航栈；命名空间隔离旧的私有数据，切换本身不应被理解为删除下载。登出时平台协调器停止音频、等待下载取消并清理当前命名空间，shared runtime 负责移除会话和 cookie；删除 profile 负责移除 profile、会话和 cookie，不能据此宣称删除所有平台文件。密码和会话凭据使用平台安全存储。

## 阅读、下载与安全边界

- 可重排入口遵循当前下载前置契约：需要本地原文件时复用 Download Center，完整校验后才交给本地 Reader；不把部分文件当作可读内容。
- PDF 和漫画按 Reader v5 的在线/Range 或已验证本地工件路径读取，保持有界内存和预取；音频由 audio runtime 选择远端或已验证本地媒体。
- 进度与书签先写入本地拥有的状态，再按 Reader v5 合同尽力同步。同步失败不应阻断内容打开或退出。
- 所有格式、MIME、容器和活动内容防护调用生成的安全策略；平台解析器只能报告事实并执行生成决策，不得维护私有黑名单或阈值。

## 实现与验证入口

共享层通过 typed Ktor repository/gateway 连接 API，UI 只发出用户意图并消费明确状态。Android 的 `visual/VisualFixtureActivity.kt` 提供无网络视觉夹具；iOS 的视觉与功能验收需要真机。当前 Reader v5 仍需跨平台真机一致性收口，具体缺口记录在架构文档和 `apps/mobile/design-qa` 的运行记录中。
