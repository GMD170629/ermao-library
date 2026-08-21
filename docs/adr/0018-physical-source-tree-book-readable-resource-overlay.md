# ADR 0018：物理 SourceNode 树与可阅读资源导入

- 状态：Accepted
- 日期：2026-08-21
- 范围：目标数据模型、SourceNode 扫描、首次导入和显式重新导入
- 取代：[ADR 0017](0017-library-root-directory-topology.md) 的目标数据模型、
  FLAT/VOLUMES 映射、目录遍历和 scanner/importer 职责
- 修订：[ADR 0002](0002-bounded-persistent-import-work-queue.md) 的路径去重键和扫描产物；
  保留其单一有界持久队列、背压、短事务和崩溃后从根重扫原则
- 保留：[ADR 0016](0016-source-preserving-reader-publications.md) 的原始格式约束；目录资源
  的原始输入是一组真实文件，不得合成为派生出版物

## 1. 范围

本次重构只建立两件事：

1. 数据库如何表达物理路径、Book、ReadableResource 和 ResourceAsset；
2. 扫描、首次导入和用户显式重新导入如何写入这些数据。

Reader、进度、书签、API、Web、Mobile、下载、备份、OPDS、Kindle 和统计均延后设计。
后续能力使用 Book、ReadableResource 和 ResourceAsset 的稳定 ID，但具体路由、Locator、
进度所有权和下载协议不在本 ADR 决定。

本次不迁移旧数据库、不双写、不保留旧模型兼容层。目标实现从 fresh database 开始。

## 2. 核心决定

数据库分为物理层和语义层：

```text
Library
  └─ LibrarySourceNode *
       ├─ LibrarySourceNodeMetadata 0..1
       └─ LibrarySourceNodeInterpretation 0..1

LibraryBook
  └─ LibraryReadableResource *
       └─ LibraryResourceAsset *

LibraryImportRun
  ├─ ResourceCandidate 0..1
  ├─ AssetCandidate *
  └─ LibraryImportTask *
```

- SourceNode 只保存扫描时发现的路径树和观察快照；
- Book 表示图书聚合；
- ReadableResource 表示可独立打开的文件或目录型资源；
- ResourceAsset 表示 Resource 实际使用的真实常规文件；
- ImportRun 只隔离一次首次导入或重新导入的临时结果。

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

`observed*` 只是首次发现或显式重新导入时的快照，不得用于自动变化检测或决定是否重新
导入。目录的 size 为 `NULL`。

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

元数据优先级、封面选择、旁车读取和旁车写回完全沿用现有逻辑。本 ADR 只改变 owner 外键
和重新导入的临时隔离边界，不借重构修改规则。实现前用 characterization fixtures 固定
现有行为。

开启旁车文件存储时，先提交数据库，再通过既有可恢复流程把当前元数据额外落盘。任何
NAS、解析器或旁车 I/O 都不得发生在数据库事务内。

### 4.2 SourceNodeInterpretation

每个可解释节点至多一条当前解释：

- `result`: `NODE_ONLY | RESOURCE`；
- `source`: `AUTO | USER`；
- `adapterId`, `adapterVersion`，无唯一匹配时可空；
- `reasonCode`；
- 目录探测的样本路径、样本数、预算、终止原因和识别时间。

`RESOURCE` 表示该节点按当前规则建立了 ReadableResource，不等于文件已经成功解析。
是否可打开由 Resource 导入状态决定。普通扫描不会重新判断已有终态解释；重新判断等同于
用户显式重新导入。

目录节点可能在“SourceNode 已提交、探测尚未完成”之间崩溃。此时解释为空，后续扫描只需
补完这次首次判断；这不属于重新识别终态节点。

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

- `id`, `bookId`, `sourceNodeId`；
- `adapterId`, `adapterVersion`, `mediaKind`, `format`；
- `enablementState`: `ENABLED | DISABLED`；
- `importState`: `PENDING | READY | FAILED`；
- `publishedRunId`，当前可见结果集合的 ImportRun ID，可空；
- `activeImportRunId`，当前仍在导入的 ImportRun ID，可空；
- 创建和更新时间。

约束：

- `UNIQUE(sourceNodeId)`，一个节点至多锚定一个 Resource；
- Resource、Book 和锚点 SourceNode 必须属于同一 Library；
- Resource 锚点等于 Book 锚点，或位于 Book 锚点子树内；
- Resource 可锚定常规文件或目录；
- `bookId` 和 `sourceNodeId` 创建后不变；
- `enablementState` 只表达用户启停，不表达导入成功与否；
- 只有 `ENABLED + READY` 才承诺当前可打开。

`publishedRunId` 只是“当前显示哪次导入结果”的发布隔离令牌，不是文件版本，不参与扫描或
变化检测。已有 READY Resource 开始重新导入时仍保持 READY，直到新结果成功发布。

目录 Resource 在语义上是一个可独立打开的叶子对象。启用、禁用或重新导入它，只改变该
Resource 自身及其 Asset，不级联修改后代 SourceNode 或后代 Resource。

### 5.3 LibraryResourceAsset

核心字段：

- `id`, `resourceId`, `sourceNodeId`；
- `publishedRunId`；
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
- 同一关系重新导入后仍存在时保留 Asset ID，role 可以更新；
- EPUB spine、压缩包内部图片、虚拟章节等解析器内部对象不是 SourceNode 或 ResourceAsset。

读取 Resource 当前 Asset 时，只查询
`asset.publishedRunId = resource.publishedRunId AND asset.importState = READY`。重新导入发布后，
仍带旧 `publishedRunId` 的 Asset 不可见；它们只在本次遍历完成后清理，以便后来重新发现的
同一路径可以继续复用原 Asset ID。

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

## 7. 首次识别

### 7.1 常规文件

首次发现常规文件时，只把物理类型和后缀交给 file adapter registry，不打开文件：

- 无匹配或多个 adapter 匹配：保存 NODE_ONLY，只保留 SourceNode；
- 唯一匹配：原子保存 RESOURCE 解释、必要的 Book、PENDING Resource、ImportRun、候选
  PRIMARY Asset 和首个 ImportTask。

worker 在事务外真正读取并验证文件。成功后发布 Resource 和 PRIMARY Asset；失败后 Resource
变为 FAILED。普通扫描不会自动重试，用户可显式 retry 或重新导入。

### 7.2 目录的前 100 个文件探测

每次自动进入一个尚无终态解释、且不在外层目录 Resource 覆盖范围内的目录前，先执行有界
探测：

1. 使用 `os.scandir()`、`follow_symlinks=False` 和 Library 的同一 ignore 规则；
2. 按文件系统返回顺序做有界深度优先递归；
3. 目录不计数，收集遇到的前 100 个常规文件；
4. 只检查物理类型和后缀，不打开或解析文件；
5. 同时限制最大遍历项数、最大深度和最长时间；
6. 100 个样本全部属于唯一 adapter 时，立即建立目录 Resource；
7. 子树提前结束且有 1～99 个样本时，按全部实际样本作同样判断；
8. 因预算或局部 I/O 提前终止时，只要已有样本全部属于唯一 adapter，仍视为目录 Resource；
9. 无样本、无匹配或多个 adapter 冲突时保存 NODE_ONLY。

保存实际样本相对路径、样本数、adapter 版本、访问数量、深度预算、时间预算和终止原因。
文件系统顺序可能因设备而异，这是被接受且可追溯的抽样结果。探测结果一旦保存，普通扫描
不再主动探测。

探测得到的有界 entry 可由随后正式遍历复用，避免立即重复访问同一批 NAS 目录；缓存不得
超过探测预算。

### 7.3 外层截断与后续文件

目录 Resource 一旦建立：

- 整棵接纳子树仍递归建立 SourceNode；
- 当前 adapter 接受的常规文件各自创建 AssetImportTask，并逐个并入该 Resource；
- 不兼容文件只建 SourceNode；
- 后代目录不再自动执行 Resource 识别；
- 第 101 个及后续文件不改变父 Resource 的类型；
- 达到 adapter 声明的最小 READY Asset 条件即可发布 Resource，不等待完整遍历；
- 发布后的其余成功 Asset 继续加入同一个当前结果集合；个别失败不使 READY Resource 失败。

显式重新导入可以在已有目录 Resource 内或其祖先建立另一个 Resource，因此数据模型允许
范围重叠。普通扫描发现重叠范围内的新文件时，只把从 Library 根向下遇到的最外层目录
Resource 作为 automatic owner，不向多个祖先 Resource 扇出。嵌套 Resource 保留，但只有
对它显式重新导入时才吸收后来发现的路径。Resource 的 ENABLED、DISABLED、PENDING、
READY 或 FAILED 状态不改变该归属规则。

## 8. 普通扫描

一次 ScanJob 只做以下事情：

1. 从 Library 根开始有界遍历；
2. 按 `(libraryId, pathKey)` 插入尚不存在的 SourceNode；
3. 为新节点完成第 7 节的首次解释和任务创建；
4. 对目录 Resource 范围内的新兼容文件创建一次 AssetImportTask；
5. 保存有界进度和错误摘要。

普通扫描明确不做：

- 更新已有 SourceNode 的 size、mtime、observedAt 或元数据；
- 重新判断已有 NODE_ONLY/RESOURCE 解释；
- 因未看到路径而删除记录或设置 MISSING；
- 识别移动、重命名或同路径内容替换；
- 自动重试已有路径的失败导入。

扫描可补完两种尚未完成的首次状态：扫描崩溃留下的空解释，以及失败重新导入新建但尚未
形成 Asset/终态解释的 SourceNode。这只是补完第一次语义写入，不是重新探测终态路径。

目录必须先写 SourceNode，再在事务外探测。探测结束后的解释、Book/Resource、ImportRun、
首批候选与任务在一个短事务提交。常规文件的 SourceNode 与首次解释/任务在一个短事务提交。
队列水位不足时，在写入会产生任务的 SourceNode 前暂停，避免留下无任务且无法自动补偿的
节点。

扫描继续使用 ADR 0002 的单一有界持久队列、lease、heartbeat、取消、重试、背压、短事务
和崩溃后从根重扫。扫描产物从“候选文件”改为 SourceNode 与必要 ImportTask；路径去重键
改为本 ADR 的 `(libraryId, pathKey)`。取消或失败保留已经提交的节点和任务，不执行缺失推断。

## 9. 导入流程

### 9.1 ImportRun 与 ImportTask

ImportRun 表示一次首次导入、显式 retry 或显式重新导入：

- `kind`: `INITIAL | RETRY | REIMPORT | RECOVERY`；
- `state`: `PENDING | RUNNING | COMPLETED | COMPLETED_WITH_ERRORS | FAILED | CANCELLED`；
- 目标 SourceNode、可空的 Resource ID、adapter、错误摘要和 `publishedAt`；
- 每个 Resource 同时至多一个非终态 active ImportRun。

ImportTask 表示一个文件的实际读取：

- `state`: `QUEUED | RUNNING | SUCCEEDED | FAILED | CANCELLED`；
- 目标 SourceNode、Resource、可空的 owner ImportRun、role、尝试次数和错误摘要；
- `(ownerImportRunId, sourceNodeId, role)` 或普通增量任务的 `(resourceId, sourceNodeId)` 保证
  一次导入意图只创建一次。

任务租约、超时回收、自动执行重试和 WorkItem 删除沿用 ADR 0002，不在本 ADR 重建另一套
队列状态机。业务结果、Task 终态和 WorkItem ack 必须在同一个短事务提交。

### 9.2 首次导入与目录增量

- worker 在事务外读取一个真实文件并产生有界结果；
- 初始 Run 的结果先写 `ResourceCandidate`/`AssetCandidate` 临时表；
- 单文件 PRIMARY 成功，或目录候选达到 adapter 的最小 READY 条件时，执行一次短发布事务；
- 发布事务写入 Resource 当前字段和元数据、upsert 稳定 Asset、设置 Resource/Asset 的
  `publishedRunId`，并把 Resource 置为 READY；
- 目录发布后，同一 Run 的剩余成功任务直接追加到当前 `publishedRunId`；
- 完整遍历和全部任务结束仍未达到最小条件时，Resource 置为 FAILED；
- 已经 READY 后发生的遍历错误或个别 Asset 失败，只让 Run 为 COMPLETED_WITH_ERRORS。

初次目录遍历期间发现的兼容文件都归属于同一个 INITIAL Run。发布不等于 Run 已结束：达到
最小条件后可以先 READY，待目录遍历和已有任务终态后才清空 `activeImportRunId`。发布前
终止且未达到最小条件时，清空 active Run 并把新 Resource 置为 FAILED。

普通扫描为 READY 目录 Resource 发现新兼容路径时，创建不属于重新导入 Run 的增量任务。
如果 Resource 正有 active Run，该任务保持 QUEUED；active Run 终态后再按当时的
`publishedRunId` 导入，避免写入正在切换的结果。每次增量成功后重新检查 adapter 最小条件；
PENDING/FAILED 目录 Resource 可以因为一个全新兼容路径创建 RECOVERY Run 并恢复 READY，
但不得借此重新读取或重试任何已有失败路径。

### 9.3 事务与晚到任务

数据库事务内禁止 NAS、解析器和旁车 I/O。每个 worker 的顺序固定为：

1. claim 持久任务；
2. 在事务外读取并验证一个文件；
3. 打开短事务，核对任务 lease 和 Resource 的 active/published Run；
4. 写业务结果、任务终态并 ack；
5. 提交后执行需要的可恢复旁车写回。

属于 ImportRun 的结果只有在 `resource.activeImportRunId = task.ownerImportRunId` 时可提交。
普通增量结果只有在 Resource 没有 active Run 时可提交；否则保留任务等待。过期结果不得
覆盖当前数据。这里的 Run ID 仅用于事务隔离，不是 SourceNode 或文件内容版本。

## 10. 显式重新导入

“重新识别”与“重新导入”是同一个 `ReimportSourceNode` 用例。用户可以对任意已有文件或
目录 SourceNode 执行；普通扫描不会代替用户触发。

流程：

1. 创建新的 REIMPORT Run，并以 CAS 占用 Resource 的 `activeImportRunId`；节点尚无
   Resource 时，只以 SourceNode 为目标并预分配候选 Resource ID；
2. 文件重新读取格式和元数据；目录重新执行前 100 个文件探测，并有界遍历其资产范围；
3. 本次访问到的已有 SourceNode 刷新 observed 快照；新路径按正常规则 insert-if-absent；
4. 新解释、Resource 元数据和 Asset 结果只写 Run candidate tables，不修改当前稳定结果；
5. 达到最小可用条件时，用一个短事务发布：保留既有 Resource/Book ID，按
   `(resourceId, sourceNodeId)` 复用 Asset ID，更新 adapter、mediaKind、role 和元数据，
   把 Resource 与当前 Asset 的 `publishedRunId` 切到新 Run；
6. 未出现在当前已发布集合的旧 Asset 保持旧 `publishedRunId` 因而立即不可见；Run 遍历
   结束前不删除，以便后续重新发现时仍能复用 ID；
7. 发布后的其余成功 Asset 继续加入新 `publishedRunId`；Run 终态后再有界清理旧结果和
   candidate。

发布前失败、取消、无唯一 adapter，或完整遍历后仍不满足最小条件时：

- 已有 Resource、Asset、解释和元数据完全不变；
- 清空 `activeImportRunId`；尚无旧成功结果的首次 Resource 置为 FAILED；
- 只记录失败 Run/Task；
- 已实际观察到的 SourceNode 快照和新 SourceNode 可以保留；
- 这些新节点以后由普通扫描补完从未完成的首次解释/Asset 任务。

一旦第 5 步发布成功，本次重新导入即成功。之后的深层遍历错误、取消或个别 Asset 失败记为
COMPLETED_WITH_ERRORS，新 READY 结果不回滚。这是“达到最小条件即可使用”与“发布前失败
保留旧数据”的明确边界。

重新导入可以改变现有 Resource 的 adapter、mediaKind、role 和元数据，但不改变 Resource、
Book 及重合 Asset 的稳定 ID，也不改变 enablementState。对 NODE_ONLY 节点成功重新导入时
可以创建新 Resource；FLAT 同时创建 Book，VOLUMES 挂入对应根文件夹 Book。

重新导入不级联删除或改状态后代 Resource。FLAT 中显式把普通祖先目录重新导入为 Resource
时，新建祖先 Book，并保留已存在的后代 Book/Resource；这类重叠只由显式操作产生。

## 11. 删除、模式切换与根路径迁移

用户删除 SourceNode 时，删除以下数据库记录：

- 该节点及其 SourceNode 子树；
- 锚定在子树内的 Book、Resource、Asset、元数据、Run 和 Task；
- 子树外 Resource 对任一被删节点的 Asset 引用及相关任务/候选。

磁盘文件不删除。幸存 Resource 删除 Asset 后若不再满足最小 READY 条件，置为 FAILED；否则
保持 READY。磁盘路径仍存在时，未来扫描会以新 SourceNode ID 重新发现。

Library 组织模式切换不是原地转换：先删除该 Library 的全部数据库关联记录，再修改模式并
重新扫描。

Library 根路径只允许通过显式 `RelocateLibraryRoot` 修改。验证新根存在、可读且不与其他
Library 冲突后，只更新 `rootPath`；所有相对路径和 Book/Resource/Asset ID 保留。系统不自动
推断根目录移动，新根缺少文件时仍只在打开或重新导入时报告错误。

## 12. 实施路径

目标实现放在未激活的 target composition root 中。每个阶段从 fresh database 验收并保持
全仓可构建、适用测试为绿色；不允许“中间不可运行，最后统一修复”。

1. **领域与 schema**：建立 SourceNode、Interpretation、Book、Resource、Asset、ImportRun、
   candidate 和 Task；落实外键、唯一约束、删除策略和纯状态测试。
2. **扫描与分类**：实现精确路径、四种 physicalKind、FLAT/VOLUMES 编排、目录有界探测、
   外层截断、背压和崩溃补完。
3. **首个单文件闭环**：选择一个格式完成 SourceNode → Resource → PRIMARY Asset → metadata，
   验证真实队列、短事务和失败。
4. **首个目录闭环**：同一切片接入有声书目录 classifier 与 TRACK importer，覆盖前 100 个
   文件、READY 早发布、尾部追加和部分失败。
5. **其余格式**：图片目录与 PAGE importer 同切片；其余每种文件格式分别形成可验证闭环。
6. **重新导入和管理操作**：完成原子发布、ID 保留、删除、模式切换和根路径迁移。
7. **规模与最终验收**：百万节点、NAS 错误、取消、崩溃、晚到 worker、队列水位和 fresh
   baseline。

开发期可使用临时增量 schema revision。全部目标模型和导入流程稳定、首次发布前压平为
唯一 fresh baseline；baseline 发布后不可重写。

## 13. 验收矩阵

### 数据模型

- SourceNode 路径唯一、同 Library 父子、父节点类型、无环和路径一致；
- Book/Resource/Asset 不得跨 Library 或越出锚点范围；
- 一个节点至多一个 Book 和一个锚定 Resource；
- 同一 SourceNode 可以被多个 Resource 作为 Asset 引用；
- 当前 Asset 查询只看到 Resource `publishedRunId` 下的 READY 行；
- 删除节点完整清理关联记录，且不误删子树外 Resource；
- FLAT/VOLUMES 不可在已有节点时原地切换；根路径迁移保留相对身份。

### 路径和扫描

- 绝对路径、空段、`.`、`..`、NUL、字面反斜杠、大小写和 Unicode 拼写；
- pathKey 摘要碰撞保护；
- SYMLINK 环、越根链接和特殊文件不被跟随或导入；
- 重复扫描不更新已有节点，不做 missing 对账，不重试终态路径；
- 移动/重命名产生新节点，旧节点保留；
- 根离线、目录不可读、取消和崩溃不删除已有数据；
- 未完成的首次解释/任务能补完，终态解释不被重新探测；
- 百万节点内存保持 `O(depth + batch + probe budget)`，队列不超过水位。

### 目录识别与导入

- 0、1、99、100、101 个递归常规文件；
- 唯一匹配、无匹配、adapter 冲突、最大深度、预算和局部 I/O；
- 提前终止但已有样本唯一匹配时建立 Resource；无样本或冲突时 NODE_ONLY；
- 探测不读取文件内容，保存完整判断证据；
- 父 Resource 后代全部建 Node，只给兼容文件建 Asset，不自动建后代 Resource/Book；
- 重叠范围内普通新文件只归最外层 Resource；
- 达到最小 READY 条件即发布，尾部 Asset 增量加入，单项失败不回滚 READY；
- 文件 I/O 不占数据库事务，Task 结果与 ack 同事务；
- 过期 worker 不覆盖 active/published Run。

### 重新导入

- 任意文件或目录节点均可重新导入；
- 发布前失败完整保留旧 Resource、Asset、解释和元数据；
- 发布成功保留 Resource/Book/重合 Asset ID，并原子切换当前集合；
- adapter、mediaKind 和 role 可以更新；
- 发布后错误为 COMPLETED_WITH_ERRORS，当前结果不回滚；
- 失败 reimport 新建的 SourceNode 可由后续扫描补完首次语义；
- 普通扫描不会因 size、mtime 或内容变化自动触发重新导入。

## 14. 明确不做

- 旧数据库迁移、回填、双写和兼容层；
- LibraryVersion、Edition 或固定中间目录业务层；
- `AUDIOBOOK` 组织模式；
- 自动文件变化检测、MISSING 对账、移动/重命名识别和自动删除；
- 自动重新识别终态目录或自动重试失败路径；
- 修改元数据优先级和旁车行为；
- Reader/API/Web/Mobile 等上层契约；
- 派生 EPUB、ZIP、目录打包、持久解包或把压缩包内部内容建成 SourceNode/Asset。

## 15. 结果

该模型只保留一棵物理路径快照和一层可阅读语义。普通扫描只发现新路径，不承担文件同步；
用户要刷新已有路径时显式重新导入。目录通过前 100 个递归常规文件快速建立 Resource，达到
最小有效 Asset 条件即可使用，剩余文件独立追加。

代价是旧路径可能长期保留，并在实际打开时才报告不存在或不可读；目录类型也受文件系统
枚举顺序和有限样本影响。系统通过保存判断证据、禁止隐式重判以及提供显式重新导入，让
这些取舍保持简单且可解释。

## 实施进度

非规范性实施台账。本节不改变上文规范。阶段 1A/1B 与阶段 2～6 目标实现已落地；
阶段 7A（运行时验收修复）已完成门禁记录；阶段 7B（baseline/激活决策）仍未完成。
target composition root 可独立构造，但尚未接入生产启动路径。

### 阶段 1A：SourceNode 纯领域基础 — 已完成

- 实现：`apps/api-python/app/modules/library/domain/source_nodes.py`
  - `SourceNodePhysicalKind`：`REGULAR_FILE | DIRECTORY | SYMLINK | OTHER`
  - `SourceNodeRelativePath` 与 `pathKey = v1:SHA-256(UTF-8(relativePath))`
  - 相对路径校验：保留大小写与 Unicode 拼写；不把 `\` 转为 `/`；拒绝空串、绝对路径、空段、`.`、`..`、NUL、Windows drive/UNC
  - 直接父子树不变量与 `PATH_KEY_COLLISION` 占用规则
  - 违规码：`INVALID_RELATIVE_PATH`、`PATH_KEY_COLLISION`、`CROSS_LIBRARY_PARENT`、`PARENT_NOT_DIRECTORY`、`PARENT_PATH_MISMATCH`、`SELF_PARENT`
- 测试：`apps/api-python/tests/unit/modules/library/test_source_nodes.py`
- 明确未接入：ORM、迁移、扫描、导入、API、Web 或运行时 composition root；本批不激活任何新运行时路径。

#### 8141b45 初版门禁（Codex 独立确认）

- 聚焦：`test_source_nodes.py` + `test_capability_architecture.py` → **64 passed**
- 全量：`uv run --no-sync pytest -q` → **6 failed, 926 passed**
- 同 6 个失败 node ID 在父 commit `83ae8d5` 上单独复跑仍为 6 failed，故为 1A 之前既有失败
- Ruff：`uv run --no-sync ruff …` 在 no-sync 环境不可用（未安装、未改依赖）

#### 审查修复（本批，在 8141b45 之后）

- 封闭：`SourceNodeRelativePath` 构造器经 `__post_init__` 自校验；非法路径抛出
  `InvalidSourceNodeRelativePathError`（稳定 `INVALID_RELATIVE_PATH` code + 原始 `relative_path`）
- `parse_source_node_relative_path` 仍对非法输入返回 `SourceNodeViolation`、不抛异常；与构造器共用同一套校验
- `pathKey` 仅由已验证的 `SourceNodeRelativePath.path_key` 提供；移除接受裸 `str` 的公共 pathKey 入口
- `evaluate_path_key_occupancy` 仅接受已验证的 `SourceNodeRelativePath`
- 验证命令与结果（于 `apps/api-python`）：
  - `uv run --no-sync pytest -q tests/unit/modules/library/test_source_nodes.py` → **47 passed**
  - `uv run --no-sync pytest -q tests/unit/modules/library/test_source_nodes.py tests/test_capability_architecture.py` → **80 passed**
  - `uv run --no-sync python -m compileall -q app/modules/library/domain/source_nodes.py` → 成功
  - 手工行宽：两个修改过的 Python 文件均无超过 88 字符的行
  - `uv run --no-sync pytest -q` → **6 failed, 942 passed**（同既有 6 失败；通过数含新增单测）
  - `uv run --no-sync ruff format --check …` / `ruff check …` → **不可用**（`Failed to spawn: ruff`；未安装依赖）

### 阶段 1B：目标 ORM schema — 已完成结构修复，等待最终统一验证

- 实现（未接入运行时读写）：
  - `apps/api-python/app/modules/library/infrastructure/readable_resource_schema.py`
    - 表：`LibrarySourceNode`、`LibrarySourceNodeMetadata`、`LibrarySourceNodeInterpretation`、
      `LibraryBook`、`LibraryBookMetadata`、`LibraryReadableResource`、
      `LibraryReadableResourceMetadata`、`LibraryResourceAsset`、`LibraryResourceAssetMetadata`
  - `apps/api-python/app/modules/imports/infrastructure/readable_resource_import_schema.py`
    - 表：`LibraryImportRun`、`ResourceCandidate`、`AssetCandidate`、`LibraryImportTask`
  - 注册：`apps/api-python/app/models/__init__.py`（仅 import 注册，无双写/兼容服务）
  - 迁移：`apps/api-python/app/db/alembic/versions/0003_readable_resource_overlay_schema.py`
    - `down_revision = "0002_version_covers"`；临时增量 revision，目标导入流稳定后才压平 fresh baseline
    - **结构修复**：0003 改为 migration-local immutable schema（本地 `MetaData`/`Table` + typed CHECK；
      逐表 `Table.create` / 逆序 `drop`）；禁止依赖运行期模型包或 declarative registry
  - ORM：全部 20 个 `CheckConstraint` 已改为 typed SQLAlchemy expressions（`column`/`and_`/`or_`/`func`/`in_` 等）
  - 防回归：`tests/test_capability_architecture.py` 增加 0003 自包含与 typed CHECK 静态守卫
- 关键约束（库可表达部分）：
  - SourceNode `(libraryId, pathKey)` 唯一；`pathKey` 长度 67 且 `v1:` 前缀；`physicalKind` CHECK
  - 同 Library 父子复合 FK；`parentPhysicalKind` shadow + DIRECTORY 复合 FK；parent 成对 CHECK；禁止直接 self-parent
  - DIRECTORY 的 `observedSizeBytes` 必须 NULL，其它类型非负
  - Book / Resource `sourceNodeId` 唯一且同 Library 复合 FK
  - Asset `(resourceId, sourceNodeId)` 唯一；`sourceNodePhysicalKind` shadow 强制 REGULAR_FILE
  - enablement / import / run / task / role 状态 CHECK
  - Resource `activeImportRunId` 部分唯一；ImportRun 每 Resource 至多一个非终态 run
  - ImportTask run-owned `(ownerImportRunId, sourceNodeId, role)` 与增量 `(resourceId, sourceNodeId)` 部分唯一
  - 当前 published Asset 组合索引；candidate 与稳定行隔离
- Shadow 列理由：`parentPhysicalKind`、`sourceNodePhysicalKind`（及实体上的 `libraryId`）仅服务 SQLite 复合 FK/CHECK，不进入领域/API DTO
- 应用层保留：父路径一致性、跨层级子树范围、无环（超出直接 self-parent）
- Legacy：`LibraryWork` / `LibraryVersion` / `LibraryVolume` / `LibraryFile` 暂时保留，无双写
- 测试代码已写、**本批未执行 pytest / Ruff / smoke**（速度优先，等待阶段 7 统一验证）：
  - `tests/integration/modules/library/test_readable_resource_schema.py`
  - `tests/test_sqlite_database.py`
  - `tests/test_capability_architecture.py`（新增守卫）
- 明确未接入：API、scanner、worker、composition root 读写路径

### 阶段 2：扫描与分类 — 实现完成，等待阶段 7 验证

- 实现：
  - `app/modules/imports/application/readable_resource/scan_source_tree.py` — `ScanLibrarySourceTree`
  - `app/modules/imports/infrastructure/readable_resource/filesystem.py` — `OsSourceTreeFilesystem`
    （`os.scandir`、`follow_symlinks=False`、有界目录探测、路径防穿越/symlink escape）
  - `app/modules/imports/domain/directory_probe.py` — 前 100 样本与终止原因决策
  - `app/modules/library/domain/organization_modes.py` / `book_placement.py` — FLAT/VOLUMES（无 AUDIOBOOK）
  - `app/modules/imports/domain/resource_adapters.py` — 后缀匹配（发现期不打开文件内容）
- 行为覆盖：有界 DFS、insert-if-absent、`PATH_KEY_COLLISION`、终态解释不重判、空解释补完、
  外层目录 Resource 截断、队列水位背压、探测证据落库
- **本批未运行 pytest / Ruff / migration / smoke**；仅 `compileall` + `git diff --check`
- target composition root **尚未激活**到生产 API/router/worker

### 阶段 3：单文件导入闭环 — 实现完成，等待阶段 7 验证

- 实现：
  - `app/modules/imports/application/readable_resource/process_import_task.py`
  - `app/modules/imports/domain/import_run_policies.py` — INITIAL/RETRY/REIMPORT/RECOVERY 与 CAS 提交规则
  - `app/modules/imports/infrastructure/readable_resource/work_queue.py` — 与 ADR 0002 `ImportWorkItem` 协调
  - `app/modules/library/infrastructure/persistence/source_tree_repository.py` — ORM 仓储（flush-only）
- 行为覆盖：claim/lease/ack、事务外读文件、candidate、PRIMARY 发布、late worker 互斥、
  业务结果与 WorkItem ack 同短事务、提交后 sidecar 调度钩子
- Adapter：EPUB / PDF / TXT / Kindle / comic-archive / audio-file（经 adapter 端口包装既有解析器）

### 阶段 4：目录有声书 / TRACK 闭环 — 实现完成，等待阶段 7 验证

- Adapter：`audiobook-directory`（TRACK）；探测唯一音频后缀 → 目录 Resource；样本与后续兼容文件入队
- 最小 READY 条件满足后发布；尾部 Asset 继续追加；个别失败不回滚 READY

### 阶段 5：图片目录 / PAGE 与其余现有格式 — 实现完成，等待阶段 7 验证

- Adapter：`image-directory`（PAGE）；文件侧 EPUB/PDF/TXT/Kindle/comic/audio 均已接入 registry
- 约束：不创建派生 EPUB/ZIP/持久解包目录；压缩包内部对象不成 SourceNode/Asset

### 阶段 6：重新导入与管理操作 — 实现完成，等待阶段 7 验证

- 用例：
  - `ReimportSourceNode` / `RetryReadableResourceImport`
    （`app/modules/imports/application/readable_resource/reimport.py`）
  - `DeleteSourceNode` / `ChangeLibraryOrganizationMode` / `RelocateLibraryRoot` /
    `EnableReadableResource` / `DisableReadableResource`
    （`app/modules/library/application/commands/manage_source_tree.py`）
- 行为覆盖：activeImportRunId CAS、candidate 隔离、发布前失败保留旧结果、删除子树与跨 Resource Asset 清理、
  模式切换先删目标关联再改模式、根路径仅更新 `rootPath`

### Target composition root — 已构造，未激活

- 入口：`apps/api-python/app/bootstrap/readable_resource_pipeline.py`
  - `build_readable_resource_pipeline(session)`
  - `build_readable_resource_worker(pipeline)` → `ReadableResourceWorkerProcessor`
    （实现位于 `imports/infrastructure/readable_resource/worker.py`）
- **未**注册到现有生产 API / router / worker 启动路径

### 阶段 7A：运行时验收修复 — 本批完成实现与门禁（非“阶段 7 完成”）

**修复的真实问题：**

1. ORM flush 顺序：为 SourceNode→Book/Run→Resource→candidate/Task→Asset 补齐 relationship /
   `foreign_keys` / `post_update` / `overlaps`，同一事务插入对象图不再 FOREIGN KEY failed
2. 能力边界：`ScanLibrarySourceTree` 与 `SqlAlchemyImportRunRepository` 迁入 imports；
   library 持久化端口迁至 `library/application/source_tree_ports.py` 并由 `library.public` 导出；
   `AdapterIdentity` 解除 library→imports.domain 耦合；架构回归禁止 peer 深导入
3. 短事务：`release_before_io` + `transaction()`；scandir/probe/parse 时 Session 不在活动事务；
   提交后才 sidecar；异常路径 rollback
4. 队列：`ClaimedWork` 不可变 DTO；overlay SQL 预过滤；精确 `work_item_id` ack/heartbeat/lease CAS；
   晚到 worker 不得写结果
5. 发布隔离：run-owned 结果先写 candidate；达最小 READY 才原子切 `publishedRunId`；
   reimport 不写旧 published 集合；CAS 失败 Run→FAILED；目录单项失败不提前终结 Run
6. 流式扫描：`iter_directory_entries` Iterator；probe 循环内预算；百万合成流式测试

**新增测试矩阵（节选）：**

- domain：directory probe、adapter 匹配、Run 策略、FLAT/VOLUMES、READY 条件
- application：短事务扫描、publish 隔离、reimport/retry CAS、manage 用例
- infrastructure：流式 scandir / 百万条目不物化、路径 escape
- integration：schema 全绿、单文件/有声书 TRACK/图片 PAGE、claim/late lease
- architecture：跨能力深导入守卫；bootstrap 不直接 rollback

**本批实际运行命令与结果（于 `apps/api-python`）：**

- `.venv/bin/pytest -q tests/unit/modules/imports tests/unit/modules/library/test_book_placement.py tests/unit/modules/library/test_readable_resource_states.py tests/unit/modules/library/test_manage_source_tree.py tests/unit/modules/library/test_source_nodes.py tests/integration/modules/library/test_readable_resource_schema.py tests/integration/modules/imports tests/test_capability_architecture.py tests/test_sqlite_database.py` → **261 passed**
- `.venv/bin/pytest -q` 全量 → **6 failed, 1030 passed**（仅既有 6 项；无新增失败）
- `.venv/bin/python -m compileall -q app tests` → 成功
- 仓库根 `git diff --check` → 成功
- Ruff：不可用（环境未安装 ruff；未改依赖锁）

**明确未完成：**

- 阶段 7B：fresh baseline 压平 0001～0003、是否激活 target composition root 的产品决策
- target composition root **仍未激活**到生产启动路径
- 不得将本批记为“阶段 7 完成”

### 阶段 7B — 未完成

- baseline 压平与激活决策；规模验收收尾
