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

## 自动化 MCP 接入

对应 ADR 0031，依据用户确认的 [MCP v2 执行规格](plans/mcp-integration-v2.md)；实现状态见[实施记录](integrations/mcp-implementation.md)。

- 2026-09-22 更新 ADR 0031：设置页使用 MCP 服务／授权服务／操作列表三个 URL Tab，默认授权列表，配置导出绑定具体授权行。服务关闭拒绝创建，保留本人有效授权配置取回。
- 授权列表行内可修改本人有效授权的名称、范围、能力与有效期，沿用原 ID、令牌摘要及密文；已撤销／过期不可修改。`PATCH /api/automation/grants/{id}` 复用 Cookie、Origin、当前账户能力校验及审计，服务关闭仍可修改。省略 `lifetimeDays` 保留到期时间，显式 null 改为长期，天数从保存时起算；后续 MCP 调用和后台发布边界使用最新权限，既有冻结方案不扩展。
- 授权创建表单默认勾选当前可授权的全部能力及子选项；API 省略 scopes 仍保持原只读默认。有效期保留 30／90／365 天并增加显式 `lifetimeDays: null` 长期选项，默认仍为 90 天。领域和 API 用 `expiresAtMs: null` 表示长期；持久化适配器在既有非空 expiresAt 列中用保留值 0 编解码，历史正时间戳保持原到期语义。长期授权仍执行撤销、当前账户权限和服务开关校验。
- 新授权默认 `libraryScope=all`，按所属账户当下可访问库动态求值；`selected` 保存明确 ID。0026 将历史授权保留为 selected，旧请求省略该字段也按 selected，不自动扩权。查询、写入、worker 和历史访问复用同一有效范围计算；冻结文件方案目标不因动态范围增长而增加。
- 新 token 同时保存认证摘要与 AES-GCM 密文，关联用户及 grant ID。密钥以 0600 原子创建于独立 `storage/secrets/automation-token.key`，部署须持久化并单独备份；存在密文但密钥丢失时拒绝生成替代密钥。撤销清除密文；历史摘要凭证仍可认证但不能恢复。
- `POST /api/automation/grants/{id}/reveal` 仅接受本人有效 Cookie 会话和合法 Origin，拒绝过期／撤销凭证，响应 no-store，审计只记身份与授权 ID。列表不暴露明文；浏览器仅在当前授权配置面板内保留明文，关闭、切换授权／分区／账户即丢弃。
- HTTP 和 HTTPS 均支持域名、IP、端口和实际部署前缀，不再有额外 HTTP 选项；合法 URL、Bearer、Origin/Host 校验保留，入口为实际根地址的 `/api/mcp`。
- 2026-09-22 文件属性策略：元数据回写与文件移动仅尽力保留所有者、权限、时间戳、文件标志、扩展属性和 ACL；属性读取、设置失败或复制后不一致不阻止成功。继续强制校验内容、源文件身份、授权与路径边界、持久化及安全发布；回写更新修改时间以失效阅读缓存。
- 2026-09-22 文件任务逐项独立执行：失败、等待、已中断或需恢复的条目及历史备份不阻塞其他条目和任务，包括后续操作同一文件。领取跳过尚未到重试时间的条目；移动逐项校验、提交结果，单项失败不取消剩余项。保留正在执行的互斥和原子领取，后续任务依据自己的冻结方案校验当前文件、授权与发布条件；失败／需恢复项不自动重置重放，历史现场保留，未执行项仍可领取。此规则取代此前整库恢复占用和备份未释放拦截规则，导入自身的必要输入依赖不变。
- 2026-09-22 对话附件：采用纯 MCP JSON Base64 分块传输，新增 `begin_upload`、`upload_chunk`、`complete_upload`，复用操作查询／列表／取消。客户端必须提供原始附件字节，不接受路径或 URL，不允许模型重建附件；仅有私有附件链接的客户端不宣称支持。
- 上传新增独立 `files:upload`、`covers:write`，历史授权不扩权。Automation 拥有上传身份、限额、进度和持久阶段（迁移 0027，内容只存受控暂存区）；Imports 复用原件发布与既有局部扫描队列；Library 复用图像校验、封面发布和元数据修订／人工保护，更新指定 Book 展示封面，不修改资源或内嵌图片。通过类型化端口与装配根接线。
- 附件按原始字节分块，单块 256 KiB、图书 8 GiB、封面 12 MiB；音频另受既有上限约束。每授权未完成数 20、暂存预留 8 GiB、最后有效传输后 24 小时过期；失败但未清理的暂存仍占字节预算。分块落盘和数据库确认成功后才返回偏移；逐上传文件锁防止并发重复执行。Worker 现有循环进行有界清理，不增加调度框架。
- 图书发布使用显式同名拒绝及不覆盖原子的发布，网页上传默认行为不变。最终重新校验范围、目录身份和边界；记录发布证明、保存与登记阶段，重试不重复保存／入队。文件保存与导入成功分开报告，导入失败保留原文件。封面以上传独有文件发布，再与元数据及操作结果在同一事务生效；版本或权限冲突保留旧引用。
- 上传查询区分传输完成、已保存、等待导入、导入中及最终结果；失败独立，基础数据库故障不能当成功。取消仅限未开始发布的上传，过期清理仅删除自身暂存，不删除已发布原件／封面。恢复证明不阻塞其他任务。协议 SDK 验证与具体聊天客户端附件验收分别报告，接入说明见 [附件调用说明](../examples/mcp/attachment-uploads.md)。
- Automation 拥有受限授权、MCP 适配和业务请求身份；Library 拥有系统元数据与文件移动；Metadata 拥有标准格式写回。调用经公开应用契约和装配根接线，不复制业务表或建立第二套扫描／写回队列。
- `/api/mcp` 使用锁定的官方 SDK 和 Bearer；授权管理仍使用第一方会话，自动化凭证不接入其他 REST 认证。服务默认关闭，每次调用和持久文件任务关键阶段重新验证当前用户、grant、部署能力与书库范围；管理员没有令牌范围绕过。
- 系统元数据修改与文件写回分别授权。Automation 发起的系统更新采用应用层 DB-only 策略，不继承全局自动写回；原 Web 配置语义保留。保护字段覆盖须指定字段及版本，不解除其他保护。
- 文件操作使用固定方案、幂等业务请求、持久阶段和有限恢复，允许已授权客户端连续 plan/execute，不增加 Web 人工审批。跨盘先校验目标再清理源，多个文件与数据库不宣称全局原子提交。显式应用移动保留业务身份，外部文件移动仍按既有扫描观察规则处理。
- 该范围包含 v2 的全部格式与验收矩阵，未完成项不能隐藏后宣称交付；新增依赖和迁移不满足 code-only 发布资格，发布仍需用户另行授权及当前门禁。

## 书库身份与有声书

对应 ADR 0003、0018、0019、0020、0022。

- 唯一关系为 `Library → SourceNode → Book → ReadableResource → ResourceAsset`。SourceNode 是相对路径观察快照；Book 拥有可见性、授权和元数据；Resource 拥有可读性与阅读身份；Asset 拥有真实文件、角色、顺序和传输身份。公开接口用 `bookId/resourceId/assetId`，仅物理路径管理用 `sourceNodeId`，不保留 Work/Version/Volume/File 双读写或兼容路由。
- 组织方式仅 FLAT、VOLUMES；已有来源节点时不能原地切换。具体归属见[书库结构](library-root-layout.md)。符号链接只记录不跟随；范围按精确路径段比较，不用大小写、Unicode 归一化或字符串前缀放宽。移动／重命名不暗中迁移身份。
- 有声书是资源适配器，不是组织方式。目录资源拥有直属音轨及中间路径全为 `CD/Disc/Disk/碟/盘`（可带编号）的后代音轨；普通子目录是不可穿透边界。只有普通子目录音轨的父级保持 NODE_ONLY；父级有直属音轨时自身成资源，子级独立。VOLUMES 首层为 Book，FLAT 每个目录资源独立成书。其他目录适配器保持自身规则。
- 发现复用有界扫描与机器契约 `audioTrackMaxCount`；超限返回生成错误，不创建被拒绝音轨资产，其他目录仍可导入。单音频走正常适配器，不按文件名归组。音轨只保存受限入口取得的标题、MIME、时长、编码等；聚合只统计 READY TRACK，任一时长未知则总时长未知。唯一且非泛化的内嵌音轨标题优先，否则用原文件名，不覆盖 Book/Resource 标题。

## 扫描与导入

对应 ADR 0018、0021、0029、0030。

- 首次、补齐与用户重试共用 ContinueImport 和 `LibraryImportTask` 单消费者队列，生产任务为 SCAN_LIBRARY、CONTINUE_SOURCE、IMPORT_RESOURCE、IDENTIFY_BOOK；IMPORT_ASSET 仅保留升级转换和历史查询兼容，不再生产或消费；不增加 legacy queue、租约、heartbeat 或自动接管。解析与扫描在事务外，部分成功不因其他项失败回滚；失败业务由明确重试／扫描规则处理，终态持久化重试不重跑业务。
- 单文件资源、IMAGE_DIR 与 AUDIOBOOK_DIR 按 `IMPORT_RESOURCE` 调度，sourceNodeId 必须为资源锚点、role 为空；同资源只有一个任务行。排队请求合并，运行中有效变化设置 rerunRequested，终结本次执行时保留下一次待办；仍为单消费者，不增加抢占或自动接管。音频目录复用目录资源执行和资产批次；只替换变化音轨自身章节，结束后统一执行音轨／章节安全重排、总时长和数量汇总。存在未知时长时总时长保持未知。内嵌封面以资源内内容哈希去重保留候选引用，最终只发布选中产物；0014 合并旧未完成音频任务。图片目录一次加载成员和成功版本，最多 200 张一个资产事务；节点校验和资产写入使用集合操作。目录元数据、自然顺序封面选择和资源数量在文件处理结束后统一收尾，不为每张图片复制目录候选。旧未完成图片任务由 0013 合并，已提交批次在中断恢复时复用。
- Asset.processedSourceVersion 记录实际读取文件的大小、纳秒 mtime 和适配器身份／版本／格式，与成功资产及资源收尾在同一事务提交；扫描节点观察不能替代该字段。解析前后文件版本或扫描上下文变化时拒绝旧结果并保留待办。重启中断任务经既有继续导入恢复，已提交且输入一致的结果不重复解析或发布封面。旧未完成单文件任务通过迁移转换，历史成功版本留空，不伪造回填；缺少可靠版本时在再次处理该资源时保守重处理一次。
- `RequestLibraryScan` 是唯一书库扫描触发入口。监听记录新增、修改、删除和移动的路径范围，按 5 秒静默窗合并，Worker 主循环持久化入队并按事件版本确认；启动监听不枚举全树。普通文件扫描父目录直接子项，新建目录递归扫描子树，聚合资源提升至所属资源目录。启用书库共用持久周期设置，启动、书库变化和监听重建做全库对账；监听故障不阻断 Worker，周期扫描补偿丢失事件。
- 每库最多一个 QUEUED 和一个 RUNNING 书库扫描；运行时新事件排入后续任务，不修改运行中范围。待执行范围合并，递归父目录覆盖子目录，全库覆盖局部。自动与手动共用对账和缺失清理规则；先在事务外完整读取一个目录及必要探测，再应用数据。访问、属性读取、迭代或探测 I/O 失败保留对应目录数据，任务标记失败，其他成功目录不回滚；取消不记为成功。扫描不按触发类型批量重排失败任务，遇到兼容 Asset 时复用同一补建／重置规则；指定失败任务走 task-scoped ContinueImport。
- 扫描复用完整目录枚举和已确定的资源归属，节点按最多 200 项批量读取、比较和写入；变化节点与去重后的资源待办同事务提交。`observedAt` 保留用于更新时间展示／排序，仅在观察属性变化时更新。`scanContextVersion` 通过迁移 0015 保存 sidecar／指定封面属性和相关配置的扫描指纹，不代表资产成功处理版本，不全文哈希媒体。无变化扫描不重新 dirty Book 或执行资源任务；元数据变化复用文件结果。
- 依赖按必要输入和扫描范围判断，不以书库或创建来源判断：单文件资源节点与观察已提交即可执行；目录资源与书籍识别只等待覆盖其锚点的未完成扫描范围，其他路径和书库的独立扫描、资源导入与识别继续执行。未完成范围独立于扫描任务记录持久化，升级时一次性把旧 FAILED 扫描的未完成范围转入该记录（按执行完成时间与覆盖范围判定恢复，不以创建顺序推断，执行时间缺失时保守保留，已执行旧版迁移的实例由后续一次性补偿迁移修正），删除、替换或合并失败任务都不会解除仍未满足的输入条件，只有随后真实覆盖该范围且完整完成的扫描才解除；一轮扫描以确认完成的精确范围替换旧范围，未访问范围继续保留，根非递归完成不解除递归缺口；恢复入口是既有扫描，任务接口只读投影说明等待原因与恢复入口，等待任务保持 QUEUED。新的扫描请求合并未完成范围，复用或合并其队列记录；完整枚举才允许按原缺失策略清理。应用层 `ContinueImportTask(force=True)` 显式清除该资源资产的成功处理版本并复用同一待办，保留可读结果和身份；默认继续导入仍增量复用。
- 每库 `allowEmptyLibraryCleanup` 默认关闭：已有索引的根目录成功读为空时，保留数据并以 `EMPTY_LIBRARY_PROTECTED` 失败；启用后允许清理，新建空库正常完成。该设置不能放行任何访问错误。局部扫描同样检查根目录可访问及空库保护。配置界面的扫描按钮只提交现有队列，不直接执行扫描，也不将排队显示为完成。
- 导入只读取文件属性、元数据、目录、指定封面、必要页码和有限编码样本。通用结构累计 8 MiB／文件，元数据文档 2 MiB，指定封面 20 MiB，编码样本 4 MiB + 3 字节；预算耗尽保留已知值，不作为出版物拒绝规则。禁止全文解码／正则、全页预检、全媒体包／块计数和失败后的全文件修复；分块、后台、限时均不构成例外。上传保存与实际阅读／播放不属于导入探测。
- 图片目录与 PDF 无有效元数据封面时，允许仅将阅读页序第一张图片／PDF 物理第 1 页读取或渲染为封面；导入与显式封面重生成共用该回退，不跳到后续页、不进行全页扫描。渲染失败不使资源导入失败，不在封面 GET 时生成，不回填存量。
- PDF 不做文本分类、损坏索引恢复或虚构页数；TXT 不查全文和尾部 NUL；FB2 到 description 结束；MOBI 按记录表取元数据／封面。ZIP/CBZ 只用中央目录登记页，不逐成员读本地头、预计算重叠或读普通页；RAR 不提取成员。音频导入不运行 ffprobe，无受限标签入口仍登记资产、未知信息为 null。实际请求成员时由 SDK 与 Reader 做结构／完整性检查，坏页保留位置。
- READY 只表示可尝试打开，不是正文验证通过；缺失、访问错误和已确认安全违规仍失败。重导清除失效技术值与导航，不改人工描述性元数据，不要求批量重导历史资源。验证真实读取区间、累计字节、禁止正文访问，以及首次／重导／重试／取消／回滚，不以命名或编译代替证据。
- 文件任务只写 Asset/Resource，所属文件任务和扫描终结后识别 Book；资产导入失败为终态不阻止本地识别；扫描失败须先恢复完整清单，取消不触发收尾。本地必跑，联网按自动整理设置；文件状态与元数据状态独立，联网失败保留本地结果。
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
- Native `DownloadResourceRuntime` 唯一拥有完整下载、去重、续传、校验与登记；平台提供私有 staging、原子发布和清理，按授权／资源／asset／版本／长度隔离。Reader 观察或打开同一工件，不复制下载管线。Web 使用账号隔离的 Reader IndexedDB 原文件库，HTTP／HTTPS 共用；原件以至多 1 MiB 分块写入，校验完成后事务发布，取消／失败不发布。事务校验账号与授权代次，退出和权限变化使旧写入失效；不创建原生下载中心状态机。漫画／image_dir 用有界 manifest/page，音频走播放器、不隐式创建可重排下载。
- 实际格式 parser/engine 决定可读性；服务器指纹、诊断版本、页数和百分比不成为第二道解析门槛。安全／引擎失败不触发旧解析器、修复或在线回退。进度、书签、设置尽力恢复，缺进度可从头；SDK 无法恢复 Locator 明确报 LOCATION_RESTORE_FAILED，不改写；进度持久化失败不阻止打开／关闭。
- libmobi 公共入口是 `apps/mobile/native/mobi-core` 的 `ermao_mobi_*` ABI v1：不透明对象、串行访问、struct_size、定宽整数、UTF-8 调用方缓冲复制；稳定资源索引／名称／类型／长度及受 ERMAO_MOBI_MAX_READ_BYTES 限制的读取；目录身份用资源索引不用标题，返回稳定状态／警告。JNI、iOS wrapper、后端 adapter 可调用，UI／领域不可；后端使用前检查 ABI 版本。ABI 有界读取不等于上游流式解析，PDB/RAWML 仍受 parser 内存预算限制；分发须核对许可和实际平台证据。
- 服务端 `NormalizedPublication.toc` 仅用于详情章节投影。EnsurePublicationNavigation 解析当前已授权验证 asset，原子写导航行和按 assetId 的成功标记（含零章节）；变化／删除使缓存失效，其他 asset 不复用。失败与空目录区分，不新增队列／轮询／锁／发布协议。Reader reading order、TOC、positions 来自本地原件，不依赖服务端投影；漫画／音频索引保持格式语义，章节共用[章节核心](mobile-reader-architecture.md#统一章节核心)。
- Web 原文件存储由 Cache Storage 替换为独立 IndexedDB（2026-09-14）；旧原文件不迁移，在 API 可用时精确清理旧 Reader 缓存，首次阅读重新下载。章节与 MOBI WASM 共用不依赖 WebCrypto 的 SHA-256 校验，HTTP 不跳过校验。
- 验证慢传输未完成不打开、完整缓存不重传、截断／取消不发布、缓存删除可重建、可重排不请求远程正文章节；HTTP 使用真实非安全上下文，localhost 不作为该验证的替代。

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

- 根 package.json 为版本源，正式 tag 为 v<version>。发布前运行 pnpm release:validate（必要时 --tag），核对脚本覆盖的 Web/核心/契约/POC、Python、service worker、锁文件、Android/iOS 版本，不因宿主分工排除其他端；同步双语说明与索引，摘要有实际用户价值，不用空说明或纯自动列表。发布说明只写用户可感知的功能、修复与必要升级影响，不罗列构建 workflow、产物清单、源码版本同步或内部交付过程。
- 普通正式发布统一 fnos-package workflow（快速分支见下文），并行执行后端完整测试（含原生章节库构建与 ctest）、服务端候选镜像／应用包／FPK；仅明确选择 Android 时执行客户端检查与签名；shared signer 的 stable/beta 渠道独立密钥与包名。正式 com.ermao.library，最低 API 26，更新保持签名并递增 versionCode。私钥在仓库外生成一次并独立备份，Secrets/DPAPI 不作唯一可恢复备份，不使用 Debug/Beta 代签；RELEASE_/BETA_ 两组 KEYSTORE_BASE64、KEYSTORE_PASSWORD、KEY_ALIAS、KEY_PASSWORD 缺失即失败，密码不入命令字面或日志，PR 不拿密钥，仅发布任务可写 Release。
- 已选择 Android 时，最终 APK 经 zipalign 16KiB 对齐、签名、apksigner verify 与对齐复查后生成 SHA-256，命名 ermao-library-v<version>-android.apk。本次选中的安装包及摘要一起上传草稿，核对远端摘要后才能提升 prod/latest、公开 Release 和 feed；失败不公开部分版本。正式 tag 是唯一稳定版构建入口，禁止先在 main 手动构建候选再打 tag 重建。标签运行一次检查、构建与签名，将最终安装包保存为该运行的不可变 artifact；用户明确授权发布后，在完成相应验收和自动校验时直接执行 publish job，不要求 GitHub environment 人工审批；签名冲突卸载需用户明确授权。发布时只按 artifact ID 下载并复核原包，按构建输出的 Docker digest 推广版本／prod／latest，不重新测试、编译或签名。未通过验收不公开 Release 或推广稳定镜像；待发布镜像仅使用提交／运行／尝试号专属标签。
- Android 默认不构建。用户说“发布新版本”“发布正式版”“完整更新”、推 tag、修改移动代码／版本或上一次选择过 Android，均不构成本次授权；未选择时直接执行服务端范围，不重复询问。此规则取代历史版本白名单；历史 Release／APK 保持原样。未选择时跳过 SDK／NDK、Gradle、模拟器、签名、APK 下载／上传，产物校验拒绝混入 APK；已选择时任何构建、签名或必要检查失败、取消、异常跳过都阻止发布，不自动降级为仅服务端。Stable/Beta 只构建各自交付渠道，必要 Debug／测试 APK 限于已授权分支。
- v1.1.0 尚未正式公开，维护者于 2026-09-16 明确授权删除草稿及附件，将其标签重建到 GHCR 适配后的发布提交，并重新构建服务端镜像与 FPK；此决定取代此前保留原标签及镜像的恢复约定，仅适用于本次未发布版本。
- 自 v1.1.0 起更新清单、应用代码与依赖发布到公开 GHCR `ghcr.io/gmd170629/ermao-library-updates`，每架构一个 OCI 制品、每文件独立 blob。feed 使用 `ghcrDependencyReleases` 固定 OCI manifest 摘要，运行时匿名下载并按下述在线更新规则验证文件 SHA-256；失败不回退同名 Release 文件。Release 仅保留面向用户的安装包及摘要。公开 Release、提升稳定镜像之前必须匿名校验 GHCR 制品与所有 blob；已有同版本不同内容不得覆盖。旧部署须通过 Docker 或 FPK 手动迁移一次。
- v1.1.0 运行 `35079716004` 已完成构建、GHCR 匿名校验、镜像推广及 Release 发布，最后 feed 同步因历史 v0.5.0 仅存说明但无 Release 而失败。仅修复发布工具对已存在历史纯说明条目的处理，再同步 feed/Wiki；不重建或移动已公开的 v1.1.0 标签及产物。最新版本或曾有安装元数据的 Release 缺失仍必须失败。
- 正式提交须同步远端 main 与 develop：fetch 后优先快进；确有分叉时只合并一次，再将另一分支快进到同一提交，不来回制造合并提交、不强推、不夹带冻结后无关改动。新 tag 前两分支必须指向同一发布提交，workflow 预检强制核对 SHA 与版本。发布后的说明修订也按同样方式同步，不能只比较文件内容。已发布 tag 不移动，程序修复用补丁版本，禁止重建或覆盖已发布版本；发布步骤失败时仅重跑失败的 publish job，沿用已有 artifact ID 和镜像摘要，禁止重新运行全部成功构建。最终核对 main/develop/tag/Release/release-feed 和日期。
- Android Beta 仅在 develop 手动运行 mobile workflow 且明确勾选 `build_android` 时发布；普通 push／PR 不构建或发布 Android，仍执行后端移动契约与公共 Reader／源码检查。全部移动检查成功后签名并更新 android-beta；旧运行不覆盖新运行、失败不替换上一版。包名 com.ermao.library.beta，非调试配置，版本追加 -beta.<run_number>、versionCode=100000+run_number，重跑保持安装版本，附件以 SHA/attempt 区分，迁移不能重置计数。标签可变但不作 Latest，不进正式说明／更新源；先上传新验证附件，再更新标签／说明，最后清旧附件，后续成功运行可清中断遗留。
- 局部修复、集成与冻结 RC 按测试策略分别验证；最终 RC 满足该次完整门禁及设备证据，冻结后变化按影响重验。CI 冒烟不代替真机。
- 删除协议：卷册源文件 DELETE /api/books/{book_id}/resources/{resource_id}/source 无必需请求体，旧 confirmation 可接受但不校验名称；先部署后端再发布不发送该字段的客户端。整书删除保留 DELETE_SOURCE_FILES 固定协议值，权限、归属、幂等和范围不变，不新增迁移。


### 发布选择、并行与缓存

- `fnos-package` 保持现有 full／code-only 服务端范围，`build_android` 是本次解析结果，不维护第二份长期配置。旧 tag 无选择时为 false；手动 tag 入口 Boolean `build_android` 默认 false，显式 true 可包含 Stable Android；分支手动入口不得选择 Stable Android。reusable `mobile` 同名 Boolean 默认 false，调用方须显式传入；PR 内容不能授权 Android 或取得发布凭据。独立 `mobile` 手动入口仅构建 Beta，稳定发布必须走正式 tag。
- 自动 tag 要包含 Android 时，沿用 `release-request` schema，以 `release/requests/stable-<主版本>-<次版本>-<补丁>.json` 承载本次明确选择，`id` 与文件名一致，`targets` 包含 `android`，`android.destination` 为 `github-apk`，`versions.android` 和 `android.buildNumber` 对应本次源码。本入口只把请求中的 Android 选择接入现有服务端发布模式，不另建跨目标发布器，iOS 不走此入口。请求复用既有来源／版本／不可变历史校验；不得读取最近一次请求作为默认。
- 先冻结源码提交，填写请求的完整 `sourceCommit`，再用单独提交接纳该请求；源提交到 tag 提交只能增加这一个请求文件，其他源码、版本、构建号和说明必须已经冻结。main/develop/tag 仍同步到接纳提交，请求必须在 origin/main 获接纳且历史不可改写。发布产物始终取同一 tag 提交；其应用源码与请求冻结提交相同。没有请求的旧入口维持原有校验，不要求历史迁移。已有请求时禁止同时传手动 Boolean（包括 false），出现冲突直接失败；这种发布通过推 tag 触发，失败阶段用原运行重试。
- `validate → {backend-tests, server-package, mobile-contracts（无 Android）或 mobile-release → android-package（含 Android）} → package → publish`。服务端候选不等待 Android 或后端完整测试；最终 `package` 必须确认服务端验收成功、完整模式后端成功、公共移动契约成功及选中 Android 的全部检查／签名成功。互斥移动分支、未选择的 Android 及 code-only 不适用的检查只按本次计划跳过；选中的必要任务必须成功。各分支以当前运行 artifact ID 汇总；实际镜像验收、应用包和正式推广使用同一 digest。tag 不再另建一份 startup-acceptance 镜像，原监督进程测试保留在后端 job，实际镜像两项验收保留在服务端 job；PR／分支启动验收仍保留。
- Docker 保留 GHA 分 scope 缓存，正式 tag 另读写 `gamersgu/shuku-starship-web:buildcache-release` registry 缓存，以避免 GHA 跨 tag 可见性限制。只有串行的受信任正式 tag 候选构建可写，PR／开发分支不能写；它不是正式版本／prod／latest，也不是发布产物来源。缓存丢失仍正常冷构建。Python wheel seed 仅依赖锁文件、项目依赖描述、安装脚本及固定运行环境；业务源码、原生库和环境指纹仍在后续正确阶段生成，amd64/arm64 保持独立。
- 查看同一 Actions 运行的 job／step 时间和 selection summary，记录版本、SHA、Android 选择及原因、后端测试、镜像构建／验收、应用包与整体墙钟时间。分别说明少做 Android 的工作量、并行消除的等待、缓存命中的收益；本地缓存证据不能代替正式 Actions 的耗时／跨 tag registry 命中数据，不预先承诺节省分钟数。


### 快速应用更新（code-only）

自本规则起，正式发布支持普通和 code-only 两个长期分支；仅用户明确要求“快速发布／快速应用更新／code-only 发布”时采用后者。未指定方式仍普通发布，讨论流程或修复不构成发布授权。本条取代仅针对快速发布的不分模式镜像、安装包和移动验收要求，普通发布按上述显式目标选择执行。

- 版本索引当前条目可选 `serverUpdate`，严格包含 `mode: "code-only"`、`baseVersion`、`runtimeImage`；缺省普通模式。baseVersion 是已公开稳定祖先版本，runtimeImage 是官方仓库不可变镜像摘要。连续快速版本继承前版摘要，追溯至完整发布的镜像种子版本；构建核对实际种子版本、协议和环境指纹。
- 默认补丁版本递增，全仓版本同步和双语说明规则不变。资格由 `scripts/release-mode.mjs` 委托 `release-request.mjs` 唯一校验：允许可交付 Web/Python 应用修复和兼容调整；依赖输入、工作区包配置、补丁、迁移、契约、原生客户端功能及固定环境变更拒绝。原生版本同步字段和不交付的发布工具/文档允许变化。`ermao-library.wiki` 完全不参与发布检查：不读取或验证其内容、指针及同步状态，它与系统交付无关。新增未知构建输入默认拒绝；不得以扩大白名单掩盖真实依赖或运行时变化。
- 冻结提交后执行 `node scripts/release-mode.mjs --published-base`；main/develop/tag 对齐规则继续适用。正式 tag 触发同一 fnos-package 工作流。快速提交的镜像任务、移动任务以及 FPK 任务跳过；该版本 tag 之后的新开发提交恢复普通开发任务。
- `scripts/build-release-app-packages.sh IMAGE@DIGEST OUTPUT code-only SEED_VERSION` 在既有 AMD64/ARM64 镜像临时容器内编译 Web、组装后端，不执行 docker build、不编译固定原生库。构建依赖按锁文件安装在临时目录；pnpm 工具版本及分发摘要固定。复用协议 2 打包器核验真实 standalone 的完整依赖身份/布局、原镜像依赖种子及 blob，不允许重写依赖冒充 keep。环境指纹来自镜像，Web basePath 也必须一致。
- 交付完整应用代码与完整目标依赖清单；现有用户只下载代码及实际缺失/变化的依赖，无逐版本补丁链。独立编译若改变依赖身份即停止 code-only；不能用旧 node_modules 覆盖新产物规避检查。
- 快速最终门禁：版本与说明、资格、Web 模块检查、原失败及直接受影响行为、双架构构建及完整产物/依赖身份校验、远端完整性校验。按维护者要求，正确构建并通过这些校验后直接发布；下载更新、安装、浏览器及重启运行验收不再是快速发布门禁，不在发布流水线执行。既有候选验收工具保留为按需诊断入口，不将构建成功表述为运行验收通过。未变化移动端不构建，无关全仓回归不属于快速门禁。
- 用户明确授权后自动验证通过即发布，不设人工审批或 required reviewers 预检；发布只使用同一运行的不可变 artifact ID。先 GHCR 上传且匿名校验所有 blob，再公开 Release，最后更新 feed。快速 Release 无 APK/FPK 附件，feed 必须有两种架构的已校验 OCI 引用；发布失败复用原产物，仅恢复失败阶段，不自动重建。
- 应用实际版本与基础镜像/fnOS 版本分别记录。在线更新不推广 Docker 版本/prod/latest，不产生新的 FPK/APK/IPA；新安装使用上次完整版本再显式在线更新。后续完整发布整合修复。不新增自动安装/回滚，保留现有两阶段操作：点击下载只准备，点击立即更新后再次确认才安装；不新增下载弹窗，保留停机及失败保护。

按需诊断入口（非快速发布门禁，已有镜像，无新镜像构建）：

```sh
python3 scripts/accept_container_update.py --image IMAGE@DIGEST \
  --candidate-packages dist/application --both-architectures --browser \
  --report artifacts/startup-acceptance/code-only.json
# 连续快速版本另加 --prior-packages <已校验前版制品目录>。
# 单架构本地已有镜像可省略 --both-architectures；仅代表实际执行的架构。
```

技能入口为 `.agents/skills/ermao-release/SKILL.md`。修改技能/流水线本身不升级产品版本、不创建 tag、不发布远端产物。

维护者于 2026-09-20 明确取消快速发布的下载更新运行验收并要求重新发布 v1.2.1。该版本首次运行在 ARM64 浏览器验收超时，尚无公开 Release 或 GHCR 发布产物，且构建包未保存；允许将未发布的 v1.2.1 标签更新至移除该门禁的发布提交并重新构建应用包。已公开版本与产物仍不可覆盖。

### 在线更新的 SHA-256 校验与安装保护

- 在线更新以下载文件的 SHA-256 与发布清单预期值一致作为唯一包完整性判据；下载完成及安装前分别计算，摘要缺失、非法或不符均不得进入替换阶段。发布清单本身按更新源中的 SHA-256 校验；GHCR 按摘要地址下载 blob，不额外获取 OCI 清单进行身份或文件集合比对。
- 更新引用使用同一解析入口，存在 `oci_digest` 时保留 GHCR 类型；未知扩展字段忽略，必要下载地址、摘要、架构和安装执行信息仍需可读取。按系统/架构选包、按版本显示更新；不以环境指纹、ABI、依赖内容漂移、声明大小/展开量/文件数量或安装计划摘要进行额外准入。旧 `plan_sha256` 字段仅保留读写兼容，不影响安装资格。
- 协议 2 根据本地记录和目标清单计算依赖差异，复用现有安装器。保留的依赖不进行内容扫描；仅为实际安装的 Python 包记录安装结果，不把该记录与发行身份再比对。安装器以 applied 表示已替换并发起启动；页面确认实际运行版本，不用额外 import/uv check 探针代替。
- 管理员权限、官方来源、当前准备包与确认目标绑定、安装互斥、安全路径/解压/写入范围、固定资源上限、网络超时、取消、停机及失败保护保持。删除或覆盖不归本包所有的文件仍被禁止。安装前从已校验归档重新生成临时目录，不能使用先前已解压的旧树。文件缺失、写入/实际安装失败继续停止并记录具体阶段和公开错误码。
- 本条仅简化客户端在线更新；发布工具仍严格校验环境、完整依赖与产物布局。针对更新实现的定向集成测试不等同于重新启用快速发布的下载更新/浏览器运行门禁。
- 此变更涉及固定安装器，首次交付必须采用新版本完整镜像/fnOS 包，不能 code-only。v1.2.0 无法靠新应用包修复其安装入口，用户需通过管理界面升级一次完整版本；不要求容器内操作，不覆盖 v1.2.0/v1.2.1，未明确授权时不发布。

### 更新程序不管理数据库

维护者于 2026-09-21 明确要求：更新执行为停止旧服务、替换代码及依赖、启动服务。本条取代此前更新流程中的停机备份要求，适用于在线更新、镜像同步和旧部署转换。更新程序不连接、备份、预检数据库，也不按数据库大小预留备份空间；数据库初始化、校验与迁移由应用启动流程负责。保留安装安全校验、互斥、取消及失败记录，不自动回滚。已有备份文件和应用内手动备份恢复功能不变；`backup` 阶段仅供旧入口和历史状态读取兼容，新流程不产生该阶段。固定入口变更通过完整镜像或对应安装包交付，单独在线更新应用代码无法替换旧入口。

### 简化更新与启动链路

维护者于 2026-09-21 明确要求更新仅停止旧服务、替换代码和依赖、运行程序。启动器删除旧程序完整性、初始化标记、旧目录递归写权限、估算空间、镜像环境完全一致、安装后 uv check／额外集合扫描和启动后依赖扫描门禁。新程序来源、摘要、安全路径、协议、互斥及真实安装错误仍是替换约束。

镜像记录缺失或损坏时重新应用镜像，允许覆盖较新的在线版本；替换完成后记录镜像身份。启动器不再执行健康／版本／Worker 就绪验收或 180 秒启动超时。应用负责数据库与配置校验，进程监督保留。页面根据 applied 状态、请求绑定及实际运行版本确认结果；状态不可读但目标版本可访问时仅提醒记录不可用，不宣称包摘要已验证。页面超时不影响程序运行。

日志、状态、归档、成功记录及清理失败只提醒，不阻止启动或停止服务。更新请求与执行中标记在旧服务停止前可靠建立；不能建立则拒绝更新而保留旧服务。依赖结果记录失败时保留未完成标记，禁止后续增量更新使用旧记录；完整镜像同步修复。实际替换失败不启动已知部分替换的程序，不自动回滚。

### 更新失败后的容器重启

- 历史请求不重放，归档失败时本次仍启动应用但禁用在线安装消费。历史诊断读写失败只提醒；日志和已有数据库备份保留。
- 镜像记录有效且没有未完成替换时保留在线版本；缺失、损坏或有未完成替换时通过当前完整镜像修复后启动。旧初始化标记或旧程序不完整不得阻止安全覆盖修复。
- 此规则取代此前健康验收决定更新成功、收尾失败停止服务及旧未完成标记仅归档的规定，不增加自动数据库恢复或清空行为。固定入口变更需完整镜像或安装包交付，单独在线应用更新无效。

### ADR 0031 补充：MCP 三组六项能力（2026-09-22，已接受）

用户确认以 system:read/system:manage、books:write/shelves:write、files:upload/files:modify 替换旧细分权限。基础查询必选且不绕过账户角色；全局配置和队列／日志仅系统管理者可见，管理工具只接受固定类别字段。图书数据修改与原文件副作用保持分离；保护字段仍要求显式字段和修订版本，跨库操作仍检查两端当前范围。

旧授权不自动扩权。新增迁移保留令牌摘要与密文、授权身份与书库模式、有效期和历史任务，仅重置能力并删除旧细分选项；服务能力同步重置。新文件删除用冻结库存、隐藏暂存与持久阶段实现，源身份变化拒绝，新增文件不递归删除，索引复用导入队列。完整替换复用分块上传和原子发布，按 files:modify 重检，不增加内容编辑器。文件属性采用尽力保留，不削弱内容、路径、持久化和身份校验。
