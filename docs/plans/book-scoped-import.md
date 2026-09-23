# Book 范围导入：本次修改边界与验收口径

状态：执行边界已拟定，Book 生产路径已接入并处于迁移验收中；M0～M7 均未整体通过。计划基线为 `develop@39a26298c444b99b0c77a851fa012d4bcb2aeba0`，执行时以实际 HEAD 和工作区为准，不覆盖已有改动。

本文依据维护者本次提出的 Book 范围导入目标，约束本次工作。桌面版执行计划提供候选步骤与检查项，并非已通过的证据；现行行为、已接受 ADR、工程规范和真实调用链用于核对实现。若其旧调度规则与本次明确目标冲突，先逐条标出并在切换生产流程时更新权威文档，不能让旧规则暗中保留第二条生产链。

## 唯一目标与工作单元

将现有单消费者导入链收敛为“发现必要边界 → 合并本书请求 → 领取本书任务 → 扫描必要范围 → 处理变化资源 → 本地识别／收尾 → 持久化完成或明确失败”。Book 是状态与完成判定的责任边界，本次变化集合是文件与解析工作范围；不能把一本书等同于每次全量重扫。Book 尚不存在时，以稳定源节点锚点登记待处理单元；未知分类目录先发现边界，不强行创建 Book。

完成结果须有 1 千、1 万、10 万条真实 Book 关系的数据规模证据，最终通过 M7 的功能、恢复、升级、客户端契约及发布门禁。M7 的“可发布”只表示门禁证据齐备，不等于已获授权打 tag、推送、公开 Release 或触碰生产。

## 允许改动的职责与条件

| 职责 | 本次允许的最小改动 | 不得扩展成 |
| --- | --- | --- |
| Imports 任务与 Worker | 演进现有 `LibraryImportTask` 队列、状态和请求合并；本书阶段、持久版本、有限退避；单消费者直接推进本书；移除普通每轮全局识别就绪搜索 | Job/Run/Step/Dependency 多套模型、第二消费者、全局依赖图、无界重试 |
| 发现和扫描 | 复用 `RequestLibraryScan`、现有目录探测和 `book_placement`；只枚举必要范围，保存完整性；已确定 Book 可在后续全库发现结束前处理 | 新文件组织规则、目录 mtime 代替完整枚举、每本书全库重扫 |
| 资源处理与导航 | 从现有资源用例提取唯一可直接调用的处理步骤；复用格式适配器、成功版本、资产批次和封面发布；局部修正导航 SQL 批量大小并保持一次替换的原子性 | 第二套解析／资产保存、半份可见导航、提高 SQL 预算 |
| Library 投影 | 只改本次链上的 Book 完成判定、直接 `book_id` 归属、资源／导航投影和人工字段保护所需位置 | Book/Resource/Asset 身份重建、阅读定位或 Reader 引擎改造 |
| 数据库与升级 | 仅为唯一生命周期补必要列、索引和新增迁移；分页升级旧未完成任务与扫描缺口；保留已成功数据和引用 | 改写已发布迁移、全库强制重导、普通 worker 每轮全库升级 |
| 真实入口与展示 | 迁移已存在的扫描、继续、重新识别、文件变更、上传、自动化／MCP、移动／删除入口及任务状态消费者；仅在既有契约确受影响时改相应适配 | 顺手改版 UI、重建所有客户端、扩大授权或增加导入开关 |

具体文件应沿真实调用链定位，不把计划中列出的路径当成必须全部修改的清单。跨能力调用仍走公开 API／应用端口；装配根只负责接线。可共享规则只保留一个实现；替换时同步迁移范围内调用方并删除旧生产接线，历史数据读取和升级所需类型可保留。

## M0：当前入口与状态消费者核对

以下路径均相对 `apps/api-python`。它们说明本次必须迁移或验证的真实调用方，不表示每个文件都需要修改。

| 现有入口／消费者 | 现行调用链 | 本次去向或边界 |
| --- | --- | --- |
| 手动扫描、书库启用 | `app/modules/imports/presentation/writes.py`、`presentation/http.py` → `ContinueImport`／`RequestLibraryScan` | 继续用原授权入口登记发现范围；发现确定 Book 后登记本书请求 |
| 启动、周期、watcher | `app/bootstrap/library_scan_runtime.py` → `RequestLibraryScan`，`app/modules/imports/infrastructure/library_scan_watcher.py` 只收集变化 | 保留合并窗口与持久扫描范围；已确定 Book 可被单消费者领取，不等整个全库发现结束 |
| 继续目录或旧失败任务 | `presentation/writes.py` → `app/modules/imports/application/readable_resource/continue_import.py` | 已知 Book 进入本书待办；未知边界走局部发现；旧任务 ID 指向唯一新待办，`force` 只失效对应资源成功版本 |
| 普通上传、自动化／MCP 附件 | `presentation/writes.py`、`app/modules/imports/infrastructure/automation_uploads.py` → 局部扫描 | 保持原文件保存与导入结果分离，复用同一发现和本书请求，不增加上传专用导入消费者 |
| 文件移动、删除 | `app/bootstrap/file_moves.py` → 队列 `reconcile_relocation`；`app/modules/imports/infrastructure/deletion_index.py` → 父目录扫描 | 仅处理旧、新归属及必要扫描缺口；保持文件互斥、索引更新和删除保护 |
| 自动整理中的显式本地识别 | `app/bootstrap/organize.py` → `SqlAlchemyBookIdentificationRequests.request` | 进入同一 Book 的本地识别待办，不借资源解析任务重跑媒体；联网整理仍归原能力 |
| 扫描发现资源变化 | `app/modules/imports/application/readable_resource/scan_source_tree.py` → `request_import_resource` | 确定归属后直接合并本书变化；Book 尚未建立时保留源节点锚点 |
| 后台识别 | `app/modules/imports/infrastructure/readable_resource/worker.py` → `prepare_book_identifications` → `IDENTIFY_BOOK` | M4 后由本书阶段直接推进，普通每轮不搜索全库待识别 Book |
| 任务列表／详情／继续 | `app/modules/imports/infrastructure/library_queries.py`、`presentation/http.py`、`presentation/writes.py` | 保留既有授权、反枚举和稳定响应；历史任务可查询、继续映射到新待办 |
| Book 详情与自动整理状态 | `app/modules/library/infrastructure/books.py`、`app/modules/metadata/infrastructure/lookup_queue.py` | `metadataPending`／`metadataState` 等展示与等待语义从唯一任务事实投影，不能再独立决定调度 |
| 封面显式重生成 | `app/modules/library/application/local_cover_regeneration.py` | 现有独立命令保留；仅其与导入状态的实际交互纳入本次，不改整套封面工具 |

当前没有独立的公开“取消单条导入任务”HTTP 入口；取消和清理由书库／源节点删除、任务被替换等现有操作触发。M7 验证这些实际路径，不凭执行计划增加一个未经需求确认的新接口。OPF／引用封面文件变化经既有 watcher 或扫描观察进入局部请求；元数据文件写回自身仍属 Metadata，不因本次改造复制写回管线。

### 状态唯一归属

- 发现任务只拥有待枚举范围及完成／缺口事实；未完整枚举的范围保留 `LibraryImportScanGap` 语义，不能由任务清理或迁移伪造完成。
- Book 待办拥有本书请求合并、阶段、执行版本、有限重试时间和最终状态。现有任务 `QUEUED/RUNNING/SUCCEEDED/FAILED` 可继续表示调度事实；`metadataPending`、`metadataState` 及列表状态只能是兼容投影，不能成为另一个可独立领取或完成的所有者。
- 资源处理步骤拥有 Resource／Asset 结果及成功来源版本；本书流程决定父任务是否进入本地识别或留下部分失败。解析、资产批次、导航和封面仍复用原实现。
- 本地识别复用 `IdentifyImportedBook` 与原字段保护。提交前只核对本书存在、本次版本、取消、字段和策略变化；失效结果不覆盖新请求。

最小持久化变更须先对照现有 `LibraryImportTask` 的 `sourceNodeId`、`resourceId`、`scanScopes`、`rerunRequested`、`bookMetadataRevision` 和 `LibraryBookMetadata` 的修订字段逐项确定用途；只补缺失的 Book 锚点／阶段／请求与执行代次／退避事实，不同时新建 Job、Run、Step、Dependency、Counter。处理中合并的新请求必须与当前执行快照分开保存，阶段让出或进程重启后仍可重建；仅有内存标志不符合此约束。

### M2 前需落实的最小持久化契约

沿用 `LibraryImportTask`，新增一种 Book 处理 kind；`SCAN_LIBRARY` 与必要的 `CONTINUE_SOURCE` 仍是发现任务，旧 `IMPORT_RESOURCE`／`IDENTIFY_BOOK` 只供升级与历史查询。尚无 Book 的稳定源节点由发现任务定位；现有扫描在确认资源时调用 `ensure_book`，因此只有建立了 Book 才登记 Book 行，其 `bookId` 非空、`sourceNodeId` 指向 Book 锚点，同一 Book 仅一条当前行。FLAT 分类目录仍是发现范围，不因其目录节点存在而创建 Book。现有 `state`、`errorSummary`、`createdAt`／`startedAt`／`finishedAt` 表示调度事实；`LibraryBookMetadata.importRevision`／`processedRevision` 只用于本地元数据输入版本与提交保护。若后续真实入口证明这一顺序无法覆盖，先记录反例，再在发现职责内作最小修正。

拟新增列须逐一对应以下不可由现有列安全承担的事实，最终名称在迁移实现时与模型同步：

| 事实 | 唯一用途 |
| --- | --- |
| `bookId` | Book 行的直接归属与局部查询；建立 Book 前的锚点归发现任务，不制造半成品 Book 行 |
| `phase` | 当前 Book 工作的扫描、资源、识别／收尾阶段；阶段最后一批结果同事务推进 |
| `requestVersion`、`executionVersion` | 分别表示已登记请求与本次固定快照；完成用条件更新拒绝清除处理中新增请求 |
| 有界 `bookWork` | 保存当前与后续两组变化范围及原因；运行中请求只并入后续组，已知资源按 ID、未知路径按必要扫描范围登记，过多离散范围可提升到本书并记录原因 |
| `resourceCursor` | 大本书在资源边界让出和重启时从尚未完成处继续；资源内沿用已提交资产成功版本跳过有效批次 |
| `retryCount`、`nextAttemptAt` | 有限任务级退避与到期领取；重试耗尽保留可见失败，不占住其他 Book |
| `supersededByTaskId` | 旧未完成任务 ID 迁至唯一 Book 行后的继续／详情映射；历史结果仍保留，不把失败伪装成功 |

扫描的大目录另外只允许在 `LibrarySourceNode` 增加一枚“本次完整枚举的见证代次”字段，用于按父节点分批找出缺失项；它不表示 Book 调度状态，也不替代已有扫描缺口。现有 `observedAt` 仅在节点内容变化时更新，不能安全地兼任此标记。先使用已有父节点索引，只有实测单条查询超预算才增加针对性索引。

`bookWork` 只保存本书内有界请求，不存整个书库清单；其编码、范围合并与输入校验须在单一应用契约中定义，数据库领取不得解析 JSON 路径作全局依赖判定。新 Book 行按 `bookId` 唯一并按 `state`／`nextAttemptAt` 索引领取；`resourceCursor` 只在当前执行版本内有效。仅当实现证明已有列可无歧义承担上述某项事实时，才删去对应新列，不额外建立同义 flag 或计数器。

### 历史升级映射与恢复

- 已成功历史任务与成功资产版本不改写。`IMPORT_RESOURCE` 未完成行以 Resource 的直接 `bookId` 归并；`IDENTIFY_BOOK` 以源节点找到 Book；旧 `IMPORT_ASSET` 如仍未完成，先按其 Resource 归属处理。多个旧任务归一 Book 时，旧 ID 保留查询与继续去向，新生产消费者只领取 Book 行。
- `SCAN_LIBRARY`／`CONTINUE_SOURCE` 未完成范围及 `LibraryImportScanGap` 仍由发现层恢复；失败或未枚举范围不能迁移成扫描成功。`metadataPending` 但无任务的 Book 产生本地识别待办；失败识别保留失败和继续语义。
- 升级遍历有界分页、可重入：先落新 Book 行，再写旧行映射；唯一锚点和条件更新使重复进入不复制待办。迁移／恢复门禁未完成时消费者不领取任务。映射不到真实 Book 或资源的旧失败保持可见诊断与人工继续边界，不能自动改为成功或触发全库重导。
- 旧执行在升级前须停止；M4 接线只保留一个生产消费者。终态写入失败时以已提交资源／元数据版本补终态，不重新解析或发布文件副作用。
- 旧任务 `state` 留作历史事实；映射后的旧排队／运行／失败行不能再次被消费者领取。旧 ID 的详情和继续先解析 `supersededByTaskId`，向客户端返回唯一当前 Book 待办及其真实状态；列表只显示当前待办和未映射的有效历史项，避免一项工作出现两个可操作行。映射不到 Book 的旧失败保留原状态与原因，人工继续只定位明确源范围。此投影仍需在 M4 用现有 API 契约和授权测试验证。

## 必须保留的行为

- SourceNode、Book、Resource、Asset 稳定身份，成功资源版本、阅读进度／书签、受保护人工字段与封面。
- FLAT／VOLUMES 及现有合法深层布局，单文件、多卷、图片目录、有声书、原有格式解析和排序。
- 文件路径及符号链接安全、actor／资源授权、文件移动／写回互斥、取消、过期结果拒绝、失败诊断与双语既有契约。
- 扫描范围完整才清理缺失项；失败目录、断连和未枚举路径不当作删除。文件解析与 I/O 在短写事务外，已提交有效批次在恢复时复用。
- 一项资源失败不撤销其他有效结果；本书不能因此虚报全成功，失败项可按明确入口继续。处理中新增变化保留下一轮待办。

## 分批交付与进入下一批的条件

| 批次 | 只解决的问题 | 进入下一批前的证据 |
| --- | --- | --- |
| M0 | 核对所有真实入口、状态所有者、旧 ADR 冲突；冻结本书阶段、升级映射和规模口径 | 简洁契约、入口去向和旧路径一次有预算的复现；不改生产行为 |
| M1 | 提取唯一资源步骤并修有界、原子导航写入 | 受影响格式、失败回滚和资源续处理的定向测试 |
| M2 | 最小 Book 生命周期和历史任务升级 | 请求合并／版本竞态、重启恢复及旧库升级测试 |
| M3 | 有界发现及所有触发入口转译 | FLAT／VOLUMES 增删改移、扫描缺口和无关 Book 隔离 |
| M4 | 一次性切换真实 API、装配、Worker 与状态消费者 | 真实入口到详情／Reader 的单链路；旧生产消费者不可达 |
| M5 | 预算异常、取消、进程中断与部分失败恢复 | 真实 SQLite、关键提交窗口和至少一次测试进程终止 |
| M6 | 以实测定位 10 万 Book 下当前瓶颈 | 三种规模的固定口径数据、执行计划、内存与文件访问证据；达标即停 |
| M7 | 冻结候选 SHA，做综合与发布门禁验收 | 各必需项通过或明确未通过／未执行，不继承历史结果 |

M1～M3 的准备代码不作为独立可发布版本；M4 才统一切换生产入口。任一批出现具体失败，只修该失败及直接受影响消费者。没有证据不得扩大为全仓重构、全平台回归或另建性能／监控平台。

## 冻结的规模与通过标准

规模库分别含 1 千、1 万、10 万条实际 Book 及其真实关系，加入无关成功历史、失败、未到重试期任务和未完成扫描范围。同一本书、同样文件、同一代码和依赖、固定环境下，至少五次暖缓存等价待处理快照取中位数，另记冷启动。夹具建立和正常队列等待不计入本书执行时间。分别记录领取、局部扫描、解析、保存、识别、收尾，以及 SQL 调用／批次、写提交、文件访问、执行计划和峰值内存。

沿用每条 SQL 的 2 秒预算，不以放宽预算、扩大连接池或增加 worker 达标。领取和完成判定各自满足热缓存 `T(10万) ≤ 2 × T(1千) + 20ms` 的计划目标；阈值是本次候选验收口径，并非已有结果。若 M0 证明测试环境使该阈值不可判定，须在实现前记录依据并冻结修订，不能在 M7 事后改口径。全库发现总时长可以随实际枚举规模增长；正常任务领取、单本处理、内存、事务及每轮补偿须有界，不能靠 `LIMIT` 的返回行数推断查询代价。

M0 旧路径最小复现（2026-09-23，当前 HEAD，macOS arm64，锁定的 Python 开发环境，临时 SQLite 库）：插入 1,000 条 SourceNode／Book／BookMetadata 关系和每本一条排队中的 `CONTINUE_SOURCE`，调用一次 `BookImportCompletion.prepare_ready()`；返回 0 条可识别 Book，单次约 167.5ms，1 次 SELECT。`EXPLAIN QUERY PLAN` 显示扫描 `LibraryBook`，并对每本执行相关子查询，其中有按 `libraryId` 搜索活动任务和 `json_each` 虚拟表检查。此样本只证明旧路径在该分布下逐本判定，既非新流程结果，也不是 10 万本性能或冷／暖中位数。既有 `test_book_import_completion.py` 与 `test_import_task_query_scaling.py` 在该基线下共 11 项通过；后者覆盖 10 万条任务列表查询，不代表 10 万本导入验收。

M7 还必须证明：无变化零媒体重解析；一卷变化仅处理该卷；不读无关 Book 内容；正常 worker 不运行全局 `prepare_ready` 或跨书路径依赖推导；大导航写入有界且原子；变化请求、失败扫描、取消及升级恢复不丢任务、不误删、不重复发布；一坏书不阻塞另一好书；旧库升级保留用户身份与数据。真实 API→Worker→详情→Reader bootstrap／manifest 以及任务继续／取消、进度／书签契约必须有当前候选版本证据。

## 现行决策冲突与发布边界

[扫描与导入 ADR](../architecture-decisions.md#扫描与导入) 已随 Book 生产链切换修订：旧 `IMPORT_RESOURCE`／`IDENTIFY_BOOK` 只用于升级映射、历史查询和必要失败记录；普通 Worker 不再执行全局识别准备。扫描安全、成功版本、文件互斥、身份与 Reader 契约仍有效。

本次预计包含数据库迁移，因此不适用 code-only 快速发布。M7 按现行[发布与版本决策](../architecture-decisions.md#发布与版本)、[工程规范](../engineering-standards.md)和[测试策略](../testing/test-execution-policy.md)完成普通服务端范围的版本、迁移、构建、运行及发布前检查；Android 仅按本次明确选择规则纳入。真实用户库只在另获数据使用授权后，用一致性备份副本和脱敏日志验证；缺少真实 NAS／用户数据时，只能报告本地工程验收结果。回退须配套旧应用、数据库和封面／存储备份，不能只回退镜像。

API QueuePool 与非法年份报告仅核验其真实日志、堆栈和复现。只有确认属于本次导入链的具体缺陷，才在现有职责位置作局部修复；否则记录为独立发现，不因时间相近推断因果。

## 当前执行状态（2026-09-23）

以下是本次工作区的局部证据，不替代 M7 综合验收。基线 HEAD 为 `39a26298c444b99b0c77a851fa012d4bcb2aeba0`；原有 Backup／Web 改动不属于本目标，不覆盖、不计入导入验收。M0～M7 尚未整体签收。

- **M1 资源与导航。** `ProcessReadableResourceImportTask.process_resource` 直接接受 Book 上下文并复用现有解析、资产、封面和版本管线；旧入口仅委托同一处理步骤。导航插入每条最多 50 行且整体事务仍原子，125 条目录在第二条插入故障时回滚恢复旧目录。EPUB、PDF、CBZ、图片、有声书的直接受影响样例已覆盖。
- **M2 生命周期与升级。** 原 `LibraryImportTask` 新增唯一 Book 行、阶段、请求／执行版本、当前／后续工作、资源游标和有限退避；0030／0031 新迁移分页映射旧未完成任务，旧 ID 可查询并继续到当前 Book。0032 只增加扫描观察见证列。迁移测试覆盖 205 条跨页映射、再次运行幂等和旧版列形状；十万级升级与进程中断重入见下方 M5／M6 证据。
- **M3 扫描。** 根目录及 FLAT 分类目录按至多 200 项读取、核对、提交；完整枚举后按见证代次分页清理缺失项，不完整或取消不清理。根目录和 FLAT 分类目录的 201 本样例均证明第 201 项读取前已有 Book 成功；VOLUMES Book 和整目录 Resource 仍在本书完整枚举后收尾。2000 张图片首扫为 168 次数据库驱动调用，未变化复扫为 83 次；未变化媒体不解析。十万条真实文件路径的根目录扫描实测见 M6；极多侧写文件仍未单独量化。
- **M4 生产接线。** 扫描、继续、显式本地识别已登记唯一 Book 待办；Worker 先领取 Book、按阶段直接处理变化 Resource 并本地识别，普通领取只消费发现任务。单书超过 128 个 Resource 持久化游标并让出；129 卷样例分两轮完成。目录 Book 受持久缺口阻挡，文件 Book 可独立推进；旧全局识别候选查询及建任务接口已删除。Book 终态写失败可只补终态。Imports 集成与单元定向回归为 `537 passed`，相关旧任务断言已迁移；混合 VOLUMES 真媒体样例已走扫描、Book Worker、详情、Reader bootstrap 和资产 URL。上传进度查询也已改为识别当前 Book 任务，并排除已映射的旧资源／识别任务；其所属集成文件 `25 passed`。客户端与最终候选状态投影仍待统一验收。
- **M5 故障。** 测试子进程在 Book 领取提交后以 `os._exit(23)` 终止，重启将同一行和当前工作快照重新排队并领取。十万本旧库升级探针还在 0031 首条 Book 迁移写入后强制退出子进程，再由新进程升至 0032；原 Book／SourceNode／Resource／Asset 数量、抽样 ID 和成功版本、旧任务状态、扫描缺口均保留。主循环只把 SQLite 锁忙或带 `time_budget_exceeded` 标记的语句超时视为可退避恢复；普通 `interrupted` 和伪装锁忙的非 SQLite 异常不误判。资产批次、封面发布、扫描提交和识别提交各窗口仍需结合已有真实事务测试逐项核对。
- **M6 初测。** 临时 SQLite 库分别包含 1 千／1 万／10 万条 SourceNode、Book、BookMetadata、Resource 真实关系，并混入历史成功／失败、未到期 Book 任务和覆盖 5% 较早排队 Book 的扫描缺口。相同 EPUB 与等价待处理快照各运行一次新连接及五次暖缓存；无其他负载时单本完整 Worker 暖缓存中位数依次约 `22.41 / 24.17 / 37.16 ms`，目标均形成资产。领取中位数约 `2.21 / 3.38 / 17.67 ms`；完成判定约 `0.58 / 0.59 / 0.59 ms`，均低于冻结的 `2 × T(1千) + 20ms` 门槛。十万本时 Worker 内领取／资源处理（含解析与保存）／本地识别／终态分别约 `19.87 / 10.14 / 5.47 / 1.21 ms`；其中解析与保存合计约 `9.44 ms`，不将嵌套阶段相加当总耗时。单本执行在三个规模均为 79 次 SQL 驱动调用、其中 62 次 SELECT、9 次连接提交；另一次独立测量的 Python 追踪内存峰值约 1.7 MiB，目标 EPUB 打开 3 次，对任何其他 EPUB 打开直接报错。领取使用 `LibraryImportTask_book_runnable_idx`，但较早的受阻 Book 越多，仍需检查更多缺口候选。可用 `PYTHONPATH=apps/api-python apps/api-python/.venv/bin/python -m tests.support.book_scope_scale_probe` 复跑。另一个旧版 0030 临时库包含十万套 Book／SourceNode／Resource／READY Asset，1% 旧任务混合排队／失败／中断／成功、0.1% 本地元数据待识别；0031 写入后强制退出再升级至 0032 约 `0.98 s`，Python 追踪峰值约 `1.55 MiB`，十万条 Asset 成功版本与抽样身份保留，可用 `PYTHONPATH=apps/api-python apps/api-python/.venv/bin/python -m tests.support.book_scope_upgrade_probe --books 100000 --kill-during-upgrade` 复跑。另以十万条实际文件路径进行本地根目录扫描与完整 Book Worker 排空：路径生成约 `22.06 s`，扫描约 `307.05 s`，扫描完成前已有 `500` 个 READY Asset；排空约 `1350.82 s`，最终 `100000/100000` Book 任务成功、`100000` 个 Asset 入库，进程峰值 RSS 约 `118.82 MiB`，库文件约 `628.57 MiB`。可用 `PYTHONPATH=apps/api-python apps/api-python/.venv/bin/python -m tests.support.book_scope_root_probe --books 100000 --drain` 复跑。该目录探针以十万条硬链接指向同一有效 EPUB，只覆盖本地文件系统路径规模与完整导入链；本书局部扫描单独耗时、真正冷数据、不同媒体内容及真实 NAS／用户库仍无证据。
- **M7 当前门禁。** 隔离候选只包含本次 Book 导入及直接消费者改动，后端全量回归为 `2559 passed / 3 skipped`，用时 `361.84 s`；原工作区另含 3 项无关备份测试，合计 `2562 passed / 3 skipped`。隔离候选的 Web `522/522` 单测、完整 lint、类型检查、双语目录检查和生产构建均通过。原工作区完整 lint 曾扫入已有的临时 Next 构建文件而失败；单独尝试的 Web E2E 在更新设置页遇到既有过期文案断言，非导入范围，也不属于现行正式发布工作流的 Web 门禁，本次不改。iOS 两处改动通过 Swift 语法解析，但无签名配置和真机，不能算安装／运行验收；Android 未被选择发布且本机缺 SDK。隔离候选的 v1.4.2 版本字段、锁文件及双语说明已通过 `pnpm release:validate`，但尚未冻结候选 SHA，也未通过服务端镜像构建／运行门禁（本机 Docker daemon 未运行）。真实 NAS／用户库尚无本次验收数据。

M7 静态接线核对：生产 Worker 只领取 Book 和发现任务；`prepare_ready` 已不在普通循环。旧 `IMPORT_RESOURCE`／`IDENTIFY_BOOK` 引用用于升级映射、历史详情／继续及旧数据兼容判断；`scan_gating` 仍供显式识别保护和查询投影，不是逐轮全库候选搜索。`metadataPending` 保留为元数据展示及提交保护字段，不独立领取任务。此分类不替代最终真实入口验收。

本地验收环境为 `Darwin 25.6.0 arm64`、Python `3.11.15`、锁定的依赖及临时 SQLite 库；分支基线为 `39a26298c444b99b0c77a851fa012d4bcb2aeba0`。隔离候选在 `apps/api-python` 使用同一锁定虚拟环境，设置 `ERMAO_CHAPTER_CORE_LIBRARY` 指向已构建且源码未改动的原生章节库后运行全量 `pytest -q`。首次未设置该路径的运行有 30 项章节库加载失败、2529 项通过；补齐环境后同一候选全量通过。Web 已运行 `pnpm --filter @shuku/web lint`、`typecheck`、`test`、`i18n:check` 和 `build`。规模和升级探针的复跑命令及样例分布见 M6。fnOS 模板预检在本机失败于安装脚本测试：目标 Linux 脚本调用 GNU `realpath -e`，macOS 的 `realpath` 不支持此参数；改用规范临时目录后仍同样失败，需在 Linux 发布环境验证。候选镜像及故障边界运行、iOS 真机、真实 NAS／用户库验证仍未执行；不能把本地硬链接探针继承为这些结果。迁移回退必须先停止写入，恢复匹配的旧应用、数据库和封面／存储备份；恢复旧备份后，升级期间新增数据可能丢失。

M7 必须按本文件的冻结矩阵核对真实入口、升级、故障恢复、规模、Reader／客户端、发布前门禁和回退。当前没有真实 NAS／用户数据库副本的授权或数据，不能声称真实环境事故已验证修复，也不自动发布。
