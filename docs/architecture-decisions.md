# 当前架构决策

本文合并仍有效的 ADR，只保留现行决策。工程细则见[工程规范](engineering-standards.md)，实现入口见[代码结构](business-code-layering-and-refactoring.md)，验证范围见[测试策略](testing/test-execution-policy.md)。机器契约拥有精确规则与生成绑定；本文不维护第二份策略表。决策有效不代表当前版本已经通过运行验收。

## 数据库与能力边界

对应 ADR 0001、0005、0023。

- 持久化使用 SQLAlchemy ORM／类型化表达式；SQLite 连接与 PRAGMA 属于 `app/db/sqlite.py`，启动检查和线性升级属于 `app/db/runner.py`，已发布 Alembic 迁移不可改写。空库初始化到当前 head，已知祖先可升级，未知版本和无版本的非空库拒绝启动。受控遗留 SQL 修复按工程规范，不扩展为新能力的例外。
- 跨能力只通过所属能力 `public.py` 导出的不可变 DTO、协议或 `app/contracts` 稳定契约；ORM 不穿越边界。Publications 拥有解析和缓存身份，Library 拥有资源与导航投影持久化，原子替换由 Publications 应用工作单元协调。
- Bootstrap 只接线、挂路由与管理进程生命周期，不承载授权、查询、映射、持久化或事务。HTTP、Worker、CLI 调用同一应用用例。Backup 通过注入的 schema registry 参与备份，应用计划只含已校验标量记录。
- 写入顺序：读取投影并关闭读事务 → 在事务外校验、解析、归一化、排序、哈希和准备文件／网络工作 → 构造不可变 Prepared 值 → 短 SQL 写事务 → 提交后映射响应与外部发布。事务内仅类型化 SQL、结果赋值和预构造 SQL 分块的有界迭代；每批最多 900 个绑定参数。用例拥有提交与回滚，仓储可 flush，不隐藏提交。
- 后台维护连接锁等待上限 500ms；每条 SQL（含取结果）独立预算 2 秒，原生 executemany 每组绑定重新计时，不累计语句间停顿或整笔事务时长。前台与恢复连接沿用各自超时策略；繁忙任务保留持久意图并延后。前台写区间超过 100ms 记录耗时／结果，不记录 SQL 和载荷。
- 认证 GET 只读；续期走 `POST /api/auth/session/refresh`，`/api/auth/me` 只提示续期。Reader bootstrap GET 不修复持久导航。元数据写回 OPF 使用显式持久准备意图、租约和 CAS，元数据修改原子登记意图；禁止 ORM flush/commit observer 推导或执行写回。
- 备份恢复是长写事务唯一例外：先在临时库解析校验，再在跨进程维护屏障下用一笔 SQL 事务应用，不能暴露部分恢复。元数据租约队列与下述单消费者导入队列不混用。

## 书库身份与有声书

对应 ADR 0003、0018、0019、0020、0022。

- 唯一关系为 `Library → SourceNode → Book → ReadableResource → ResourceAsset`。SourceNode 是相对路径观察快照；Book 拥有可见性、授权和元数据；Resource 拥有可读性与阅读身份；Asset 拥有真实文件、角色、顺序和传输身份。公开接口用 `bookId/resourceId/assetId`，仅物理路径管理用 `sourceNodeId`，不保留 Work/Version/Volume/File 双读写或兼容路由。
- 组织方式仅 FLAT、VOLUMES；已有来源节点时不能原地切换。具体归属见[书库结构](library-root-layout.md)。符号链接只记录不跟随；范围按精确路径段比较，不用大小写、Unicode 归一化或字符串前缀放宽。移动／重命名不暗中迁移身份。
- 有声书是资源适配器，不是组织方式。目录资源拥有直属音轨及中间路径全为 `CD/Disc/Disk/碟/盘`（可带编号）的后代音轨；普通子目录是不可穿透边界。只有普通子目录音轨的父级保持 NODE_ONLY；父级有直属音轨时自身成资源，子级独立。VOLUMES 首层为 Book，FLAT 每个目录资源独立成书。其他目录适配器保持自身规则。
- 发现复用有界扫描与机器契约 `audioTrackMaxCount`；超限返回生成错误，不创建被拒绝音轨资产，其他目录仍可导入。单音频走正常适配器，不按文件名归组。音轨只保存受限入口取得的标题、MIME、时长、编码等；聚合只统计 READY TRACK，任一时长未知则总时长未知。唯一且非泛化的内嵌音轨标题优先，否则用原文件名，不覆盖 Book/Resource 标题。

## 扫描与导入

对应 ADR 0018、0021、0029、0030。

- 首次、补齐与用户重试共用 ContinueImport 和 `LibraryImportTask` 单消费者队列，任务为 SCAN_LIBRARY、CONTINUE_SOURCE、IMPORT_ASSET、IDENTIFY_BOOK；不增加 legacy queue、租约、heartbeat 或自动接管。解析与扫描在事务外，部分成功不因其他项失败回滚；失败业务由明确重试／扫描规则处理，终态持久化重试不重跑业务。
- `RequestLibraryScan` 是唯一触发入口。监听只写内存缓冲，Worker 主循环入队；新建／移入按 5 秒静默窗合并，修改仅延后已有待处理新建，独立修改不触发。启用书库共用持久周期设置，启动、书库变化和监听重建做对账；监听故障不阻断 Worker，周期扫描补偿丢失事件。
- 每库最多一个 QUEUED 和一个 RUNNING 扫描；运行时可排一个后续任务。自动触发用 PRESERVE，手动用 PRUNE_MISSING，合并只能升级为清理。只有相应目录完整正常遍历后才清理缺失节点。扫描不按触发类型批量重排失败任务，遇到兼容 Asset 时复用同一补建／重置规则；指定失败任务走 task-scoped ContinueImport。
- 导入只读取文件属性、元数据、目录、指定封面、必要页码和有限编码样本。通用结构累计 8 MiB／文件，元数据文档 2 MiB，指定封面 20 MiB，编码样本 4 MiB + 3 字节；预算耗尽保留已知值，不作为出版物拒绝规则。禁止全文解码／正则、全页预检、全媒体包／块计数和失败后的全文件修复；分块、后台、限时均不构成例外。上传保存与实际阅读／播放不属于导入探测。
- 图片目录与 PDF 无有效元数据封面时，允许仅将阅读页序第一张图片／PDF 物理第 1 页读取或渲染为封面；导入与显式封面重生成共用该回退，不跳到后续页、不进行全页扫描。渲染失败不使资源导入失败，不在封面 GET 时生成，不回填存量。
- PDF 不做文本分类、损坏索引恢复或虚构页数；TXT 不查全文和尾部 NUL；FB2 到 description 结束；MOBI 按记录表取元数据／封面。ZIP/CBZ 只用中央目录登记页，不逐成员读本地头、预计算重叠或读普通页；RAR 不提取成员。音频导入不运行 ffprobe，无受限标签入口仍登记资产、未知信息为 null。实际请求成员时由 SDK 与 Reader 做结构／完整性检查，坏页保留位置。
- READY 只表示可尝试打开，不是正文验证通过；缺失、访问错误和已确认安全违规仍失败。重导清除失效技术值与导航，不改人工描述性元数据，不要求批量重导历史资源。验证真实读取区间、累计字节、禁止正文访问，以及首次／重导／重试／取消／回滚，不以命名或编译代替证据。
- 文件任务只写 Asset/Resource，所属文件任务和扫描终结后识别 Book；失败为终态不阻止本地识别，取消不触发收尾。本地必跑，联网按自动整理设置；文件状态与元数据状态独立，联网失败保留本地结果。
- Book 按用户 SIDECAR_OPF／EMBEDDED／PATH 优先级逐字段合并；只在一个已启用资源时继承其候选，多资源不继承子卷正文，人工编辑含清空受保护。名称只看自身，支持明确作者标记、“书名 - 作者”和完整 `[书名][作者]`（去已知扩展名、两个非空字段、允许空白后继续卷号解析）；不猜父目录、多组括号或缺失字段。
- Book 无自有封面时先选路径排序第一个可读资源，再验证该资源封面；无效用默认展示，不跳到后续资源、不持久化默认图。导入收尾与整本重生成共用规则。
- BookMetadata 保存 importRevision、processedRevision、metadataPending、metadataState；活动 IDENTIFY_BOOK 对根节点唯一并记录执行修订，写回检查修订、人工编辑时间和来源优先级。任务终态独立提交；失败保留已执行结果按原轮询重试，成功或任务删除前不领取下一项、不重跑业务。重启先独立收尾 RUNNING，识别补偿不得回滚它。
- Worker 每轮在写事务外准备至多 50 本待识别 Book 与任务 ID，释放读事务后独立校验修订、活动导入、取消与重复任务并入队。失败保留 metadataPending，后续轮询／重启补偿，不新增队列、提交回调或事务循环。
- Book 响应保留 metadataState（WAITING_IMPORT/QUEUED/RUNNING/COMPLETED/FAILED）、metadataPending、metadataOnlineState；resourceImportSummary.failedFiles 与资源 failed 独立。Asset 只存有界来源候选和封面引用；文件封面先独立版本发布再提交引用，失败／取消撤回新版本、保留旧版，Book 封面复用根节点备份发布。已发布迁移不改写、不回填旧业务数据。

## 原生客户端与会话

对应 ADR 0006、0015、0020。

- KMP `:shared` 通过 ErmaoShared 共享领域、DTO、API、Cookie、会话、导航意图和用例；Compose `:androidApp` 与 SwiftUI `iosApp` 各拥有原生 UI、可访问性、导航栈、布局和生命周期。iOS 通过 Xcode direct integration 接入，不用 CocoaPods／实验 Swift Export；Mobile 不引入 Node 或 pnpm/Turbo。能力仅因真实隔离／消费者需要拆 Gradle 模块。
- Home、Library、Shelves、Me 独立保存导航栈；Reader／Now Playing 属根级呈现。依赖遵循 public facade → application → domain，基础设施实现端口；新增共享状态须两端安全处理。精确视觉数值唯一源为 `packages/design-contracts/visual-tokens.json`；Kotlin/Swift/Android 绑定构建生成，Web CSS/TS 提交以支持 Node-only 构建。
- profileId 拥有地址、Cookie、活动选择和验证记录；地址为可带 base path、不带 `/api` 的规范外部地址。握手证明 serverIdentity，唯一生成者为后端 compatibility 能力：protocol/minimum client 为 3、reader schema 为 5、library schema 为 1，能力标志反映真实支持，管理能力不绕过授权。进入私有 Shell 前验证；连接／编辑／切换先完成健康、兼容、设置和会话预检，失败保留原活动 profile 与导航。
- Cookie 按 profile 隔离，Android Keystore/AES-GCM、iOS Keychain AfterFirstUnlockThisDeviceOnly 存储；普通快照／键值存储不含密码或 Cookie。默认系统 TLS，仅允许原生风险确认后的单 profile 绕过，不允许全局绕过。
- KMP 唯一拥有会话状态和 ServerProfileRepository、CookieVault、VerifiedSessionRepository。成功 `/api/auth/me` 原子保存验证记录（profileId、serverIdentity、用户、授权快照／版本、lastValidatedAt），无自行定义的到期或状态字段。冷启动匹配记录可立即恢复普通 Authenticated Shell并后台验证；它不是新授权。
- 网络、超时、TLS、5xx、解析失败保留已恢复 Shell；401、ACCOUNT_DISABLED、确认 serverIdentity 改变则清理对应 Cookie／验证记录并移除私有 Shell。退出、删服务器、改地址、恢复系统 TLS 清除验证记录；首次无记录仍需在线设置／登录及成功验证。
- 无独立离线模式、宽限期、剩余天数、离线导航或 downloaded-only 筛选。Home/Library/Facet/详情不持久化 GET 页面；首次／刷新失败显示局部错误，后续分页失败保留本轮已加载页。下载中心是本地下载发现入口，下载、封面性能缓存、Reader 缓存、进度、书签、偏好不重建服务器页面；撤权遮蔽私有内容。
- 一般私有缓存按 serverIdentity + userId + authzVersion 隔离；Reader 精确本地位置按 serverIdentity + userId + clientId + bookId + resourceId，不含 authzVersion，重新认证不隐藏同一记录。Reader v5 待同步机制按下文执行，不引入另一套全局离线同步。

## Reader 原件与章节

对应 ADR 0009、0012、0014、0016、0025。

- 第一方 EPUB/FB2/TXT/MOBI/AZW/AZW3/PRC 使用 DOWNLOAD_ORIGINAL：授权 asset 完整下载、验证身份／版本／长度并原子发布后，由本地 parser 打开。原件是唯一持久正文，不生成、缓存或下载派生 EPUB/ZIP、生成章节集或解包目录；TXT/FB2/MOBI 只提供内存 Publication。
- Native `DownloadResourceRuntime` 唯一拥有完整下载、去重、续传、校验与登记；平台提供私有 staging、原子发布和清理，按授权／资源／asset／版本／长度隔离。Reader 观察或打开同一工件，不复制下载管线。Web 使用账号隔离的 Reader Cache Storage，不创建原生下载中心状态机。漫画／image_dir 用有界 manifest/page，音频走播放器、不隐式创建可重排下载。
- 实际格式 parser/engine 决定可读性；服务器指纹、诊断版本、页数和百分比不成为第二道解析门槛。安全／引擎失败不触发旧解析器、修复或在线回退。进度、书签、设置尽力恢复，缺进度可从头；SDK 无法恢复 Locator 明确报 LOCATION_RESTORE_FAILED，不改写；进度持久化失败不阻止打开／关闭。
- libmobi 公共入口是 `apps/mobile/native/mobi-core` 的 `ermao_mobi_*` ABI v1：不透明对象、串行访问、struct_size、定宽整数、UTF-8 调用方缓冲复制；稳定资源索引／名称／类型／长度及受 ERMAO_MOBI_MAX_READ_BYTES 限制的读取；目录身份用资源索引不用标题，返回稳定状态／警告。JNI、iOS wrapper、后端 adapter 可调用，UI／领域不可；后端使用前检查 ABI 版本。ABI 有界读取不等于上游流式解析，PDB/RAWML 仍受 parser 内存预算限制；分发须核对许可和实际平台证据。
- 服务端 `NormalizedPublication.toc` 仅用于详情章节投影。EnsurePublicationNavigation 解析当前已授权验证 asset，原子写导航行和按 assetId 的成功标记（含零章节）；变化／删除使缓存失效，其他 asset 不复用。失败与空目录区分，不新增队列／轮询／锁／发布协议。Reader reading order、TOC、positions 来自本地原件，不依赖服务端投影；漫画／音频索引保持格式语义，章节共用[章节核心](mobile-reader-architecture.md#统一章节核心)。
- 验证慢传输未完成不打开、完整缓存不重传、截断／取消不发布、缓存删除可重建、可重排不请求远程正文章节。

## Reader 安全

对应 ADR 0026。

- 唯一语义源是 `packages/reader-contracts/reader-safety-policy.json`，schema 与 policy 分别版本化；规范 JSON 使用 UTF-8、排序键和无多余空白，摘要排除 policyDigest 自身，生成 TS/Kotlin/Python/C 绑定；iOS 经 KMP 使用，不维护 Swift 策略。随构建发布，无远程修改或 bootstrap 策略握手。
- 格式适配、含边界值的预算、算法、ruleId、阶段、消费者、动作、错误、标记／URI／CSS／SVG／XML／DRM、PDF／漫画／音频及平台隔离要求均由机器契约拥有。适配器只检测事实并调用生成决策，不建私有阈值、白名单、MIME 表或安全错误。后端 parser snapshot 预留内存亦属于契约；驱逐不能准入单体超限，缓存数量／闲置淘汰不成为准入规则。
- 默认 ALLOW，按明确危险行为黑名单处理；动作仅 ALLOW、SANITIZE、BLOCK_RESOURCE、REJECT_PUBLICATION。未知声明／标签／实体／scheme／MIME 不自动危险。可恢复主动内容在内存清理后继续；可隔离的坏图片、字体、目录、漫画页只隔离资源；CRC／冲突字节属于完整性错误；实际 parser／解密失败、容量、缺平台防护按 CAPABILITY/INTEGRITY/RESOURCE_LIMIT/IMPLEMENTATION 分类，不伪装安全指控。
- 所有 DOCTYPE 在易失副本去外部依赖；有界内部文本实体转义展开，外部／递归／参数／未知引用保留字面，禁用外部解析，不增加无限 DTD parser。普通点路径可归一，真正越根阻止；未知加密声明不能替代解码结果。
- 原生 ContainerAsset 在 PublicationOpener 前保护控制文件，正文/CSS/SVG 懒读经过同一容器；渲染回调不担安全入口。每次打开可保存首个致命错误，关闭／取消／账号切换清理；重开、重试、懒读应用当前检查，无全局可变失败状态、规则事件历史或出版物图重分类框架。
- 清理不改变原件／下载字节，不持久化衍生物；语义过滤变化递增策略版本和受影响 normalization 标识，但诊断变化不迁移／重置 v5 进度。原生 PDF 共用仓库 PDFium，Web 用 pdf.js，各平台履行同一决策与限制；缺防护报 ENGINE_*／PLATFORM_*，不得回退绕过。
- 一致性样例记录输入 SHA-256、消费者、动作、终态、规则事件与语义投影摘要；生成器检查 schema、语义、交叉引用和漂移，boundary checker 禁私有规则。CI 按契约执行 generator --check、单测、边界与消费者套件；报告标识 policy/version/digest，日志不含正文、私有路径。保留历史回归样例，活动套件依机器契约；Chromium/WebKit 验证无网络隔离，原生验收需真实适配器与物理设备，不能用共享测试替代。

## PDF 原件物化与串行执行

对应 ADR 0027。

- Web pdf.js 保持在线 Range、无需完整下载的首屏。原生 PDFium 可请求文件内任意正 Long 区间；KMP 拒绝零、溢出、越界。HTTP 每段不超过 1 MiB、强版本校验 206，拒绝整文件 200，易失缓存最多 8 MiB。
- 整文件请求、工作集超缓存或本会话必需区间覆盖全文件时，PdfRangeLoader 返回 CompleteOriginalRequired（不是 PDF_RANGE_INVALID）。离开 PDFium executor 后调用同账号 Downloads 创建／加入同资源版本唯一任务，不拼接 Range 缓存或另建下载流程。
- 校验完成后在同一 document handle 原子切为本地随机访问 source，关闭 loader／清缓存并重试原步骤；不重建页面、不新增下载进度 UI，首次保留加载态、翻页保留现有页面。Reader 关闭仅取消自己的等待与渲染，不删除／取消已创建普通下载。
- 物化失败、空间不足、版本／账号变化或本地读失败终止本次操作，不回退 Range 或同会话重复物化；显式重开可新建会话并复用合格工件。
- 所有 PDFium API（含初始化／关闭）用进程互斥保证并发为 1，Android 应用级单线程 dispatcher、iOS 后台串行 executor。网络、下载等待、文件准备在 executor 外；同步回调仅登记区间／读已缓存字节，不联网、等待、访问 UI 或重入。主线程只更新状态与图像。
- 验证大请求转物化而非超大 Range、非法范围无网络、切源拒绝旧响应、重复请求仅一次物化、API 串行、Web 不回归；物理设备检查慢下载时返回／关闭、页面保留、完成后下载中心重开。

## Reader v5 进度

对应 ADR 0028。

- ReaderPositionReport 的 locator 保留引擎完整 JSON 对象，presentation 独立携带百分比、totalProgression、href／章节／页／播放信息。恢复只用 locator，书库只用 presentation；服务端不读 Locator 键、不验证正文锚点、不推导展示值。空字符串、null、未知嵌套保留语义，不要求键序、空白或数字拼写；紧凑 UTF-8 上限 64 KiB，可通用编解码／测量／哈希。
- 写入带 UUID mutation id、不带 baseRevision；服务器按事务提交顺序分配递增 revision，最后成功提交为现值，客户端时间仅元数据。相同重放返回原 revision 不写入，同 ID 不同内容报 READER_PROGRESS_MUTATION_REUSE。
- 客户端联网前原子保存完整报告和最新 pending mutation，重试同 ID／内容，确认只清除匹配 pending。启动顺序：显式目标 → 本地 pending v5 → 服务器 v5 → 开头；其他设备不能后台移动活动会话。
- v5 独立存储并统一 `/api/reader/v5`；不读、迁移或删除旧 v4 进度／回执／outbox。SDK 才判断导航是否可恢复，客户端不修补服务端值、不截断文本、不注入 progression、不拼不同次 Locator。跨端格式 adapter 提供一致性样例。
- 阅读状态独立于定位，标已读不制造 Locator；手动状态操作的清理与重开行为见[内容导航](mobile-book-content-navigation.md#手动阅读状态)。日志仅身份、revision、字节数、结果，不含 Locator 或正文。

## 服务端账户头像

对应 server-owned-account-avatar。

- 认证响应 avatarImageUrl 用于展示，nullable avatarUrl 只标识自定义上传；setup/login/session/账号修改共用服务端响应解析。认证 GET `/api/auth/avatar` 返回上传或服务端内置无损 WebP 默认图，private, no-cache；共用有界文件适配器处理交付／清理，读取不写入。
- Web 共用头像组件，KMP 传展示地址给两端，原生展示响应字节；缺失／失败留空，不生成首字母、BrandMark 或待上传替代图。旧服务端无字段仅用现有自定义 URL；默认图能力需服务端与客户端配套部署。

## 发布与版本

- 根 package.json 为版本源，正式 tag 为 v<version>。发布前运行 pnpm release:validate（必要时 --tag），核对脚本覆盖的 Web/核心/契约/POC、Python、service worker、锁文件、Android/iOS 版本，不因宿主分工排除其他端；同步双语说明与索引，摘要有实际用户价值，不用空说明或纯自动列表。
- 正式发布统一 fnos-package workflow，复用移动检查、构建原生章节库再测后端、构建版本镜像与 FPK；shared signer 的 stable/beta 渠道独立密钥与包名。正式 com.ermao.library，最低 API 26，更新保持签名并递增 versionCode。私钥在仓库外生成一次并独立备份，Secrets/DPAPI 不作唯一可恢复备份，不使用 Debug/Beta 代签；RELEASE_/BETA_ 两组 KEYSTORE_BASE64、KEYSTORE_PASSWORD、KEY_ALIAS、KEY_PASSWORD 缺失即失败，密码不入命令字面或日志，PR 不拿密钥，仅发布任务可写 Release。
- 最终 APK 经 zipalign 16KiB 对齐、签名、apksigner verify 与对齐复查后生成 SHA-256，命名 ermao-library-v<version>-android.apk。APK、FPK 及摘要一起上传草稿，核对远端摘要后才能提升 prod/latest、公开 Release 和 feed；失败不公开部分版本。main 手动构建候选，最终签名 APK 完成物理设备验收再建正式 tag；签名冲突卸载需用户明确授权。未完成门禁只留草稿，不切 Latest 或建公开正式 tag。
- 正式提交须同步远端 main：fetch 后快进或保留双方正常合并，不强推、不夹带冻结后无关改动；新 tag 前验证远端 main 包含发布提交且版本／说明匹配。已发布 tag 不移动，修复用补丁版本；最终核对 main/tag/Release/Wiki/release-feed 和日期，未同步 main 不算完成。
- develop 相关推送／手动才发布 Android Beta，其他分支／PR 不发布。全部移动检查成功后签名并更新 android-beta；旧运行不覆盖新运行、失败不替换上一版。包名 com.ermao.library.beta，非调试配置，版本追加 -beta.<run_number>、versionCode=100000+run_number，重跑保持安装版本，附件以 SHA/attempt 区分，迁移不能重置计数。标签可变但不作 Latest，不进正式说明／更新源；先上传新验证附件，再更新标签／说明，最后清旧附件，后续成功运行可清中断遗留。
- 局部修复、集成与冻结 RC 按测试策略分别验证；最终 RC 满足该次完整门禁及设备证据，冻结后变化按影响重验。CI 冒烟不代替真机。
- 删除协议：卷册源文件 DELETE /api/books/{book_id}/resources/{resource_id}/source 无必需请求体，旧 confirmation 可接受但不校验名称；先部署后端再发布不发送该字段的客户端。整书删除保留 DELETE_SOURCE_FILES 固定协议值，权限、归属、幂等和范围不变，不新增迁移。
