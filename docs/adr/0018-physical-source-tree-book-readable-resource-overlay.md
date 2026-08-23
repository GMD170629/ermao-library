# ADR 0018：物理 SourceNode 树与可阅读资源导入

- 状态：Accepted
- 日期：2026-08-21
- 范围：目标数据模型、SourceNode 扫描、统一「继续导入」
- 取代：[ADR 0017](0017-library-root-directory-topology.md) 的目标数据模型、
  FLAT/VOLUMES 映射、目录遍历和 scanner/importer 职责
- 修订：[ADR 0002](0002-bounded-persistent-import-work-queue.md) 对本 target importer 的适用范围
  （见第 9 节）；ADR 0002 的复杂持久队列仅属于当前 legacy production importer
- 保留：[ADR 0016](0016-source-preserving-reader-publications.md) 的原始格式约束；目录资源
  的原始输入是一组真实文件，不得合成为派生出版物

## 1. 范围

本次重构只建立两件事：

1. 数据库如何表达物理路径、Book、ReadableResource 和 ResourceAsset；
2. 统一的继续导入（ContinueImport）如何扫描、识别并写入这些数据。

Reader、进度、书签、API、Web、Mobile、下载、备份、OPDS、Kindle 和统计均延后设计。
后续能力使用 Book、ReadableResource 和 ResourceAsset 的稳定 ID，但具体路由、Locator、
进度所有权和下载协议不在本 ADR 决定。

本次不迁移旧数据库、不双写、不保留旧模型兼容层。目标实现从 fresh database 开始。

产品模型明确变更（不是局部优化）：

- 重新导入 = 继续导入
- 重新识别 = 继续导入
- 首次导入也是同一套继续导入逻辑
- 目标只有一个消费者，严格按顺序处理任务
- 失败不自动恢复、不自动重试、不自动接管
- 用户再次执行「继续导入」即可
- 接受中断或失败留下的部分 SourceNode、Resource、Asset
- 代码和数据模型以尽可能简单、一致为最高优先级

## 2. 核心决定

数据库分为物理层和语义层：

```text
Library
  └─ LibrarySourceNode
       ├─ LibrarySourceNodeMetadata
       └─ LibrarySourceNodeInterpretation

LibraryBook
  └─ LibraryReadableResource
       └─ LibraryResourceAsset

LibraryImportTask
```

- SourceNode 只保存扫描时发现的路径树和观察快照；
- Book 表示图书聚合；
- ReadableResource 表示可独立打开的文件或目录型资源；
- ResourceAsset 表示 Resource 实际使用的真实常规文件；
- LibraryImportTask 是唯一队列表，由单一消费者顺序处理。

从目标模型彻底删除：

- LibraryImportRun、ResourceCandidate、AssetCandidate
- activeImportRunId、publishedRunId、ownerImportRunId、discoveryComplete
- Run kind/state、原子候选发布、旧发布集合切换、晚到 worker
- CAS、lease、heartbeat、fencing token、自动接管、自动重试、retry/backoff
- cancellation 状态机、WorkItem bridge
- 「重新导入」「重新识别」「retry」三个不同用例

目标只保留 10 张表：

1. LibrarySourceNode
2. LibrarySourceNodeMetadata
3. LibrarySourceNodeInterpretation
4. LibraryBook
5. LibraryBookMetadata
6. LibraryReadableResource
7. LibraryReadableResourceMetadata
8. LibraryResourceAsset
9. LibraryResourceAssetMetadata
10. LibraryImportTask

删除 `LibraryVersion`。原 `LibraryVolume` 的业务位置由 ReadableResource 取代，原
`LibraryFile` 的物理输入关系由 ResourceAsset 取代。

SourceNode 不是文件系统的实时镜像。系统不自动检测文件修改、移动、重命名、删除或
不可读状态，不维护 `sourceRevision`、fingerprint、内容哈希、MISSING 或
`lastSeenScanId`。打开路径时发现不存在或无法读取，只向调用方报告错误，不回写节点状态。

## 3. LibrarySourceNode

### 3.1 字段

核心字段：

- `id`, `libraryId`, `parentId`；
- `relativePath`, `pathKey`, `name`；
- `physicalKind`: `REGULAR_FILE | DIRECTORY | SYMLINK | OTHER`；
- `observedSizeBytes`, `observedMtimeNs`, `observedAt`；
- `createdAt`, `updatedAt`。

`observed*` 只是首次发现时的快照。继续导入不更新已有 SourceNode 的 observed 字段。
目录的 size 为 `NULL`。

SourceNode 主表不保存展示标题、封面、排序、文件角色、格式解释、导入状态或用户选择。

### 3.2 路径身份

SourceNode 的身份是 Library 内的精确相对路径槽位：

- `relativePath` 保留枚举得到的名称组件，只用 `/` 连接组件；
- 不做大小写折叠，不做 Unicode NFC/NFD 归一化；
- 拒绝绝对路径、空路径段、`.`、`..` 和 NUL；
- `pathKey = v1:SHA-256(UTF-8(relativePath))`；
- `UNIQUE(libraryId, pathKey)`；
- 摘要相同仍比较原始路径；原路径不同时以 `PATH_KEY_COLLISION` 拒绝整个写入。

大小写或 Unicode 拼写变化、移动、重命名都会产生新 SourceNode。系统不自动迁移、合并或
删除旧节点。

### 3.3 树约束

- `parentId` 必须属于同一 Library，并指向 DIRECTORY；
- SourceNode 树不得成环，节点路径必须与父路径一致；
- Library 根目录本身不建 SourceNode；根下节点的 `parentId` 为 `NULL`；
- 未被 ignore 规则排除的目录、常规文件、符号链接和特殊文件都建立节点；
- SYMLINK 使用 `follow_symlinks=False`，只记录、不跟随、不导入；
- socket、device、FIFO 等记为 OTHER，不参与资源识别。

能由复合外键、唯一约束和 CHECK 表达的同 Library 与类型约束必须落入数据库；无环和父路径
一致性由应用规则及集成测试保证。

## 4. 元数据与解释

### 4.1 元数据

SourceNode、Book、ReadableResource 和 ResourceAsset 分别使用自己的元数据表。书架、标签、
分面等成员关系继续使用独立关系表，不折叠进单行元数据。

元数据优先级、封面选择、旁车读取和旁车写回完全沿用现有逻辑。本 ADR 只改变 owner 外键，
不借重构修改规则。实现前用 characterization fixtures 固定现有行为。

开启旁车文件存储时：先提交 Resource/Asset；再调用现有旁车公开端口；旁车失败只记录日志，
不回滚成功导入；用户再次继续导入时可再次触发。不得用 `touch_updated_at` 冒充旁车持久队列。
任何 NAS、解析器或旁车 I/O 都不得发生在数据库事务内。

### 4.2 SourceNodeInterpretation

每个可解释节点至多一条当前解释：

- `result`: `NODE_ONLY | RESOURCE`；
- `source`: `AUTO | USER`；
- `adapterId`, `adapterVersion`，无唯一匹配时可空；
- `reasonCode`；
- 目录探测的样本路径、样本数、预算、终止原因和识别时间。

`RESOURCE` 表示该节点按当前规则建立了 ReadableResource，不等于文件已经成功解析。
是否可打开由 Resource 导入状态决定。

已有 RESOURCE 解释固定使用当前 adapter；继续导入只补充兼容 Asset，不切换 adapter。
NODE_ONLY 节点在用户执行继续导入时允许再次探测并变成 Resource。空解释（崩溃留下）由
继续导入补完首次判断。

## 5. Book、ReadableResource 与 ResourceAsset

### 5.1 LibraryBook

核心字段：`id`, `libraryId`, `sourceNodeId`。

- `UNIQUE(sourceNodeId)`；
- Book 与锚点 SourceNode 必须属于同一 Library；
- `sourceNodeId` 创建后不可改变；
- 标题、作者、简介、系列和封面等保存在 `LibraryBookMetadata`。

Book 不复制 SourceNode 子树，也不保存 Version。

### 5.2 LibraryReadableResource

核心字段：

- `id`, `libraryId`, `bookId`, `sourceNodeId`；
- `adapterId`, `adapterVersion`, `mediaKind`, `format`；
- `enablementState`: `ENABLED | DISABLED`；
- `importState`: `PENDING | READY | FAILED`；
- 创建和更新时间。

约束：

- `UNIQUE(sourceNodeId)`，一个节点至多锚定一个 Resource；
- Resource、Book 和锚点 SourceNode 必须属于同一 Library；
- Resource 锚点等于 Book 锚点，或位于 Book 锚点子树内；
- Resource 可锚定常规文件或目录；
- `bookId` 和 `sourceNodeId` 创建后不变；
- `enablementState` 只表达用户启停，不表达导入成功与否；
- 只有 `ENABLED + READY` 才承诺当前可打开。

不存在 `publishedRunId` / `activeImportRunId`。当前 Asset 查询为：
`resourceId` 匹配且 `importState = READY`。

Resource 拥有至少一个 READY Asset 后直接置为 READY。已经 READY 的 Resource 不因其他
文件失败而回滚。没有任何 READY Asset 时可置 FAILED。

目录 Resource 在语义上是一个可独立打开的叶子对象。启用、禁用或继续导入它，只改变该
Resource 自身及其 Asset，不级联修改后代 SourceNode 或后代 Resource。

### 5.3 LibraryResourceAsset

核心字段：

- `id`, `libraryId`, `resourceId`, `sourceNodeId`；
- `role`: `PRIMARY | TRACK | PAGE | SIDECAR | SUPPLEMENT`；
- `importState`: `PENDING | READY | FAILED`；
- `sequenceIndex`, `sortKey`、技术元数据和失败原因；
- 创建和更新时间。

约束：

- `UNIQUE(resourceId, sourceNodeId)`；
- Asset、Resource 和 SourceNode 必须属于同一 Library；
- Asset 的 SourceNode 必须是 REGULAR_FILE；
- 文件型 Resource 的 PRIMARY 必须指向 Resource 自身节点；
- 目录型 Resource 的 Asset 必须位于 Resource 锚点子树内；
- 同一个 SourceNode 可以被不同 Resource 引用；
- 同一关系继续导入后仍存在时保留 Asset ID，role 可以更新；
- EPUB spine、压缩包内部图片、虚拟章节等解析器内部对象不是 SourceNode 或 ResourceAsset。

Asset 排序继续使用现有自然路径排序和元数据覆盖规则，最终必须形成稳定总序。

## 6. Library 组织模式

Library 只保留 `FLAT | VOLUMES`。删除 `AUDIOBOOK`；有声书、图片目录漫画和其他目录型
出版物都由 Resource adapter 识别。FLAT 与 VOLUMES 使用完全相同的文件和目录识别规则。

### 6.1 FLAT

- 任意深度的每个自动识别 Resource 独立形成一本 Book；
- 文件型和目录型 Resource 使用同一规则；
- 目录被识别为 Resource 后，后代仍建 SourceNode，但不再自动识别后代 Resource 或 Book；
- NODE_ONLY 目录继续递归，后代 Resource 各自形成 Book。

### 6.2 VOLUMES

- Library 根下的常规文件 Resource 各自形成单文件 Book；
- 根下文件夹一经发现就建立 Book，允许空 Book；
- 根文件夹内任意深度的 Resource 都归属该 Book；
- 根文件夹本身也可以同时是 Book 和目录 Resource 的锚点；
- 普通中间目录只是 SourceNode 导航容器。

Library 已存在 SourceNode 时，不允许原地切换 FLAT/VOLUMES。切换必须先删除该 Library 的
全部关联数据库记录，再修改模式并重新扫描；磁盘文件不删除。

## 7. ContinueImport / 继续导入

统一概念只有一个：ContinueImport。入口使用显式 target 类型，不使用布尔 mode flag：

- `ContinueLibraryImport(library_id)`
- `ContinueSourceImport(source_node_id)`

两种入口共享同一套扫描、识别、补齐逻辑。不保留 Reimport / Retry / 重新识别作为别名。

### 7.1 统一语义

1. 扫描并插入尚不存在的 SourceNode；
2. 对尚未形成 Resource 的节点再次尝试识别；
3. 对已有 Resource 发现尚未导入的兼容文件；
4. 把不存在任务或上次 FAILED 的文件重新放入队列；
5. 已 SUCCEEDED 的文件不重复处理；
6. 成功一项就直接 upsert ResourceAsset；
7. Resource 拥有至少一个 READY Asset 后直接置为 READY；
8. 某项失败只把该任务置为 FAILED；
9. 已经 READY 的 Resource 不因其他文件失败而回滚；
10. 用户再次执行继续导入时补齐失败项和新文件；
11. 不承诺失败前完全保留旧快照；允许部分成功；
12. 已识别的 Resource 固定使用当前 adapter，继续导入只补充兼容 Asset；
13. NODE_ONLY 节点执行继续导入时允许再次探测并变成 Resource；
14. 不自动删除未再次发现的 SourceNode/Asset；
15. 不检测移动、重命名或同路径内容变化。

### 7.2 ContinueLibraryImport

- 流式扫描 Library 根；
- 插入新 SourceNode；
- 已有 SourceNode 不更新 observed；
- 识别尚未解释的新节点；
- 对 NODE_ONLY 节点再次探测（用户明确执行继续导入）；
- 已有 RESOURCE 解释不改变 adapter；
- 为缺失或 FAILED 的兼容 Asset 创建/重置 IMPORT_ASSET 任务；
- SUCCEEDED Asset 任务跳过；
- 不删除旧节点、不做 missing 对账。

### 7.3 ContinueSourceImport

- 文件节点：识别或继续其 Resource/PRIMARY Asset；
- 目录节点：重新流式遍历子树，插入新节点并补齐当前 adapter 接受的 TRACK/PAGE；
- NODE_ONLY 目录允许重新执行前 100 文件探测并变成 Resource；
- 已有 Resource 不切换 adapter，只继续当前 adapter；
- 第 101 个及后续兼容文件同样补齐；
- 不创建重复 Book/Resource/Asset；
- 不生成针对 DIRECTORY/SYMLINK/OTHER 的 IMPORT_ASSET 任务。

### 7.4 首次识别规则（仍属继续导入）

常规文件：只把物理类型和后缀交给 file adapter registry，不打开文件。

- 无匹配或多个 adapter 匹配：保存 NODE_ONLY；
- 唯一匹配：保存 RESOURCE 解释、必要的 Book、PENDING Resource，并创建 PRIMARY 的
  IMPORT_ASSET 任务。

目录：前 100 个常规文件探测（`os.scandir`、`follow_symlinks=False`、有界 DFS）：

1. 收集前 100 个常规文件，只检查物理类型和后缀；
2. 限制最大遍历项数、最大深度和最长时间；
3. 100 个样本全部属于唯一 adapter 时建立目录 Resource；
4. 子树提前结束且有 1～99 个样本时，按全部实际样本作同样判断；
5. 因预算或局部 I/O 提前终止时，只要已有样本全部属于唯一 adapter，仍视为目录 Resource；
6. 无样本、无匹配或多个 adapter 冲突时保存 NODE_ONLY。

目录 Resource 一旦建立：

- 整棵接纳子树仍递归建立 SourceNode；
- 当前 adapter 接受的常规文件各自创建 IMPORT_ASSET；
- 不兼容文件只建 SourceNode；
- 后代目录不再自动执行 Resource 识别；
- 第 101 个及后续文件不改变父 Resource 的类型；
- 重叠范围内普通新文件只归最外层目录 Resource。

## 8. LibraryImportTask 与单消费者队列

### 8.1 任务字段

LibraryImportTask 是唯一队列表，只表达：

- `kind`: `SCAN_LIBRARY | CONTINUE_SOURCE | IMPORT_ASSET`
- `libraryId`
- `resourceId`（仅 IMPORT_ASSET）
- `sourceNodeId`（CONTINUE_SOURCE / IMPORT_ASSET）
- `role`（仅 IMPORT_ASSET）
- `state`: `QUEUED | RUNNING | SUCCEEDED | FAILED`
- `errorSummary`
- `createdAt` / `startedAt` / `finishedAt`

不要增加：owner、lease、expiry、attempts/retry policy、priority、availableAt、
heartbeat、claim version、fencing token、Run ID、candidate ID。

### 8.2 消费流程

明确只支持一个消费者。不为误启动多个 worker 增加任何竞争保护机制。

1. 唯一 worker 取 `createdAt` 最早的 QUEUED 任务；
2. 在短事务中改为 RUNNING；
3. 提交；
4. 在事务外执行扫描或文件解析；
5. 成功后短事务写业务结果并置 SUCCEEDED；
6. 失败后 rollback 业务写入，再用短事务置 FAILED；
7. 继续消费下一条。

worker 启动时：

- 所有遗留 RUNNING 任务直接改为 FAILED；
- `errorSummary` 使用稳定代码 `WORKER_INTERRUPTED`；
- 不自动重新入队；
- 用户执行继续导入时才重新排队。

用户再次 ContinueImport 时：对相关 FAILED 任务重置为 QUEUED（统一实现，不保留两套
retry 语义）。

### 8.3 IMPORT_ASSET 直接写稳定结果

- 事务外解析一个真实文件；
- 成功后短事务直接 upsert 稳定 ResourceAsset；
- 复用 `(resourceId, sourceNodeId)` 已有 Asset ID；
- 写入 role、状态、排序和技术元数据；
- Resource 至少有一个 READY Asset 后置为 READY；
- 标记任务 SUCCEEDED；
- 不经过 candidate 或 publishedRunId。

失败时：

- 任务置 FAILED；
- 对应 Asset upsert 为 FAILED（一致规则）；
- Resource 没有任何 READY Asset 时可置 FAILED；
- Resource 已 READY 时保持 READY；
- 不清理其他成功 Asset；
- 不自动重试。

### 8.4 扫描与内存

保留：

- `os.scandir`、`follow_symlinks=False`、流式 DFS；
- 内存 `O(depth + probe budget)`；
- 前 100 个文件目录探测；
- FLAT / VOLUMES；
- 外层目录 Resource 截断；
- 路径 traversal/symlink escape 防护；
- 文件系统 I/O 和解析器不在数据库事务内；
- 数据库写入使用短事务；
- pathKey 唯一与碰撞保护。

删除：

- queue high-water 背压、扫描切片恢复、scan heartbeat/cancellation/lease/claim；
- 晚到 scan worker、discovery completion barrier。

扫描任务执行到成功或失败为止。进程崩溃后任务在下次启动被标记 FAILED，用户重新执行。

## 9. 对 ADR 0002 的范围修订

- ADR 0002 的复杂持久队列（lease、heartbeat、恢复、取消、优先级、WorkItem bridge）
  只属于当前 legacy production importer；
- 本 ADR 的 target importer 不继承这些机制；
- 最终切换到 target importer 后，legacy queue 随 legacy importer 删除。

ADR 0002 历史正文保留；其状态/范围说明同步标注上述修订。

## 10. 删除、模式切换与根路径迁移

用户删除 SourceNode 时，删除以下数据库记录：

- 该节点及其 SourceNode 子树；
- 锚定在子树内的 Book、Resource、Asset、元数据和 Task；
- 子树外 Resource 对任一被删节点的 Asset 引用及相关任务。

磁盘文件不删除。幸存 Resource 删除 Asset 后若不再有 READY Asset，置为 FAILED；否则
保持 READY。磁盘路径仍存在时，未来继续导入会以新 SourceNode ID 重新发现。

Library 组织模式切换不是原地转换：先删除该 Library 的全部数据库关联记录，再修改模式并
重新扫描。

Library 根路径只允许通过显式 `RelocateLibraryRoot` 修改。验证新根存在、可读且不与其他
Library 冲突后，只更新 `rootPath`；所有相对路径和 Book/Resource/Asset ID 保留。

## 11. 实施路径

目标实现最初在独立 composition root 中构造，并由 ADR 0019 完成生产切换。每个阶段从
fresh database 验收并保持全仓可构建、适用测试为绿色。

Alembic 已压平为唯一 fresh-install baseline
（`0001_library_topology_baseline`，含 version covers 与 ADR 0018 overlay 表）。
不支持从已删除的开发期 revision（原 `0002` / `0003`）升级；baseline 发布后不可重写。

## 12. 验收矩阵

### 数据模型

- SourceNode 路径唯一、同 Library 父子、父节点类型、无环和路径一致；
- Book/Resource/Asset 不得跨 Library 或越出锚点范围；
- 一个节点至多一个 Book 和一个锚定 Resource；
- 同一 SourceNode 可以被多个 Resource 作为 Asset 引用；
- 当前 Asset 查询只看到 `importState = READY`；
- 删除节点完整清理关联记录；
- FLAT/VOLUMES 不可在已有节点时原地切换；根路径迁移保留相对身份。

### 继续导入

- 单消费者按 createdAt 顺序处理；
- 启动时 RUNNING → FAILED / `WORKER_INTERRUPTED`；
- 失败不自动重试；用户 ContinueImport 后 FAILED → QUEUED；
- SUCCEEDED 不重复执行；
- 重复 ContinueImport 不重复 Book/Resource/Asset；
- NODE_ONLY 后新增兼容文件，再 ContinueImport 可变成 Resource；
- 目录新增第 101 个及后续文件可继续补齐；
- 单项失败不影响其他成功 Asset；READY Resource 在后续文件失败时保持 READY；
- 无 lease/heartbeat/fencing/Run/candidate/WorkItem bridge；
- 文件解析期间无数据库事务；
- EPUB/PDF/TXT/Kindle/comic/audio/TRACK/PAGE adapter 边界仍通过；
- 百万合成目录输入不整体物化。

### 路径和扫描

- 绝对路径、空段、`.`、`..`、NUL、字面反斜杠、大小写和 Unicode 拼写；
- pathKey 摘要碰撞保护；
- SYMLINK 环、越根链接和特殊文件不被跟随或导入；
- 不更新已有节点 observed，不做 missing 对账；
- 移动/重命名产生新节点，旧节点保留；
- 百万节点内存保持 `O(depth + probe budget)`。

## 13. 明确不做

- 旧数据库迁移、回填、双写和兼容层；
- LibraryVersion、Edition 或固定中间目录业务层；
- `AUDIOBOOK` 组织模式；
- 自动文件变化检测、MISSING 对账、移动/重命名识别和自动删除；
- 自动重试失败路径、lease/CAS/多消费者保护；
- 修改元数据优先级和旁车内容规则；
- Reader/API/Web 等上层契约由 ADR 0019 决定；Mobile 仍不在本批范围；
- 派生 EPUB、ZIP、目录打包、持久解包或把压缩包内部内容建成 SourceNode/Asset；
- ADR 0018 本身不决定生产切换；实际激活由 ADR 0019 完成。

## 14. 结果

该模型只保留一棵物理路径快照、一层可阅读语义，以及一张简单任务表。继续导入是发现、
识别与补齐的唯一用户意图。部分成功被接受；失败由用户再次继续导入补齐。

代价是旧路径可能长期保留，并在实际打开时才报告不存在或不可读；目录类型也受文件系统
枚举顺序和有限样本影响。系统通过保存判断证据、固定已识别 adapter，以及提供统一的
继续导入，让这些取舍保持简单且可解释。

## 实施进度

非规范性实施台账。本节不改变上文规范。

### 当前状态（ADR 0019 切换完成后）

- 生产 composition root 已接入 `ContinueImport`、`ScanSourceTree`、
  `ProcessReadableResourceImportTask` 与简单 `LibraryImportTask` 单消费者队列；
- legacy importer、Run/candidate/lease/heartbeat/fencing/WorkItem bridge、自动 retry 与旧队列
  控制入口已从生产路径删除；
- Library、Reader、Publication、Media、Metadata、Organize、Kindle、Backup、OPDS、System、
  Web 与 reader-core 已由 ADR 0019 切换到 Book/ReadableResource/ResourceAsset 身份；
- fresh baseline 仅保留 `0001_library_topology_baseline`，不提供旧数据升级或兼容接口；
- Mobile 未纳入本次实现和验收。

### 最终后端验证（2026-08-22，于 `apps/api-python`）

- `ruff format --check .` → **560 files already formatted**；
- `ruff check .` → **All checks passed**；
- `mypy app` → **411 source files, no issues**；
- `python -m compileall -q app tests` → exit 0；
- 使用仓库固定源码编译的 MOBI runtime 执行 `pytest -q --tb=short` →
  **851 passed in 431.80s**；
- 事务、架构、OpenAPI、授权、备份、导入、Reader 与 schema 守卫包含在上述完整套件中。
