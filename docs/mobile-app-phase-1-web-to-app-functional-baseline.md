# 移动 App 第一阶段：Web → App 功能基线审计

> 状态：已采纳的产品与技术基线
> 审计日期：2026-08-11
> 适用范围：从零重建的 `apps/mobile` 及其所依赖的 App 专用后端契约
> 事实来源：当前 Web 路由与交互、FastAPI 运行时路由与授权实现、Reader v4、媒体流、PWA/本地同步代码
> 横切实现规范：[`mobile-app-development-global-guidelines.md`](mobile-app-development-global-guidelines.md)

> v1.0.0 会话与内容回退修订（2026-08-15）：以 [`ADR 0015`](adr/0015-mobile-v1-verified-session-without-offline-mode.md) 为准。首发不提供独立离线模式、30 天授权宽限或服务器 GET 页面持久缓存回退。匹配的已验证会话可先恢复正常 App Shell，再后台验证；暂时网络失败保留 Shell，明确 401、账户停用或服务器身份变化才结束会话。完成下载、Reader、本地进度、书签和偏好继续保留，但不构成单独的离线产品模式。

> ADR 0020 身份与 Book Detail 统一修订（2026-08-26）：[`ADR 0020`](adr/0020-mobile-book-resource-asset-cutover.md) 取代本文全部 `Work / Version / Volume / File` 身份和兼容假设。Mobile 只使用 `Book(bookId) → ReadableResource(resourceId) → ResourceAsset(assetId)`。详情显示、目录/资源动作和管理入口以当前 Web 的 `book-detail-page.tsx`、`book-content-browser.tsx`、`resource-detail-view.tsx` 及其权限过滤为唯一产品事实；`bookDetailManagement` 不作为全局开关。单个可读资源直接显示资源详情但不自动进入 Reader；多个资源显示真实来源目录。阅读与收听均在线优先，不要求先下载；离线下载是独立的可选动作。本修订覆盖本文中所有旧的卷册轨道、隐藏目录和下载后阅读描述。

## 1. 基线目的

本文件不是 Web 菜单清单，也不是旧移动端方案的延续。它将当前仓库里的真实能力翻译成可以直接约束 App 产品设计、交互设计和技术实现的功能边界。

所有 App 页面或流程在进入设计前，必须同时回答：

1. 用户要完成什么任务；
2. Web 的真实入口在哪里；
3. 当前可用的 API 是什么；
4. 数据、会话、权限和失败状态是什么；
5. 此能力是否进入 App，以及进入哪个阶段；
6. 在 iOS/Android 上使用什么原生交互形态；
7. 哪些 Web 表象、旧接口或未完成能力禁止带入 App。

若设计无法映射到本文件中的真实 API 和状态，则它是待补契约的产品提案，不是可直接实施的 App 功能。

## 2. 第一阶段产品定义

第一阶段 App 定义为：

> 面向自托管服务器的原生阅读、音频与受管下载客户端。

它不是移动版 Web 管理后台。Web 继续承担服务器文件系统管理、批量治理、元数据维护、备份恢复、日志和高风险系统管理。

### 2.1 决策等级

| 等级 | 含义 | 设计要求 |
|---|---|---|
| P0 | 首个可发布版本的核心闭环 | 必须设计、实现并覆盖完整状态 |
| P1 | 契约真实且适合 App，但不阻塞首发 | 可预留入口层级，不得占据 P0 主导航 |
| P2 | 以后可能提供的辅助或只读能力 | 当前不出 App 详细设计，先补能力/安全前置 |
| Web-only | 保留在 Web 的管理能力 | App 最多提供“在 Web 管理”跳转 |
| 排除 | 已退役、占位或不应由官方 App 消费 | 禁止建模、调用或在设计稿中承诺 |

### 2.2 P0 用户闭环

P0 必须形成以下连续闭环：

```text
添加并验证服务器
→ 初始化或登录
→ 获取用户与授权上下文
→ 首页 / 书库 / 书架发现内容
→ Book Detail 选择 ReadableResource
→ 阅读或播放
→ 本地可靠记录进度
→ 联网同步并恢复继续阅读
```

## 3. P0 原生信息架构

底部一级导航固定为四项：

```text
首页 / 书库 / 书架 / 我的
```

全局结构约束：

- 搜索使用系统搜索栏或独立 Search Stack，不单列底部 Tab。
- 系列、作者是“书库”的二级发现维度，不单列底部 Tab。
- Book Detail 通过导航栈进入。
- 电子书、漫画、PDF 阅读器使用独立全屏阅读栈，不占底部 Tab。
- 音频使用跨 Tab 持续存在的 mini player，并进入全屏 Now Playing。
- 筛选、排序、新建/编辑书架、阅读设置与内容动作使用适合平台的 Sheet、Menu 或确认对话框。
- 系统管理不混入普通“我的”列表；第一阶段只提供明确的 Web 管理入口。
- iOS 保留边缘返回语义，Android 保留系统/预测性返回语义；核心动作不能只依赖手势。

## 4. Web → App 功能取舍矩阵

### 4.1 连接、账户与首页

| 能力 | Web 入口 / 真实 API | 数据与权限状态 | 决策 | App 原生形态与硬约束 |
|---|---|---|---|---|
| 服务器连接 | Web 默认同源；`GET /api/health`、`GET /api/mobile/compatibility` | App 使用 `noServer / checking / reachable / incompatible / unavailable`；兼容握手固定 protocol v3、Reader schema v4、Library schema v1 与 `bookResourceAsset=true` | P0 | 首次启动先添加服务器地址并检测；必须支持部署 base path；网络不可达不等于登出。进入 Shell 前必须验证 ADR 0020 的 protocol、schema 与 capability，不得以 `app-config` 代替 |
| 初始化 | `/setup`；`GET /api/auth/setup/status`、`POST /api/auth/setup` | 仅服务未初始化时；已初始化返回冲突 | P0 | 与登录互斥的初始化流程；只创建首位管理员。服务器/NAS 目录配置不放进手机初始化 |
| 登录与会话 | `/login`；`POST /api/auth/login`、`GET /api/auth/me`、`POST /api/auth/logout` | Cookie 会话；登录失败、账户停用、setup required、会话失效、服务不可用 | P0 | 原生表单与持久 Cookie Jar；启动和前台恢复统一请求 `me`；`401` 进入重新认证，离线/超时保留现有本地会话状态 |
| 首页 | `/`；`GET /api/dashboard/continue-reading`、`recent-reading`、`recent-books` | 各分区按当前资源范围过滤并可部分失败 | P0 | “继续阅读”主卡、最近阅读、最近入库；下拉刷新；每个分区独立 skeleton、空、错误和重试，不因单个请求失败阻塞整页 |
| 账户资料 | `/settings`；头像、姓名、邮箱、密码、preferences、logout API | 当前账户本人；改密码可撤销会话；头像上限由 API 校验 | P0 | “我的”中的账户 Stack；系统照片/文件选择器；敏感修改明确确认；退出必须清理该服务器/用户的私有数据 |
| 语言与关于 | `/settings`、`/settings/about`；`GET/PATCH /api/auth/preferences` 与本地版本 | 登录用户；服务端偏好白名单有限 | P0 | `zh-CN`、`en-US` 完整；系统本地化格式；关于页展示 App 与服务器版本，不将 Web PWA 更新状态当作 App 更新状态 |

### 4.2 发现、组织与详情

| 能力 | Web 入口 / 真实 API | 数据与权限状态 | 决策 | App 原生形态与硬约束 |
|---|---|---|---|---|
| 书库浏览 | `/library`；`GET /api/books` | 分页；按关键词、媒介、阅读状态、出版/追踪状态、标签等过滤；只返回当前用户可见图书 | P0 | 原生搜索、Grid/List、下拉刷新、无限分页、稳定恢复滚动位置；禁止复制桌面管理表和页码器 |
| 基础筛选与排序 | `/library`；`GET /api/library/filter-schema`、`filter-options`、`GET /api/books` | schema/options 可加载失败；选择项可能随权限变化失效 | P0 | Filter Sheet + Sort Menu；顶部仅展示少量活动条件；必须提供清除、应用、无结果和失效条件恢复 |
| 高级动态规则编辑 | Web 高级过滤器与智能书架规则 | 规则表达式和 options 真实存在，但手机编辑复杂 | P1 | 以后使用全屏条件编辑器；P0 可读取并显示规则摘要，不压缩桌面 builder |
| 系列 / 作者 | `/library/series`、`/library/authors`；`GET /api/library/groupings?kind=SERIES|AUTHOR` | 搜索、分页、空/错；仍受作品范围授权 | P0 | 书库二级入口；列表 → 带 facet 的作品列表 → 详情，保留返回上下文 |
| 静态书架 | `/shelves`；书架 CRUD API | 按 `ownerUserId` 隔离；用户手动管理作品 | P0 | “书架”Tab；详情 Stack；创建/编辑 Sheet；明确选择模式加入作品；禁止依赖右键和桌面拖放 |
| 智能书架 | `/shelves`；书架 CRUD 与过滤规则 | 规则计算；可能出现不支持规则 | P0 浏览，P1 编辑 | P0 展示规则摘要和计算结果，不能允许手工增删作品；不支持规则必须显式提示 |
| 书架集合 | `/shelves`；书架 CRUD | `COLLECTION` 只能包含书架，不能直接放作品；非空集合删除冲突 | P0 浏览，P1 复杂整理 | 集合 → 书架 → 作品的层级导航；删除使用系统确认并呈现 `409` 原因 |
| 图书详情 | `/books/[bookId]`；Book、Resource、Asset、reading units API | Resource 是可独立打开的阅读资源；Asset 是 Resource 使用的真实常规文件；部分目录节点、章节或资源可失败 | P0 | 折叠头部；单资源直接显示资源详情，多资源显示与 Web 相同的来源目录、面包屑、文件夹、分页、视图模式和六种排序；稳定的开始/继续主 CTA；管理动作按 Web 当前对象范围和权限过滤进入 Menu/Sheet，不混入主信息层级 |
| 阅读状态 | 作品详情；Reader v4 `PUT .../reading-status` | `UNREAD / READING / FINISHED`；用户级状态 | P0 | 详情动作 Sheet；开始阅读可推进到 READING；标记完成提供可撤销反馈 |
| 批量加入个人书架 | Web 书库选择模式 | 普通用户可操作自己的书架 | P1 | 原生明确“选择”模式和底部操作栏；不复刻 Ctrl/Cmd 多选、右键菜单 |

### 4.3 阅读、播放与本地下载

| 能力 | Web 入口 / 真实 API | 数据与权限状态 | 决策 | App 原生形态与硬约束 |
|---|---|---|---|---|
| Reader bootstrap | `/reader/[resourceId]`；`GET /api/reader/v4/resources/{resourceId}/bootstrap` | `bootstrapping / loading / ready / error / disposed`；含 reader type、fingerprint、progress snapshot、Book、Resource、Assets 与 publication | P0 | 只使用 `resourceId` 与 Reader v4；相对媒体 URL 必须基于已配置服务器 base URL 解析 |
| 可重排电子书 | Reader v4 + `GET/HEAD /api/assets/{assetId}` 或 resource asset | EPUB/MOBI/AZW/AZW3/PRC/FB2/TXT；完整工件、fingerprint、下载失败和内容版本变化 | P0 | 在线入口始终请求 Bootstrap；已有本地完整工件时由原生解析器决定能否打开，fingerprint、版本和声明长度差异仅作诊断。在线章节优先，离线使用缓存章节并由书内 TOC 补充。Reader 仍提供点按区、滑页/滚动、目录、书签、进度与外观 Sheet；Web DOM/Foliate renderer 不能直接当原生实现 |
| 漫画 | Reader v4 + pages list/page API | LTR/RTL、页列表、图片加载失败、内存与预取窗口 | P0 | 在线默认按页流式阅读，原生图片管线只做有限预取，禁止一次加载全部页；有完整本地工件时可离线打开，不要求在线阅读前下载整包 |
| PDF | Reader v4 + 支持 Range 的媒体端点 | Range、ETag、页码与密码/加载错误；当前 Web 实际以分页为主 | P0，首发只承诺分页 | 在线使用系统/原生 PDF renderer 通过 Range 流式读取，不要求先下载整份；完整本地工件可离线打开；捏合缩放、页码 scrubber，连续模式不在未验证前承诺 |
| 书签 | Reader v4 bookmarks GET/PUT | 本地优先；服务端为整组替换、无 revision，多设备存在最后写覆盖风险 | P0 | 书签列表、增删、跳转；必须标注当前同步弱一致性，禁止宣称无冲突多端合并 |
| 批注 / 笔记 | Web Reader 面板占位 | 无完整数据层和跨端同步契约 | 排除 | P0 设计稿不得出现可用的“笔记/批注”承诺 |
| 阅读进度同步 | Reader v4 progress PUT；客户端本地精确位置 | 进度以 `bookId + resourceId` 归属；`clientId / revision / location` 描述同步状态，Publication fingerprint 仅作诊断 | P0 | 本地事务先保存，再同步；Asset 或解析器指纹变化不得创建新进度槽、丢弃位置或阻止恢复；进度模块异常不得阻止内容打开或退出 |
| 音频书 | `/listen/[resourceId]` 仅为瞬时深链；bootstrap + Asset API | pending/loading/playing/paused/error；track/chapter/resume；Range 媒体 | P0 | 全局 mini player + Now Playing；系统音频会话、后台播放、锁屏/耳机/Bluetooth、跳转、倍速、章节、睡眠定时；`/listen` 不建成底部页面 |
| 本地下载内容 | App 私有下载目录 + Reader bootstrap + 媒体 Range API；Web SW 仅为参考 | 服务端没有设备下载 manifest；App 目录按 `serverIdentity + userId + authzVersion` 隔离，以 completed、Book/Resource/Asset 身份和本地文件存在为事实来源；fingerprint 仅作诊断 | P0 受限范围 | Download Center 按图书聚合任务与完整工件，并直接搜索本地已下载书名、作者和资源名；只承诺显式完成的 Resource，不把普通缓存或服务器任务冒充下载事实；不得宣称全量本地书库 |
| 原文件导出 | Web 下载；媒体 GET/HEAD | 与 App 私有下载工件是两种意图 | P1 | “导出原文件”单独走系统 Share Sheet；不能把一个下载按钮同时表示本地副本和文件导出 |

### 4.4 导入、发送与系统管理

| 能力 | Web 入口 / 真实 API | 数据与权限状态 | 决策 | App 原生形态与硬约束 |
|---|---|---|---|---|
| 手工文件导入 | 首页/书库上传；`POST /api/books/import` | 当前受 `canManageSystem` 保护；目标必须位于已启用书库根目录并符合其组织方式；multipart；无分块或断点续传 | P1 | 系统 Document Picker / Share Extension；选择合法的服务器书库路径，前台上传进度、取消、失败重试；上传完成后由扫描器绑定 SourceNode / Book / Resource / Asset，手机文件名或表单元数据不能另建结构 |
| 导入任务 | `/settings/library`；import task 与 scan job API | `PENDING / PARSING / COMPLETED / FAILED` 等；当前管理入口要求 `canManageSystem` | P2 只读候选 | 若以后进入 App，采用任务时间线和失败摘要；扫描、清队列、删源文件保留 Web |
| Kindle | `/settings/email` 与作品详情；kindle settings/task API | 个人任务按用户隔离；SMTP 是系统配置 | P1 | 作品动作 Sheet + 个人发送队列；SMTP 配置 Web-only |
| 用户管理 | `/settings/users`；`/api/admin/users*` | 只有 `isAdmin`；创建、停用、授权、重置密码、删除 | Web-only | 不进入首阶段 App；`canManageSystem` 不能代替 admin |
| 书库根目录 | `/settings/library`；library root 与设置 API | 服务器路径、NAS、`FLAT / VOLUMES` 组织方式、扫描策略；系统管理权限和资源范围 | Web-only | App 不复制服务器目录树；最多跳转 Web 管理后台 |
| 整理与元数据治理 | `/settings/organize`；organize、duplicates、facets、provider API | 批量、长任务、可破坏写操作、失败与回滚 | Web-only；以后可 P2 只读 | P0/P1 不提供 Book/Resource 的合并、拆分、移动、创建或删除，也不提供元数据源配置；详情页只允许不改变 SourceNode 身份的内容分类修正 |
| OPDS 配置 | `/settings/opds`；system settings | 系统管理；OPDS 是第三方客户端协议 | Web-only | 官方 App 内部数据层禁止改用 OPDS |
| 备份、健康、队列、日志 | settings 对应入口和 system/management API | 系统管理；含高风险与运维状态 | Web-only；以后可 P2 健康摘要 | 不复制桌面日志、备份恢复、队列操作台；高风险动作继续在 Web 完成 |

## 5. 会话与权限基线

### 5.1 App 根状态机

App 不能用零散布尔值协调启动。根状态至少应建模为互斥状态：

```text
no-server
checking-server
tls-risk
server-connection-failed
incompatible-server
setup-required
setting-up
setup-failed
signed-out
authenticating
login-failed
account-disabled
authenticated
session-expired
```

- 匹配的 `VerifiedSessionRecord` 直接恢复 `authenticated`；网络、超时、TLS、`5xx` 或协议解析失败保持该状态，不增加网络模式状态。
- `session-expired` 由明确 `401` 驱动，需要重新登录；账户停用和 server identity 变化分别进入对应阻断状态。
- `incompatible-server` 由 `GET /api/mobile/compatibility` 的 protocol v3、最低客户端版本、Reader/Library schema、`bookResourceAsset` 和稳定 `serverIdentity` 判定；v2 或缺少必要 capability 的服务端不得进入 Shell。

### 5.2 会话协议

当前后端唯一会话凭证是 `shuku_session` Cookie：

- `HttpOnly`；
- `SameSite=Lax`；
- `Secure` 由部署配置决定；
- 服务端 Cookie 默认有效期为 30 天并可在接近到期时续期；该传输层会话期限不是 Mobile 离线授权、宽限期或本地剩余天数；
- Cookie path 可能跟随部署 base path；
- 仓库没有 App 专用 Bearer access/refresh token API。

因此 App 网络层必须使用持久 Cookie Jar，正确保存 `Set-Cookie`，并让后台媒体传输和普通 API 使用同一授权语义。不能把 Cookie 值复制到业务状态或日志。

### 5.3 授权上下文

`GET /api/auth/me` 的 `authorization` 是 App 导航和动作显隐的唯一事实来源：

```text
isAdmin
canManageSystem
allLibraryScopes
libraryIds
canViewManualImports
authzVersion
```

必须区分：

| 身份 | 可做什么 | 不能推导什么 |
|---|---|---|
| 未登录 | 连接、初始化、登录 | 无任何私有书库访问 |
| 普通成员 | 当前授权范围的书库/阅读/个人书架/账户 | 不等于能导入或管理系统 |
| 系统管理成员 | 普通成员能力 + `canManageSystem` 保护的系统动作 | 不等于 admin；不等于自动拥有全书库 |
| 管理员 | 系统管理 + 用户管理 | 仍应遵守资源读取和防枚举契约 |

资源范围由 `allLibraryScopes`、`libraryIds` 与 `canViewManualImports` 共同决定。Book、Resource、封面、Asset 和 Reader bootstrap 都必须由服务端重新授权。无权访问通常与不存在一样返回 `404`；App 只能显示“内容不存在或当前不可访问”，不能泄露资源是否真实存在。

### 5.4 私有数据命名空间

所有私有缓存至少按下列键隔离：

```text
serverIdentity + userId + authzVersion
```

Reader 媒体与下载以 `bookId + resourceId + assetId` 归属，书签与阅读状态 owner 为 `resourceId`；本地精确阅读进度单独使用：

```text
serverIdentity + userId + clientId + bookId + resourceId
```

服务器切换、用户切换、登出、账户停用或 `authzVersion` 变化时，必须清理不再授权的封面、详情、媒体、搜索历史与播放状态。待同步进度先隔离，只有在确认不可恢复后才允许删除。

## 6. API 客户端硬约束

App 的共享传输层必须统一负责：

1. 保存并解析服务器 origin 与 base path；
2. 持久 Cookie Jar 与安全日志脱敏；
3. Reader bootstrap 中 `/api/...` 相对 URL 的正确解析；
4. 请求取消、超时和过期结果拒绝；
5. 标准成功 envelope `{ok:true,data}`；
6. 标准失败 envelope `{ok:false,error:{message,code?,details?}}`；
7. `401` 重新认证、`403` 能力失败、`404` 防枚举、`409` 冲突分类、`410` 永久停用、`413` 上传过大、`422` 字段错误、`503` 暂不可用；
8. `error.code` 缺失时按 HTTP 状态归一化，禁止按中文或英文 message 字符串分支；
9. 媒体请求的 Range、ETag、Last-Modified、206/304/416；
10. 网络、存储、URL 和持久化内容一律作为未知输入验证后再进入 App 模型。

OpenAPI 不是当前客户端唯一真相：仓库已有关键端点 request body 不完整的审计记录。P0 端点必须以运行时 schema、显式类型和契约测试共同约束。

## 7. Reader、本地状态与同步硬约束

### 7.1 进度 outbox

Reader 进度只实现 [`mobile-reader-architecture.md`](mobile-reader-architecture.md) 定义的 Reader v4 状态机；该文档是跨 Web、Android、iOS 的唯一权威，本文不再定义兼容状态机。固定生命周期为：

```text
本地事务先写
→ 更新 UI
→ 500 ms trailing debounce
→ durable latest-only pending slot
→ single-flight Reader v4 PUT（mutationId + baseRevision）
→ 成功先持久化 confirmed revision，再以 mutationId 防误删 pending
→ 网络失败保留 pending，生命周期恢复时重试
→ 409 消费被拒 mutation，并在打开的会话内显示非阻断远端进度 notice
```

关键行为：

- 网络恢复、App 进入后台、离开 Reader 时尝试 flush；
- 可重试失败保留最新 durable pending；不可重试失败记录稳定的 terminal failure code，不建立第二套 quarantine 队列；
- 进度读写不得因 Publication fingerprint 变化而拒绝；资源位置仍须属于路由指定的 `resourceId`；
- 启动恢复按精确位置捕获时间确定性选择，时间相同由服务端胜出；显式深链、章节、页码或书签目标始终优先；
- 服务端 revision 前进时，较新的本地 pending 基于最新 revision 重建 mutation，较新的服务端位置消费旧 pending；
- 启动条件不得显示 local/cloud/cancel 阻断对话框；远端替代位置只通过可关闭、可跳转且需精确复核的非模态 notice 呈现；
- 不得重新引入 1.5 秒防抖、单写者租约、`clientSequence`、旧序列 `applied` 状态或独立 quarantine 状态机。

### 7.2 书签同步

当前服务端书签是整组 PUT，未提供 revision、增量 mutation 或服务端冲突合并。第一阶段可实现 local-first，但设计必须能够表达“待同步/同步失败/被其他设备覆盖的风险”，不能将其描述为强一致多端同步。

### 7.3 本地下载工件边界

格式访问策略固定为：阅读和离线下载是两个独立用户意图。受支持的可重排格式、PDF 和漫画在线且缺少已验证本地工件时直接进入 Reader bootstrap，不得创建下载任务或要求先下载；同一命名空间和 Resource/Asset 存在 completed 本地工件时可直接打开本地原文件，网络不可用且无已验证工件时为不可用。只有用户明确触发的下载动作可创建下载任务。Reader 打开不比较 fingerprint、版本、声明长度或服务端页数；下载任务首次进入 completed 前仍必须完成临时 sink、传输完整性检查和原子提交。取消、空间不足、短响应或进程中断不得留下伪 completed。

第一阶段可以承诺：

- 已显式完成、通过完整性验证并原子发布的原始 Resource/Asset 工件；
- authenticated cover 性能缓存与 Reader navigation/range/render 缓存；
- 本地进度 durable outbox；
- 本地书签；
- 明确的下载、网络失败、待同步和内容失效状态。

第一阶段不能承诺：

- 全量书库长期镜像；
- Home、Library、Facet、Book Detail 或 Reader bootstrap 的持久 GET 页面快照；
- 增量 catalog 同步；
- 任意未下载内容离线可用；
- 无冲突的多设备离线书签合并；
- 杀进程后 multipart 上传必然恢复；
- 服务器导入/整理完成的远程 Push 通知。

## 8. 必须保留的用户任务链

1. **日常续读**：首页继续阅读 → Book Detail/ReadableResource → Reader 或播放器 → 本地耐久进度 → 联网同步 → 首页刷新。
2. **发现与开始**：搜索 / 书库 / 系列 / 作者 / 书架 → 保留筛选上下文的图书列表 → Book Detail → ReadableResource → 阅读或播放。
3. **个人整理**：作品动作或书库选择模式 → 加入个人书架；书架 → 作品 → 返回原上下文。
4. **在线阅读与离线下载**：所有受支持原始格式均可从详情在线进入 Reader 或播放器；已有已验证本地副本时可优先使用，但本地副本缺失不阻塞。用户可独立下载到本机 → Download Center 管理/搜索 completed 内容 → 从本地打开 → 产生本地进度 → 有网时继续正常同步。
5. **账户安全**：我的 → 修改账户/语言/密码或退出 → 会话刷新 → 正确保留或清理私有命名空间。
6. **权限变化**：管理员调整范围 → `authzVersion` 变化 → App 清理旧权限缓存 → 重新拉取书库和资源状态。
7. **P1 手工导入**：有权用户选择设备文件 → 选择符合组织方式的服务器书库路径 → 前台上传 → 扫描器绑定目录拓扑 → 查看自己的任务结果 → 打开新作品。

## 9. 明确禁止从 Web 复制的内容

- 响应式汉堡抽屉不是 App 导航依据。
- Web 右键、hover、Ctrl/Cmd 多选、桌面表格、横向工具条和服务器目录树不是 App 交互。
- `/listen/{id}` 不是独立一级页面。
- `/management`、`/organize*`、`/import-tasks` 等兼容入口不是 App IA。
- 首页与书库目前不一致的上传按钮显隐不是权限规范；以 `/me.authorization` 和真实后端 guard 为准。
- Reader v1–v3 与 edition 路由均为 `410` 退役契约；App 只使用 Reader v4 + `resourceId`。
- 外部来源 `sources/source-search-records` 是 tombstone，不设计“移动端书源搜索”。
- OPDS 面向第三方客户端，不作为官方 App 内部 API。
- Web PWA Service Worker 不是原生 Download Center。
- Web Reader 的“笔记/批注”占位不是已交付功能。
- `/openapi.json`、`/docs`、`/redoc`、`/api/__db-ping` 不是产品连接 API；连接检测使用 `/api/health`。

## 10. 设计前置风险与后端缺口

下列问题必须在对应 App 能力进入实现前解决或形成明确降级：

1. **兼容握手验收**：`GET /api/mobile/compatibility` 已固定 protocol v3、最低客户端版本 3、Reader schema v4、Library schema v1 与 Book/Resource/Asset、受管下载 capability；仍须覆盖 base path、错误映射、旧客户端拒绝和 `serverIdentity` 变化的真机验收。
2. **后台下载授权**：iOS/Android 后台下载是否可安全复用 Cookie Jar 必须实测；否则需资源绑定、短期有效的下载凭证。
3. **自签名证书与重定向策略**：服务器添加流程必须定义 TLS 错误、受信任范围、base path 和多服务器切换规则。
4. **跨 renderer 续读**：EPUB CFI/href/snapshot 与原生引擎位置兼容需用真实 EPUB/MOBI/FB2 语料验证 Web ↔ App 双向恢复。
5. **格式与 codec 矩阵**：导入允许的 MOBI/AZW/PRC/FB2、CBR/RAR 与多种音频格式不等于系统 renderer/player 全部支持。
6. **上传不可恢复**：当前 multipart 无 upload session、分块、幂等与断点续传，P1 首版只能承诺前台上传。
7. **书签并发覆盖**：如要承诺可靠多端编辑，后端需 revision 或增量 mutation。
8. **无 catalog delta**：完整本地书库需新增 change token/delta API。
9. **密码重置不适配远程 App**：当前流程依赖服务器本地 reset file 与 Web URL，不是普通邮件 magic link。
10. **远程事件缺失**：没有设备注册、Push token 或事件流，首版仅能提供本地通知和前台轮询。

## 11. 当前 Web 移动视口证据

本次审计以 390 × 844 视口检查当前 Web，目的是识别任务优先级和禁止照搬的响应式表象，不把 Web 截图当作 App 视觉规范。

| 步骤 | 页面/交互 | 健康度 | 对 App 的直接结论 |
|---|---|---|---|
| 1 | 书库 | 有条件通过 | 三列封面适合快速浏览，但长标题截断、管理/上传动作拥挤；App 需原生 Grid/List 与筛选 Sheet |
| 2 | 汉堡导航抽屉 | 不通过 | Web 全量 IA 被压进抽屉；不得作为 App 一级导航，改为四 Tab + 二级 Stack |
| 3 | 首页 | 通过其任务优先级 | 继续阅读是最强任务，最近阅读/最近入库可独立失败；保留任务结构，不复制 Web 卡片样式 |
| 4 | Book Detail | 有条件通过 | 真实来源目录、ReadableResource 和继续 CTA 可复用；App 需原生内容浏览、稳定 CTA 与按 Web 权限过滤的动作 Menu/Sheet |
| 5 | PDF Reader | 有条件通过 | 沉浸阅读、点按唤出工具、进度和目录有效；需原生返回、缩放、scrubber，并移除未实现的笔记承诺 |
| 6 | 设置中心 | 不通过 | 个人设置和系统管理混在网格中；App 只保留账户/语言/下载/关于，系统管理 Web-only |
| 7 | 入库设置 | 不通过 | 390px 下工具条和 Tab 横向溢出；若以后提供任务状态，应使用时间线/列表 + 筛选 Sheet + 详情 Stack |

审计限制：本次 EPUB Reader 在移动视口运行时未完成加载，因此不能用该次截图证明 EPUB 交互已经健康；P0 EPUB 原生交互必须在独立原型和真实设备上重新验收。

## 12. 第二阶段设计准入清单

任何 App 页面、流程或组件开始高保真设计前，必须提交以下最小矩阵：

| 必填项 | 准入条件 |
|---|---|
| 能力等级 | 明确 P0/P1/P2/Web-only/排除 |
| 用户任务 | 能放入第 8 节任务链或给出新增任务依据 |
| 入口与返回 | 所属 Tab、Stack、deep link、系统返回行为明确 |
| 真实 API | method/path、请求/响应 schema、分页/Range 行为明确 |
| 权限 | 未登录、member、system manager、admin、资源范围分别定义 |
| 完整状态 | loading、empty、error、permission、success、conflict 均有去向；请求失败不恢复持久化 GET 页面 |
| 本地数据 | namespace、缓存、清理、加密/安全存储和迁移策略明确 |
| 原生形态 | iOS/Android 控件、Sheet/Menu、系统分享/文件/媒体能力明确 |
| 组件所有权 | 按全局开发规范标记 A/System-owned、B/Native-themed、C/App-owned 或 D/Approved-motion；平台差异和精确还原区域明确 |
| 可访问性 | 动态字体、VoiceOver/TalkBack、焦点、触摸目标、降低动态效果、非手势替代明确 |
| 国际化 | `zh-CN`、`en-US`、动态内容、日期/数字格式和长文本布局明确 |
| 观测与恢复 | 可行动错误、重试、待同步、冲突、日志脱敏和恢复路径明确 |
| 验收证据 | 紧凑/扩展尺寸、浅/深外观、真实设备、弱网/离线、权限变化均有证据 |

不满足该矩阵的页面不得因“Web 已有入口”直接进入 App 设计或开发。

## 13. 主要仓库证据索引

- Web 路由与导航：`apps/web/app/**/page.tsx`、`apps/web/components/layout/app-shell.tsx`
- 首页：`apps/web/features/dashboard/dashboard-page.tsx`
- 书库与筛选：`apps/web/features/library/library-page.tsx`、`apps/web/features/library/api/works.ts`、`apps/web/features/library/api/filtering.ts`
- 系列/作者：`apps/web/features/library/library-grouping-page.tsx`
- 书架：`apps/web/features/shelves/`、`apps/api-python/app/modules/shelf/presentation/http.py`
- Book Detail：`apps/web/features/books/`、`apps/api-python/app/modules/library/presentation/http.py`
- Reader v4：`apps/web/features/reader/v4/`、`apps/api-python/app/modules/reader/presentation/v4.py`
- 跨客户端 Reader 契约：`packages/reader-core/src/`
- 音频：`apps/web/features/audio/`
- 媒体 Range：`apps/api-python/app/modules/media/presentation/http.py`、`infrastructure/http_streaming.py`
- 会话与授权：`apps/api-python/app/core/auth.py`、`core/authorization.py`、`modules/auth/presentation/schemas.py`
- Reader 本地精确进度与单飞同步：`apps/web/features/reader/v4/`、`packages/reader-core/src/`
- PWA 与离线：`apps/web/public/sw.js`、`apps/web/lib/reader/book-cache.ts`
- 设置权限导航：`apps/web/features/settings/center/settings-secondary-nav.tsx`
- OpenAPI 已知缺口：`apps/api-python/docs/openapi-audit/README.md`

本基线优先级高于 Web 菜单、响应式布局和旧移动端遗留实现。若后续产品决策需要偏离，必须同时记录用户价值、API 变更、权限影响、离线影响和迁移/兼容条件。
