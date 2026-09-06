# 移动 App 第二阶段：当前信息架构与导航

> 文件名沿用历史阶段编号；正文是当前实现摘要。页面名称使用 Book、Resource、Asset 等现行身份，具体行为以共享模型和两端 Shell 为准。

## 根模型

共享 [`navigation/public.kt`](../apps/mobile/shared/src/commonMain/kotlin/com/ermao/library/shared/navigation/public.kt) 固定四个根 Tab，顺序为 Home、Library、Shelves、Me。认证门位于根 Shell 之前；认证成功后 Android 和 iOS 各自维护每个 Tab 的导航路径，辅助页不会把根 Tab 重新定义成独立产品。

| 层级 | 页面/入口 | 当前代码依据 |
|---|---|---|
| L0 | Server entry、Setup、Login、重新认证、账户停用和不可用/不兼容状态 | `shared/modules/auth`、`modules/servers`；Android `bootstrap/ErmaoLibraryRoot.kt`；iOS `Application/AppRootView.swift` |
| L1 | Home、Library、Shelves、Me | Android `features/shell/MainShell.kt`；iOS `Features/Shell/MainTabView.swift` |
| L2 | Shelf detail、facet、Book detail、Download Center、Settings/管理 | Android Shell 的 `ShelfDetailRoute`、`FacetRoute`、`BookDetailRoute`、`DownloadsCenterRoute` 与 Me routes；iOS `AppRoute`/`AppPathStore` |
| L3 | Book 目录节点、Resource detail、Reader、Now Playing | `BookContentTarget`、Reader 启动协调器、两端 Reader/Audio feature |

## Android 当前路由

`MainShell.kt` 创建 `HomeRoot`、`LibraryRoot`、`ShelvesRoot`、`MeRoot` 四个独立 back stack，并保存选中的 Tab。辅助路由包括：

- `ShelfDetailRoute(shelfId)`：从 Shelves 进入一个书架或合集；
- `BookDetailRoute(bookId)`：从 Home、Library、Shelves 或下载结果进入 Book 根页；
- `FacetRoute(kind, facetId)`：从 Library 分组进入系列或作者 facet；
- `DownloadsCenterRoute`、`DownloadedBookRoute(bookId)`：查看任务及其已下载内容；
- `ReaderUnavailableRoute(resourceId, accessKind)`：Reader 不可用时显示可恢复的明确状态；
- Me 下的个人设置、语言、安全、关于和能力过滤的管理路由。

重新选择当前根 Tab 会回到该 Tab 根路径；跨 Tab 进入内容时保留全局音频 mini player。`WarmPageNavigationSuite` 当前承载紧凑布局的底部导航和 mini player，平台导航行为仍由全局规范约束。

## iOS 当前路由

`MainTabView.swift` 使用 `TabView`、每个 Tab 的 `NavigationStack` 和 `AppPathStore` 保存路径。当前路径覆盖 Home、Library、Shelves/书架详情、Me、Book detail、facet、Download Center、已下载内容、Reader 入口、音频 Now Playing、个人与管理设置。紧凑尺寸使用应用自己的 `RootTabControls` 组合底部入口；常规尺寸使用系统 TabView。系统返回和导航目的地由 `NavigationStack` 管理。

## 内容详情层级

共享 `ContentModels.kt` 将 Book 内容落点建模为：

1. `BookContentTarget.Root`：Book 身份、封面、元数据、状态、继续动作和内容浏览器；
2. `BookContentTarget.Directory(sourceNodeId)`：目录节点、面包屑、排序、分页和子节点；
3. `BookContentTarget.ResourceDetail(resourceId)`：资源身份、章节/reading units、页面或音频轨道、进度及 Reader/播放动作。

`bookContentTarget` 只接受服务端声明的资源或源目录，不能从资源数量、文件名或客户端状态推断落点。目录层不重复 Book hero 或管理动作；从目录/资源返回时恢复来源和面包屑上下文。

## 启动、恢复与切换

根状态顺序是读取 profile/安全凭据、探测服务器、判断兼容性与初始设置、登录或恢复已验证会话，最后建立带命名空间的主 Shell。短暂网络失败保留可重试的门控状态；服务端明确返回未授权时进入重新认证；账户停用、服务器身份改变或授权范围改变会销毁旧 Shell 的私有视图。

切换服务器打开 Server Center 并重新填充表单，不自动替用户登录目标 profile；成功切换会激活目标 profile 并重置导航栈，命名空间隔离旧的私有数据。删除 profile 需要系统确认，并由 runtime 移除 profile、会话和 cookie；平台层对当前 Shell 的音频、下载和缓存清理是独立协调步骤，不能把删除 profile 概括成删除所有本地文件。当前没有离线根 Shell；已验证本地工件从 Download Center 或内容动作进入相应阅读路径。

## Overlay 与跨层入口

Sheet、Menu、Dialog、Picker、系统权限、键盘和返回手势由平台原生容器承载。业务内容只提供标题、选项、状态和回调。音频 mini player 是跨根 Tab 的共享 chrome，点击后打开 Now Playing；下载任务从 Book/Resource 动作进入统一 Download Center。管理设置按服务端 capability 显示，未授权入口不以空壳页面代替。

## 导航维护规则

- 外部深链和通知只携带稳定的 Book/Resource/Asset 标识及必要的来源上下文，先经过当前会话和权限校验。
- Tab、路径、选中项和筛选状态各自只有一个状态所有者；不要在页面内复制一份导航状态再用 effect 追赶。
- 任何新内容入口复用共享 `ContentRepository`、`BookContentTarget` 和现有详情页面；不新增平行详情树。
- 页面、路由和状态的可见文案完整支持 `zh-CN`、`en-US`，程序分支使用稳定枚举/错误码。

## 验证入口

Android 入口是 `MainShell.kt` 和 `ErmaoLibraryRoot.kt` 的路由测试、无网络 `VisualFixtureActivity`；iOS 入口是 `MainTabView.swift`、`AppRootView.swift` 及真机导航/返回检查。Reader v5 的内容启动和安全验证以 [`mobile-reader-architecture.md`](mobile-reader-architecture.md) 为准。
