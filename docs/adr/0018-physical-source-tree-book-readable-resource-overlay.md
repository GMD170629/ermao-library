# ADR 0018：物理资源树与 Book/ReadableResource 语义覆盖

- 状态：Accepted
- 日期：2026-08-21
- 取代：[ADR 0017](0017-library-root-directory-topology.md) 中固定的 `Work -> Version -> Volume` 目录映射
- 继续遵循：[ADR 0002](0002-bounded-persistent-import-work-queue.md) 的有界持久导入队列
- 继续遵循：[ADR 0016](0016-source-preserving-reader-publications.md) 的原始格式阅读约束

## 背景与审计结论

当前图书导入以 `LibraryWork -> LibraryVersion -> LibraryVolume -> LibraryFile`
表达图书结构。多卷模式把根目录下文件夹视为 Work、直接子文件夹视为
Version，更深层目录无法自然映射；与此同时，Version 已不能筛选、不承担稳定的
媒体类别或版本差异语义，却仍出现在数据库、导入、阅读器、API 和 Web UI 的大量
路径中。

本次代码审计确认：继续保留 Version，或把任意目录继续强制映射成
Work/Version/Volume，只会把文件系统层级偶然性固化为业务规则。最终架构采用两套
职责清楚、可以独立演化的模型：

1. `LibrarySourceNode` 完整记录图书馆根目录下的物理文件树；
2. `LibraryBook` 与 `LibraryReadableResource` 在物理树上提供业务语义覆盖；
3. `LibraryResourceAsset` 描述一个可阅读资源实际使用的文件或子节点；
4. 删除 Version 概念，现有 Volume 演化为 ReadableResource，现有 File 演化为
   ResourceAsset。

SourceNode 不是为了取代文件系统。它是数据库侧的物理索引和稳定关联点，使重扫时
能够用一次顺序遍历更新物理状态，并只对发生变化的节点重算 Book、Resource、Asset、
元数据和导入任务。若每次业务查询都临时访问 NAS，则无法稳定分页、关联进度、表达
缺失状态或避免反复读取机械硬盘。

## 最终领域边界

```text
Library
  └─ SourceNode (完整物理树，FILE 或 DIRECTORY)

Book
  ├─ sourceNodeId -> SourceNode
  └─ ReadableResource *
       ├─ sourceNodeId -> SourceNode（文件或目录）
       └─ ResourceAsset * -> SourceNode
```

物理模型只回答“磁盘上有什么、在哪里、是否仍存在”。业务模型只回答“什么是一本
图书、什么可以独立阅读、阅读器需要哪些资源”。目录可以只是容器，也可以同时被
解释为 Book 或目录型 ReadableResource；同一层级可以并列出现 EPUB、PDF、音频和
普通文件夹。

### LibrarySourceNode

根 Library 本身不创建 SourceNode；根目录下节点的 `parentId` 为 `NULL`。

建议字段：

- `id`, `libraryId`, `parentId`；
- `relativePath`, `pathKey`, `name`；
- `physicalKind`: `FILE | DIRECTORY`；
- `fileRole`: `READABLE | METADATA | COVER | SIDECAR | OTHER`；
- `presenceStatus`: `PRESENT | MISSING | UNREADABLE`；
- `sizeBytes`, `mtimeMs`, `fingerprint`；
- `sourceRevision`, `lastSeenScanId`；
- `defaultSortKey`, `metadataSortOrder`；
- `displayTitle`, `coverPath`；
- 创建和更新时间。

约束与索引：

- `UNIQUE(libraryId, pathKey)`；
- 为 `(libraryId, parentId, presenceStatus)`、`lastSeenScanId` 和展示排序建立索引；
- 数据库存相对路径，不重复存绝对路径；运行时相对 Library 根目录解析，并继续执行
  路径穿越和符号链接逃逸检查；
- 记录所有未被忽略的文件和目录。格式支持和最小文件大小只决定是否生成业务资源，
  不决定是否保存 SourceNode；
- 空目录也保存，界面默认隐藏，可通过查询参数显示；封面、OPF 等内部文件不计为可见
  内容。

默认排序使用当前文件系统展示所采用的自然排序；节点元数据配置了排序值时，使用
`metadataSortOrder` 覆盖默认值。不增加手动拖拽排序体系。

### LibraryBook

`LibraryWork` 直接演化并重命名为 `LibraryBook`，保留图书级标题、作者、简介、标签、
书架、封面等业务字段，并增加唯一的 `sourceNodeId`。Book 详情页是点击图书后的默认
入口。

Book 不复制物理子树，也不保存 Version。Book 下的目录内容由 SourceNode 的父子关系
按需查询，任意深度均采用相同规则。

### LibraryReadableResource

`LibraryVolume` 直接演化并重命名为 `LibraryReadableResource`：

- `bookId` 直接指向 Book；
- `sourceNodeId` 唯一指向一个文件或目录节点；
- `state`: `ACTIVE | DISABLED`；
- `classificationSource`: `AUTO | LIBRARY_RULE | USER`；
- 保留格式、阅读器、封面、时长、页数、章节数、轨道数及资源级元数据；
- 每个 ReadableResource 独立拥有阅读进度、阅读单元、书签和最近阅读状态。

目录型有声书是正式支持的 ReadableResource。系统可以按照现有音频适配器把一个包含
音轨的目录识别为单一资源；用户可以把该节点转换为普通 DirectoryNode。转换时不删除
资源和进度，而是把资源设为 `DISABLED` 且记录 `USER` 判定，使其子节点恢复为普通可见
内容；重新启用时沿用原进度。

### LibraryResourceAsset

`LibraryFile` 演化并重命名为 `LibraryResourceAsset`：

- `resourceId`, `sourceNodeId`；
- `role`: `PRIMARY | TRACK | PAGE | SUPPLEMENT`；
- 保留 MIME、媒体技术信息、轨道或页面顺序等资源内部属性。

Asset 不重复保存绝对路径。阅读时通过 SourceNode 的相对路径和 Library 根路径定位原始
文件。文件型 Resource 通常有一个 `PRIMARY` Asset；目录型音频 Resource 拥有多个
`TRACK` Asset。

## 导入模式的解释规则

三种导入模式只决定如何从 SourceNode 生成初始语义覆盖，不再决定物理树的形状。

### FLAT

根目录任意深度中的每个受支持可读文件生成一个 Book、一个 ReadableResource 和一个
PRIMARY Asset。祖先目录仍完整保留在物理树中，但不强制成为业务层级。

### VOLUMES

- 根目录中的可读文件生成单文件 Book 和 Resource；
- 根目录中的文件夹生成 Book；
- Book 下允许文件和文件夹任意嵌套并在 UI 中并列展示；
- 每个受支持可读文件生成 Resource；
- 普通目录只是导航容器，除非被格式适配器或用户明确解释为目录型 Resource。

不再规定“直接子目录是版本”，也不对更深层目录赋予新的业务名词。

### AUDIOBOOK

- 根目录中的音频文件生成单文件 Book 和 Resource；
- 根目录中的文件夹生成 Book；
- 被音频适配器识别为完整出版物的目录生成一个目录型 Resource；
- 活跃目录型 Resource 的后代是它的 Asset，不再同时生成嵌套 Resource；
- 用户把目录型 Resource 转换为普通目录后，其子节点重新按普通树展示和解释。

## 元数据、封面和进度

元数据优先级继续使用系统已有的用户可配置规则，不新增另一套优先级机制：

- 图书级目录元数据写入 Book；
- 原 Version 所承担的目录展示标题、封面和排序写入 SourceNode；
- EPUB、PDF、音频等文件元数据及旁车 OPF 写入 ReadableResource；
- 媒体技术属性写入 ResourceAsset；
- Book 或目录没有自己的封面/元数据时，可按现有优先级回退到第一个可读资源；
- 普通文件夹只读取本地元数据，不自动执行外部图书元数据查询；外部查询目标仅为 Book
  或 ReadableResource。

Book 阅读进度是所有 `ACTIVE` 且未隐藏 Resource 进度的等权平均值。`DISABLED` Resource
不参与聚合；`MISSING` 但仍为 ACTIVE 的 Resource 保留进度并继续参与聚合。至少存在一个
活跃 Resource 且全部达到 100% 时，Book 才算完成。“继续阅读”选择最近产生阅读进度的
Resource。聚合查询直接使用 `resource.bookId`，不得递归遍历物理树。

## 全量重扫与缺失处理

一次完整重扫仍使用现有 `ImportScanJob`、`ImportWorkItem`、`os.scandir()` 有界迭代、队列
水位和分片限制。扫描器为每个未忽略节点产生轻量观察值并批量执行：

1. 计算由类型、大小、修改时间及必要路径信息组成的廉价 fingerprint；
2. 按 `(libraryId, pathKey)` 批量 upsert SourceNode；
3. 所有已看到节点更新 `lastSeenScanId`；
4. 只有 fingerprint、存在状态或解释状态实际变化时，递增 `sourceRevision` 并纳入本批
   changed node IDs；
5. 仅针对 changed node IDs 重算 Book、Resource、Asset、元数据读取和 ImportTask；
6. 在同一个短事务中提交该批 SourceNode 及其直接派生写入。

仅更新 `lastSeenScanId` 不得修改 `updatedAt` 或递增 `sourceRevision`，否则十万图书重扫会
把所有行伪装成业务变化并触发全库级联更新。

扫描完整结束且所有目录枚举均成功时，把本次未看到的既有节点标记为 `MISSING`，而不
物理删除，也不立即删除 Book、Resource、Asset 或阅读进度。只要任一目录发生读取错误，
本轮跳过 unseen-to-missing 对账，避免把 NAS 临时离线误判成批量删除。界面提示对应路径
不存在即可。

不实现移动/重命名识别；路径变化按旧节点 MISSING、新节点新增处理。不引入内容哈希、
文件系统事件总线、分布式扫描、逐目录持久游标或复杂重试。进程崩溃后允许从 Library 根
重新扫描，依靠幂等 upsert 恢复。

对于约十万本书、目录深度 2～3 层的普通 NAS/机械硬盘，主要成本是一次顺序目录枚举和
SourceNode 批量 upsert。该成本与实际节点数线性相关，通常由 NAS 元数据访问延迟主导；
通过有界扫描、短事务、批量写入和 changed-only 派生更新，不会再把未变化的十万本书
全部重新解析。该设计接受最终一致性，不承诺实时反映文件系统变化。

## API 与 Web 目标

本次是未发布版本的破坏性重构，不保留旧 API 别名或兼容响应。目标 API 以以下资源为
中心：

- `/api/books`, `/api/books/{bookId}`；
- `/api/books/{bookId}/nodes`；
- `/api/books/{bookId}/nodes/{nodeId}/children`；
- `/api/source-nodes/{nodeId}/cover`；
- `PATCH /api/source-nodes/{nodeId}/interpretation`；
- `/api/resources/{resourceId}`、cover、reading-units、reclassify、download；
- `/reader/v4/resources/{resourceId}/...`。

`GET /api/books/{bookId}` 返回图书元数据、聚合进度、根节点信息和第一层目录内容；更深
层级按需加载，禁止一次返回无界整棵树。

Web 端把 `features/works` 演化为 `features/books`，使用 `BookView`、`SourceNodeView`、
`ReadableResourceView`。图书详情由元数据头部、整体进度和当前目录内容组成：文件夹进入
下一层，Resource 打开对应阅读器。删除版本画廊、版本分页和版本编辑入口。所有新增界面
同时完成 `zh-CN` 与 `en-US` 文案。

手机端在基础架构完成后单独更新；本次不为了兼容现有手机模型保留 Version。

## 当前实现影响面

审计时确认的主要切入点如下，行号会随开发变化，以文件和职责为准：

- `apps/api-python/app/models/library.py` 定义当前 Work/Version/Volume/File 模型；
- `apps/api-python/app/modules/library/domain/layout.py` 把路径强制解释为固定层级；
- `apps/api-python/app/modules/importing/infrastructure/files/topology_scan.py` 只产出可导入
  候选并拒绝普通目录；
- `apps/api-python/app/modules/importing/infrastructure/files/streaming_scan.py` 已具备可复用
  的有界扫描基础；
- `apps/api-python/app/modules/importing/infrastructure/persistence/scan_batch_store.py` 当前
  直接写入 Work/Version/Volume/ImportTask/ImportAsset/ImportWorkItem；
- Library HTTP、Reader DTO、进度、书签、阅读单元、元数据、整理、下载、Kindle、OPDS、
  备份、统计和 Web 均仍传播 `versionId`/`volumeId`。

审计快照中，后端生产代码约有 34 个文件直接引用 `LibraryVersion`、43 个文件引用
`LibraryVolume`、31 个文件引用 `LibraryFile`；约 60 个文件出现 `version_id`、93 个文件
出现 `volume_id`。Web 版本相关表面约 22 个文件，手机端约 36 个文件。上述数字仅用于
说明重构规模，不是实现完成条件；最终以全仓库语义检索为准。

当前工作区存在与导入、Library 和 Web 重叠的未提交修改，其中部分修改继续强化 Version
封面、画廊、分页和编辑能力。开始开发前必须先保存或隔离这些用户改动；扫描设置和有界
扫描改进可按新架构复用，但 Version 专属迁移与 UI 不进入最终实现。

## 一次性实施路径

重构按依赖方向推进，允许中间阶段无法启动或测试失败；在最终模型完成前不运行全量测试，
但每阶段必须做最小的结构或导入检查，避免错误累积。

### 阶段 0：固定决策与保护工作区

- 本 ADR 是最终结构决策；后续实现不再引入 Edition/Version 等中间容器；
- 保存或隔离当前未提交修改，明确哪些扫描能力保留、哪些 Version 增强废弃；
- 列出所有模型、外键、API、Worker 和 Web 调用方，作为删除清单。

### 阶段 1：直接建立最终数据库模型

- 因应用未发布，重写当前唯一 Alembic baseline，只支持新建数据库；
- 新建 SourceNode、Book、ReadableResource、ResourceAsset 及索引和约束；
- 把进度、书签、阅读单元、元数据、导入任务等外键直接改为 `bookId`/`resourceId`；
- 删除 LibraryVersion 和 Version 专属表、约束、迁移；
- 不写旧数据迁移、回填、双写或兼容模型。

阶段完成只验证 ORM 模型可导入、全新数据库可创建。

### 阶段 2：替换拓扑扫描和批量持久化

- 删除 `LayoutVersion`、`LayoutVolume`、`version_identity`、
  `PreparedTopologySource` 等固定层级解释；
- 保留有界 `os.scandir()` 和持久队列，扫描器改为产出目录与文件观察值；
- 实现 SourceNode 批量 upsert、changed node IDs、完整扫描 missing 对账；
- `scan_batch_store` 只对变化节点创建或更新语义覆盖与导入任务；
- 不引入第二张 change-log 表或事件总线。

### 阶段 3：迁移格式导入器

- 依次迁移 EPUB、PDF、TXT、MOBI、FB2、Comic 和 Audio；
- 每个导入器从 SourceNode/Resource/Asset 读取和写入，不再创建 Work/Version/Volume；
- 音频目录识别与用户转换成为显式策略；
- 保持原始格式阅读，不生成派生 EPUB 或持久解包目录；
- 完成调用方切换后立即删除旧实现，不做双写。

### 阶段 4：迁移核心读取与阅读链路

- 先迁移授权和图书/目录查询，再迁移媒体与 Publication；
- Reader、进度、书签、阅读单元统一改用 `resourceId`；
- Book 进度和继续阅读按本 ADR 的 Resource 聚合规则实现；
- HTTP 路由保持薄适配器，事务与文件副作用顺序归应用用例负责。

### 阶段 5：迁移次级后端能力

- 元数据、封面、整理、OPDS、Kindle、下载、备份、仪表盘、书架、分面和事件；
- 删除版本合并、转移、封面画廊、分页和编辑等结构操作；
- 备份只表示新架构，不读取任何旧备份格式。

### 阶段 6：重写 Web

- 更新生成契约和 feature 模型；
- 完成 Book 详情的惰性目录浏览、混合 Resource 展示、缺失和空目录状态；
- 更新各阅读器入口与资源级进度；
- 完成中英文国际化；
- 手机端保持明确未适配状态，不加入临时兼容层。

### 阶段 7：删除遗留并统一验收

- 全仓库检索并删除运行时代码中的 Version/Edition、`versionId`、旧 `volumeId` 语义；
- 删除重复实现、临时适配和无调用代码；
- 最后统一运行后端单元/集成/API/Worker/导入测试、全新数据库迁移测试、Web lint、
  typecheck、tests、i18n check 和关键 Reader E2E；
- 测试失败应修复到最终架构，不恢复旧模型来换取通过。

## 明确不做

- 旧数据库迁移、历史数据回填、旧 API/备份兼容；
- 本阶段手机端兼容；
- 文件移动或重命名识别；
- 全文件内容哈希；
- 分布式扫描、文件事件总线、多写者协调；
- 复杂的子树断点续扫或重试编排；
- 手动拖拽排序体系；
- 为中间阶段维持可发布状态。

## 完成标准

- 运行时代码和数据库不再存在 LibraryVersion/Version 业务概念；
- 物理层只有 SourceNode 树，业务层只有 Book、ReadableResource、ResourceAsset；
- 全量重扫更新全部已见 SourceNode，但只有真实变化触发业务派生更新；
- 删除或离线目录以 MISSING 表达，不误删阅读进度；
- Book 下可浏览任意深度文件夹，并列展示不同格式和目录；
- 文件型与目录型 ReadableResource 均可阅读、转换并保持资源级进度；
- Book 聚合进度、完成状态和继续阅读符合本 ADR；
- Web 完成新模型和中英文适配；
- 最终适用质量门全部通过；
- 手机端适配作为基础架构完成后的独立工作明确保留。

## Consequences

该决策消除了没有实际语义的 Version，并允许文件系统保持任意自然层级。代价是本次需要
同时改动数据库、扫描、导入、Reader、API 和 Web，属于一次中大型破坏性重构；但应用尚未
发布，不承担兼容成本，现在是一次完成该边界调整的最低成本窗口。

SourceNode 会使数据库行数接近所有未忽略文件和目录数，但它把昂贵 NAS 遍历与高频业务
查询解耦，并为增量派生更新、缺失提示、稳定分页和资源关联提供必要基础。架构接受重扫
期间的短暂最终一致性，以简单、可解释和可维护为优先目标。
