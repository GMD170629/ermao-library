# 移动 App 第三阶段：当前用户流程

> 文件名沿用历史阶段编号；旧线框和重复验收表已收敛为当前行为说明。具体视觉组合见 Phase 4–7，平台路由见 Phase 2。

## 流程共同约束

用户可见流程必须使用 `zh-CN` 和 `en-US` 文案、稳定错误码和明确的 loading/empty/error/retry 状态。用户输入的标题、作者、系列、标签、路径和文件名保持原样。系统 Sheet、Menu、Dialog、Picker、权限和返回行为交给平台；内容身份使用 `Book → Resource → Asset`。

## 当前流程索引

| 流程 | 触发与结果 | 主要实现 |
|---|---|---|
| F01 连接与登录 | 添加/选择服务器，完成探测、首次设置或登录；恢复已验证会话；失败可重试或重新认证 | `DefaultMobileRuntime`、`AppSession`、`ErmaoLibraryRoot.kt`、iOS `AppRootView.swift` |
| F02 继续阅读 | Home 的继续项打开 Book/Resource；保存本地位置并尽力同步；同步异常不阻断阅读 | `features/home`、`modules/reader/application`、两端 Reader feature |
| F03 书库发现 | 在 Books、Series、Authors 中搜索、排序、切换视图、筛选和分页，进入 Book 或 facet | `modules/library/ContentModels.kt`、两端 `features/library` |
| F04 书架组织 | 浏览全部/书架/合集，搜索、创建、查看成员、打开 Book；处理空态、失败和分页 | `modules/shelf`、两端 `features/shelves` |
| F05 音频播放 | 从 Book/Resource 或下载内容开始播放；mini player 跨 Tab 保留，Now Playing 提供完整控制 | `modules/audio`、Android `features/audio`、iOS `Features/Audio` |
| F06 下载与本地打开 | 选择 Resource/Asset，排队、校验并发布完整工件；Download Center 管理后打开合适的阅读/播放入口 | `modules/downloads`、两端 `features/downloads` |
| F07 切换服务器 | Server Center 更新当前 profile；激活目标、重置导航栈并以新命名空间重建私有视图 | `DefaultMobileRuntime`、`SessionStore.swift`、Android `MainViewModel` |
| F08 内容与授权变化 | 授权失效、撤权、内容指纹变化或服务器不兼容时遮蔽旧私有内容并给出可恢复状态 | auth/session runtime、下载命名空间、Reader v5 gateway |
| F09 个人与管理设置 | 从 Me 进入个人资料、语言、安全、关于或授权管理模块；按 capability 显示可用入口 | Android `features/me`/`features/administrativesettings`、iOS 对应目录 |

## F01：首次连接、设置与登录

`DefaultMobileRuntime.start` 先读取 profile 和安全存储，再调用 server probe。没有 profile 显示空 Server entry；探测成功后按 setup status 进入首次管理员设置或登录。成功登录并读取 `/me` 后保存 profile、已验证会话和 `serverIdentity + userId + authzVersion` 命名空间，根 Shell 才进入四个 Tab。

网络不可用、超时、TLS 信任风险、服务器不兼容、无效凭据和账户停用是不同状态。普通网络失败保留表单并提供重试；明确的认证失败进入重新认证或登录错误；账户停用离开主 Shell。切换 profile 不自动登录目标服务器。

## F02：继续阅读

Home 从共享内容仓库读取继续阅读和最近内容。入口先校验会话和内容身份，再进入 Book detail 或 Resource detail；Reader v5 启动协调器加载 bootstrap。位置由 Reader 运行时先写本地拥有的状态，随后以单飞、可取消的方式同步；书签和进度服务失败时仍允许关闭或继续阅读。

## F03：发现并开始阅读

Library 使用 `LibraryScope`、`LibrarySort`、`LibraryViewMode`、`ReadingStatus` 和分页查询。Books 显示搜索、排序、Grid/List 和阅读状态菜单；Series/Authors 先进入分组结果，再进入 facet。结果项打开共享 Book detail，不在结果页另造阅读逻辑。内容详情根据服务端 `BookContentTarget` 打开目录节点或资源详情，用户明确选择后才进入 Reader/播放。

## F04：组织到书架

Shelves 的范围是 All、Shelves、Collections。用户可以搜索、打开现有书架或合集，并从创建 Sheet 选择静态或智能类型；合集成员和条件由共享 shelf 模块负责。删除、添加成员或刷新失败以明确状态返回，不能通过空列表伪装成功。打开成员复用 Book detail 和当前来源上下文。

## F05：持续播放

Audio runtime 负责远端/本地媒体、播放阶段、进度和队列。Android 由服务与控制器承载，iOS 由平台播放适配器承载；两端都在根 Shell 维护 mini player，并从 Now Playing 处理播放、暂停、拖动、上一项/下一项和错误。网络失败时只在存在同一命名空间、完整校验的本地工件时切换本地媒体，否则显示可恢复错误。

## F06：下载后阅读或播放

下载记录按当前命名空间和 Book/Resource/Asset 归属存储。队列经历 queued、downloading、paused、retryable/terminal failure、completed 等状态；写入临时文件，验证期望字节数、MIME、哈希/完整性后原子发布。部分文件、未知归属文件或跨用户文件不会进入阅读入口。Download Center 支持暂停、继续、重试、移除和打开已验证内容。

可重排内容按现行下载前置契约在完整原文件可用后打开；PDF/漫画可以使用 Reader v5 的在线 Range/分页路径，已有完整工件时才支持本地打开；音频使用 audio runtime。客户端不创建派生包或持久化解包目录。

## F07：切换、登出与清理

Server Center 的 profile 选择只更新待用服务器和表单。登出主 Shell 时平台协调器停止音频、取消并等待下载任务，再清理当前命名空间的缓存/目录和会话记录；删除 profile 由 runtime 移除 profile、会话和 cookie，不能概括成删除所有平台文件。切换后的 Shell 以新的服务器身份、用户和 `authzVersion` 建立，旧内容不通过遮罩或透明占位继续暴露。

## F08：授权与安全恢复

请求返回未授权时进入重新认证；授权范围变化时先隔离旧私有状态并重新读取服务端内容。Reader v5 bootstrap 在打开前校验用户、Book/Resource/Asset 归属、格式和安全策略；安全策略只来自生成的机器合同。网络、解析器、资源上限和策略拒绝分别映射到明确状态，不能用另一个解析器或旧缓存静默绕过。

## F09：个人与管理设置

Me 提供 profile、语言、安全、关于和下载中心。管理员入口按服务端 capability 显示 library/import/organization/metadata/OPDS/people/queue/backups/system/logs 等已接入模块；各模块使用 shared administrative settings 合同，并复用根会话、locale 和错误状态。没有权限的模块不应出现在可操作列表中。

## 验证入口

行为验证沿 F01–F09 覆盖正常、空、失败、重试、未授权和重新进入路径。Android 无网络夹具位于 `features/visual/VisualFixtureActivity.kt`，Reader 和完整导航需要真机；iOS 的 Reader、系统覆盖层和视觉一致性需要真机。Reader v5 的详细边界以 [`mobile-reader-architecture.md`](mobile-reader-architecture.md) 为准。
