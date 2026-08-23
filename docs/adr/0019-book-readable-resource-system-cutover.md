# ADR 0019：Book / ReadableResource / ResourceAsset 全系统切换

- 状态：Accepted（最终切换规范；不表示当前工作区已经通过验收）
- 日期：2026-08-22
- 依据：ADR 0018、ADR 0012、ADR 0014、ADR 0016
- 类型：fresh-only、破坏性身份切换
- 后续：Mobile 排除条款已由 [ADR 0020](0020-mobile-book-resource-asset-cutover.md)
  完成其独立切换决策；本文件仍记录 0019 批次当时的范围边界

## 1. 决策摘要

本 ADR 把产品和运行时代码一次性从 Work / Version / Volume / File 身份切换为：

~~~text
LibrarySourceNode
    └─ LibraryBook
        └─ LibraryReadableResource
            └─ LibraryResourceAsset
~~~

SourceNode 是物理源树中的路径节点；Book 是图书聚合；ReadableResource 是可以独立打开的
文件型或目录型阅读资源；ResourceAsset 是 Resource 实际使用的真实常规文件。

这是一次 fresh-only 的破坏性切换，不是迁移项目、兼容项目或双轨重构。最终交付只允许
存在一套新身份、一套新 API、一套生产导入链和一套授权规则。

本 ADR 决定：

1. 后端、API、Web 和 packages/reader-core 在同一批次完成新身份切换；
2. Mobile 完全排除在本批次之外，可以暂时继续使用旧身份并与新后端不兼容；
3. 生产代码先整体切换完成，再统一更新 fixtures、契约测试、架构守卫和其他测试；
4. 测试不得成为保留旧接口、旧模型或兼容 shim 的理由；
5. 最终删除所有旧表、旧 ORM、旧路由、旧 DTO、旧模块和兼容层；
6. 导入只使用 ADR 0018 定义的简单单消费者 ContinueImport 链路；
7. 没有中间交付状态，没有 upgrade/backfill，没有旧数据处理，没有旧接口过渡期。

本文是实施和验收的权威目标。代码尚未完成时不得以本 ADR 的存在声称切换已经完成。

## 2. 范围与明确排除

### 2.1 本批次范围

必须在同一个最终生产状态中完成：

- fresh database baseline、SQLAlchemy ORM 和所有应用数据库访问；
- Library、授权、目录、dashboard、过滤、facet、shelf、最近阅读和继续阅读；
- Reader bootstrap、Reader 进度、书签、偏好、mutation receipt、progress cursor；
- reader-core 的身份、Locator、恢复和同步协议；
- Publication、导航缓存、EPUB/MOBI/AZW/AZW3/PRC/TXT/FB2、PDF、comic、audiobook；
- Media 文件、页面、封面、下载和 Range 访问；
- metadata lookup/writeback、organize、Kindle、backup、OPDS、download；
- ContinueImport、SourceNode 扫描、target worker 和 composition root；
- FastAPI schemas/routes、OpenAPI、Web adapters、models、hooks、UI；
- 对应文档、fixtures、contract tests、integration tests、architecture guards 和静态门禁。

所有上述能力的业务身份必须使用 Book / ReadableResource / ResourceAsset。跨能力调用必须
通过 public API、application port 或稳定 contract，不得深层导入另一个能力的私有文件。

### 2.2 Mobile 完全排除

本 ADR 不修改、不删除、不重命名、不生成和不测试 apps/mobile 的代码。

因此本批次允许 Mobile 暂时保留 Work / Version / Volume / File 类型、字段、旧路由、旧
下载协议和旧 Reader 参数。后端不得为了维持 Mobile 暂时可用而添加旧接口、双读、双写、
兼容 DTO 或 ID 映射。Mobile 后续必须依据单独的设计和 ADR 一次性切换。

### 2.3 不做数据库迁移

本批次不处理旧数据库中的任何数据。禁止：

- upgrade migration、old-to-new backfill、数据清洗、合并、ID 映射和历史状态修复；
- 旧表与新表双写，或根据旧表是否存在选择实现；
- 动态表检测、旧备份转换、临时兼容启动路径；
- 为旧数据库增加过渡 API 或运行时转换器。

目标是 fresh database。旧数据库需要由产品层面另行处理，不属于本 ADR。

## 3. 唯一身份模型

| 业务概念 | 唯一身份 | 责任 |
| --- | --- | --- |
| 物理源节点 | sourceNodeId | Library 内相对路径树节点，不是实时文件系统镜像 |
| 图书聚合 | bookId | 可见性、策展状态、元数据、书架和图书级授权 owner |
| 可打开资源 | resourceId | format、mediaKind、启用状态、导入状态和 Reader owner |
| 真实文件资产 | assetId | Resource 使用的常规文件、角色、顺序和技术信息 owner |

SourceNode 可以出现在导入、源树管理和受保护的物理路径管理 contract 中。公开内容、
Reader、媒体、进度和下载 contract 的核心身份只能使用 bookId、resourceId、assetId。

产品代码中禁止使用 Work、Version、Volume、File 表示上述业务概念。内部函数、参数、变量、
类名、文件名和公开 symbol 也必须采用 book/resource/asset 命名。历史 ADR、迁移禁止项清单
和本文件中的反例可以保留旧词，但不得被运行时导入。

### 3.1 Book

LibraryBook 至少包含 id、libraryId、sourceNodeId、visibilityState、curationState 和
时间字段。标题、作者、简介、系列、封面和 metadata quality 属于 LibraryBookMetadata；
标签和 facet 使用独立关系表。

Book 约束：

- sourceNodeId 在同一 Library 内唯一；
- Book、锚点 SourceNode 和 Library 必须属于同一 Library；
- sourceNodeId 创建后不可改变；
- 可见性来自 Book state，不从 Resource 或 Asset 推导；
- 空 Book 可以出现在管理视图，但不能进入 continue-reading；
- Book 不包含 Version、Edition 或固定中间业务层。

Book 完成状态由 actor 可见的 Resource 进度投影得出，不能使用旧 Volume 或旧进度表。

### 3.2 ReadableResource

LibraryReadableResource 至少包含 id、libraryId、bookId、sourceNodeId、adapterId、
adapterVersion、mediaKind、format、enablementState、importState 和时间字段。

Resource 约束：

- 一个 SourceNode 至多锚定一个 Resource；
- Resource、Book、锚点 SourceNode 必须属于同一 Library；
- 锚点必须等于 Book 锚点，或位于 Book 锚点子树内；
- 可以锚定 REGULAR_FILE 或 DIRECTORY；
- bookId 和 sourceNodeId 创建后不可改变；
- enablementState 只表达用户启停；
- 只有 ENABLED + READY 才承诺当前可打开；
- 拥有 READY Asset 后可置为 READY；没有 READY Asset 时可以置为 FAILED；
- 已 READY 的 Resource 不因后来某个 Asset 失败而回滚。

目录 Resource 是可独立打开的叶子对象。启用、禁用或继续导入目录 Resource 不会级联
修改后代 SourceNode 或后代 Resource。

### 3.3 ResourceAsset

LibraryResourceAsset 至少包含 id、libraryId、resourceId、sourceNodeId、role、importState、
sequenceIndex、sortKey、技术元数据、错误摘要和时间字段。role 只允许 PRIMARY、TRACK、
PAGE、SIDECAR、SUPPLEMENT。

Asset 约束：

- UNIQUE(resourceId, sourceNodeId)；
- Asset、Resource、SourceNode 必须属于同一 Library；
- Asset 的 SourceNode 必须是 REGULAR_FILE；
- 文件型 Resource 的 PRIMARY 必须指向 Resource 自身节点；
- 目录型 Resource 的 Asset 必须位于 Resource 锚点子树内；
- 同一 SourceNode 可以被不同 Resource 作为 Asset 引用；
- 继续导入时保留已有关系的 Asset ID；
- EPUB spine、压缩包内部图片、虚拟章节不是 SourceNode 或 ResourceAsset。

当前可读文件查询只能看到 resourceId 匹配且 importState = READY 的 Asset。

### 3.4 目标表

ADR 0018 定义的十张 fresh baseline 核心表必须保持：

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

附属能力必须直接挂到新身份，包括 LibraryBookFacet、LibraryReadableResourceFacet、
ShelfBook、BookDetailPreference、ReaderBookPreference、ReaderProgressCursor、
ReaderResourceProgress、ReaderProgressMutation、ReaderBookmark、
ReadableResourceNavigationUnit、PublicationNavigationCache，以及 metadata、organize、
Kindle、download、backup、OPDS、授权和 operation 关系。

目标 baseline 与 runtime ORM metadata 必须完全一致。不得存在为旧模型保留的影子表、空壳
模型或仅供测试导入的旧关系。

## 4. 物理源树与组织模式

SourceNode 规则完全沿用 ADR 0018：

- relativePath 是 Library 内精确相对路径；
- 拒绝绝对路径、空段、点段、NUL 和越根路径；
- pathKey 使用版本化 SHA-256 摘要并防止摘要碰撞；
- parentId 必须属于同一 Library 并指向 DIRECTORY；
- SourceNode 树不得成环，父路径必须与子路径一致；
- Library 根目录本身不建立 SourceNode；
- SYMLINK 只记录，不跟随、不导入；
- socket、device、FIFO 等 OTHER 只记录，不建立资源；
- 已有节点的 observed 字段不因 ContinueImport 更新；
- 不自动检测移动、重命名、删除、内容变化或 missing 状态。

Library 只允许 FLAT 和 VOLUMES：

- FLAT：每个自动识别的文件或目录 Resource 独立形成一个 Book；
- VOLUMES：Library 根下文件夹形成 Book，子树 Resource 归属于该 Book，允许空 Book；
- 文件和目录使用相同 adapter registry；
- 已有 SourceNode 后不允许原地切换模式；
- 模式切换必须删除该 Library 的数据库关联记录，再重新扫描，磁盘文件不删除；
- 根路径迁移只修改 rootPath，保留相对路径和新身份 ID，并验证新根存在、可读且不冲突。

## 5. ContinueImport 与单消费者导入

### 5.1 唯一生产链

生产环境只能使用以下 target importer：

~~~text
ContinueImport
  ├─ ScanSourceTree
  └─ ProcessReadableResourceImportTask

SqlAlchemyReadableResourceWorkQueue
  └─ LibraryImportTask

target adapter registry
~~~

应用入口使用显式命令 ContinueLibraryImport(library_id) 和
ContinueSourceImport(source_node_id)。首次导入、重新发现、继续补齐和用户再次执行都
统一称为 ContinueImport。不得保留 Reimport、Retry、Rescan 或重新识别作为兼容入口。

### 5.2 任务与消费语义

LibraryImportTask 只允许 kind、libraryId、resourceId、sourceNodeId、role、state、
errorSummary、createdAt、startedAt、finishedAt。kind 只允许 SCAN_LIBRARY、CONTINUE_SOURCE、
IMPORT_ASSET；state 只允许 QUEUED、RUNNING、SUCCEEDED、FAILED。

禁止 lease、owner、expiry、attempts、priority、availableAt、heartbeat、claim version、
fencing token、CAS、Run、candidate、published set、discovery barrier、WorkItem bridge、
自动 retry/backoff、取消状态机、queue control 和多消费者竞争保护。

唯一消费者严格按 createdAt 顺序处理：

1. 短事务取最早 QUEUED 任务并改为 RUNNING；
2. 提交事务；
3. 在事务外执行扫描、文件系统访问和解析器工作；
4. 成功后在短事务中直接写稳定业务结果并置 SUCCEEDED；
5. 失败时回滚本次业务写入，再在短事务中置 FAILED；
6. 继续消费下一条任务。

启动时将遗留 RUNNING 任务改为 FAILED，使用稳定错误码 WORKER_INTERRUPTED，不自动重排。
用户再次 ContinueImport 时才将相关 FAILED 任务重新置为 QUEUED。未预期 worker 异常使用
WORKER_ERROR 终止当前任务，不自动重试。

### 5.3 扫描、识别和 Asset 写入

ContinueLibraryImport 流式扫描根目录，插入新 SourceNode，识别没有解释的节点，为缺失或
FAILED 的兼容 Asset 建立 IMPORT_ASSET，跳过 SUCCEEDED 任务，不删除未再次发现的节点。
NODE_ONLY 节点只在用户再次 ContinueImport 时允许重新探测；已有 RESOURCE 固定 adapter。

ContinueSourceImport 处理文件节点及其 PRIMARY Asset，流式遍历目录并补齐 TRACK/PAGE 等
Asset。不得建立重复 Book、Resource、Asset；不得为 DIRECTORY、SYMLINK、OTHER 建立
IMPORT_ASSET。

IMPORT_ASSET 在事务外解析真实原始文件，成功后直接 upsert ResourceAsset，并按
resourceId + sourceNodeId 保留关系 ID。Resource 至少有一个 READY Asset 后置为 READY。
失败只影响当前任务和对应 Asset；已经 READY 的 Resource 保持 READY。

禁止 candidate/publishedRun 中间态，禁止数据库事务包围文件系统或解析器 I/O，禁止自动
重试和隐藏的后台任务。

### 5.4 原始格式与目录资源

遵循 ADR 0016：

- EPUB、MOBI、AZW、AZW3、PRC、TXT、FB2 使用原始文件或 parser-backed in-memory
  Publication；
- PDF、comic、audiobook 保留原始文件和真实页面或轨道 Asset；
- Reader、download、cache、recovery 不创建、缓存、宣传或下载派生 EPUB、ZIP 或解包目录；
- 目录 Resource 不允许临时 ZIP 打包；
- 压缩包内部对象不能伪装成 SourceNode 或 ResourceAsset；
- dormant legacy import conversion subsystem 不得连接 Reader、delivery、download 或
  progress。

解析器权威规则、Publication TOC、导航缓存和 Reader Locator 继续遵守 ADR 0012、0014、
0016。导航缓存 owner 是 resourceId + assetId，不是旧 ReadingUnit/Volume。

## 6. 后端、API 与业务能力切换

### 6.1 API 路由和 wire

规范入口为：

| 意图 | 规范入口 |
| --- | --- |
| 图书列表 | /books |
| 图书详情 | /books/{bookId} |
| 图书资源 | /books/{bookId}/resources |
| 资源详情 | /resources/{resourceId} |
| 资源资产 | /resources/{resourceId}/assets |
| 资产访问 | /assets/{assetId} |
| Reader v4 | /reader/v4/resources/{resourceId}/... |
| Library scan/import | /books/import 或 /libraries/{libraryId}/scan |

具体 method、status、envelope 和错误 code 必须由 contract tests 固定。旧 /works、
/versions、/volumes 和旧 file-identity 路由不注册，由框架直接返回 404；不得返回 410、
redirect 或安装兼容 handler。

稳定 wire 字段只允许 bookId、resourceId、assetId，以及物理源树管理需要的 sourceNodeId。
禁止 workId、versionId、volumeId、fileId 及 snake_case 变体出现在当前生产 API、DTO、
schema、OpenAPI 或 Web contract 中。禁止 versions 数组、WorkVersion、VersionResource、
availableVolumes、continueVolumeId、continueVersionId 和 selectedVersionId。

### 6.2 Library、授权和个人数据

Library 查询和命令必须在数据库查询阶段应用 actor 可见性和资源授权范围；分页排序必须
稳定且有最大页大小；ORM entity 不得泄漏到 presentation 或其他能力。

必须迁移并保持用户隔离：

- shelf 使用 ShelfBook；
- Book preference 使用 bookId；
- Resource progress、bookmark、mutation receipt、cursor 使用 resourceId；
- navigation cache 使用 resourceId/assetId；
- 删除 Book、Resource、SourceNode 依靠正确 FK/CASCADE 清理附属数据；
- not-found 与 forbidden 的既有防枚举语义保持不变。

### 6.3 Reader、Publication、Media 与下载

文件访问统一遵守：

1. 校验 actor 对 Book/Resource 的访问权；
2. 加载 ENABLED + READY 的 ResourceAsset；
3. 校验 REGULAR_FILE SourceNode；
4. 使用配置的 Library root + relativePath；
5. 再次验证 traversal、绝对路径和 symlink escape；
6. 返回原始文件或 parser-backed 内容。

Reader bootstrap、progress、bookmark、reading status、manifest、positions、comic page、
PDF Range、audiobook tracks、cover 和 download 的公开身份全部迁移到新 ID。Locator 以
稳定 resource href 与 selector、fragment、CFI 或有界文本上下文表达，不依赖 EPUB 容器。

### 6.4 Metadata、Organize、Kindle、Backup、OPDS、System

- metadata lookup/writeback owner 只能是 Book、Resource、Asset 或 SourceNode；
- organize 不得重新引入 Version 或数据库结构归组、merge/split/transfer；
- Kindle task 只接受 bookId/resourceId/assetId；
- backup 只支持新 schema 和新身份格式，不读取旧备份；
- OPDS 暴露 Book/Resource 语义；
- download 完成只能触发 ContinueImport，不调用 legacy scan/requeue 入口；
- system/health 保留与身份切换无关的稳定能力，但不得暴露旧 import queue control、
  lease、heartbeat 或 legacy importer 状态。

## 7. Web 与 packages/reader-core

### 7.1 Web

Web 必须使用 book/resource/asset 的 wire DTO、domain model、view model 和 form state。
API client 只能通过 shared transport 和 capability adapter 访问网络；页面不直接解析
envelope，不直接使用 ORM 概念。

library、reader、shelf、media、imports、organize、metadata、download 页面同时完成新身份
切换。OpenAPI/client 类型通过生成流程更新，生成文件禁止手工编辑。zh-CN、en-US 的用户
可见文案、metadata、错误和 accessibility label 同步完成。

Web 产品代码必须零命中旧 wire 字段和旧产品 Version 概念。历史文档和专门的禁止项测试
可以包含旧词。

### 7.2 packages/reader-core

reader-core 保持 framework-independent，只负责 Reader session、Locator、导航、进度、
恢复的纯规则、resourceId/assetId 协议、解析器无关的状态转换和 Reader adapter port。

reader-core 不得依赖 FastAPI、SQLAlchemy、Web browser、Mobile UI 或旧 Volume/File DTO。
Reader 进度恢复失败不得阻塞内容打开和关闭动作；Parser-authoritative 规则继续有效。

## 8. 分层与实现约束

后端依赖方向固定为：

~~~text
delivery/presentation -> application -> domain
infrastructure -> application ports and domain types
composition root -> all layers for wiring only
~~~

必须遵守：

- domain 不依赖 FastAPI、ORM、文件系统、队列、环境或第三方 SDK；
- application 不依赖 Request/Response、SQLAlchemy implementation 或浏览器；
- route 只解析输入、取得 actor、调用一个用例、映射结果；
- repository 使用 SQLAlchemy ORM 和 typed expression API；
- 禁止 handwritten SQL、sqlalchemy.text、文本 SQL、exec_driver_sql、sqlite3 和 raw cursor；
- 低层 repository 只 flush，不隐藏 commit/rollback；
- 文件发布使用临时路径、校验和原子 replace；
- 跨能力只通过 public.py、应用 port 或稳定 contract；
- 不添加通用 utils/helpers/managers/compat dumping ground；
- 稳定边界使用显式 Pydantic、dataclass 或 domain value object；
- 不使用 Any、wildcard import、mutable module state、TODO/FIXME 或全局 ignore 逃避门禁；
- 所有写用例明确校验/授权、当前状态、业务决策、事务边界、副作用和恢复路径。

## 9. 一次性实施流程

本批次不产生中间交付物。工作树在切换期间可以暂时不可运行，但对外只能交付完整的新
实现。生产代码和最终测试不允许在旧/新身份之间形成可提交的中间状态。

### 阶段 0：冻结与盘点

1. 读取本 ADR、ADR 0018、0012、0014、0016 和分层规则；
2. 盘点入口、调用方、授权、状态、文件/队列副作用和生成物；
3. 确认目标 baseline 是 fresh-only；
4. 明确 Mobile 不在本批次；
5. 建立旧身份、旧表、旧路由、旧模块和旧导入链禁止清单；
6. 审查在途 target importer 接线，只能纳入和完善，不能覆盖或另建重复实现。

### 阶段 1：并行完成生产代码

按第 10 节的任务边界并行修改后端、Web 和 reader-core。此阶段只修改生产代码、生成
流程所需的输入和必要文档，不更新旧测试来保留旧契约。

每个并行任务必须：

- 只编辑自己的边界；
- 通过 public contract 与其他任务协作；
- 不添加兼容层；
- 不提交独立中间 commit；
- 在自己的边界内完成新身份和依赖方向；
- 向主验收者报告未解决的跨边界调用，而不是临时加 shim。

### 阶段 2：生产代码收敛

所有生产任务完成后，主验收者一次性：

1. 通过正式生成流程生成 OpenAPI/client 产物；
2. 更新跨边界 import 和 composition root；
3. 运行旧身份、旧路由、旧表、旧模块、旧队列和派生格式静态扫描；
4. 修复所有生产代码残留；
5. 确认 Mobile 没有被修改；
6. 确认 runtime ORM 与 fresh baseline 对齐。

在本阶段通过前，不开始重写测试，不保留任何“先让旧测试通过”的兼容代码。

### 阶段 3：统一更新测试和 fixtures

生产代码冻结到新契约后，统一更新：

- unit/domain/application tests；
- repository/integration tests；
- API contract tests；
- worker/import failure tests；
- Web model/component/e2e tests；
- reader-core tests；
- architecture guards；
- fixtures、OpenAPI snapshots 和双语检查。

测试必须断言新身份的可观察行为，不得为了过测试恢复旧模块、弱化断言、添加 skip 或
保留旧别名。明确退役的旧能力测试删除；仍有效的业务行为测试必须改用 Book/Resource/Asset
fixtures 恢复。

### 阶段 4：统一验证与交付

完成所有测试和门禁后，形成一个最终交付 commit。禁止中间 commit、临时兼容发布或把
未解决的跨边界问题留给后续清理。

## 10. 可并行任务边界

并行任务可以在独立 worktree 中完成，由主验收者按新身份合并；不能通过共享私有文件或
直接覆盖另一任务的实现协作。

| 任务 | 负责范围 | 不得修改 | 完成条件 |
| --- | --- | --- | --- |
| A：Schema 与 baseline | apps/api-python/app/models、app/db、schema metadata、FK/CASCADE、fresh baseline | 其他能力 HTTP/UI；Mobile | 目标表唯一、baseline 与 ORM 一致、无旧表、无 upgrade/backfill |
| B：Source tree 与 importer | ADR0018 SourceNode、ContinueImport、ScanSourceTree、ProcessReadableResourceImportTask、queue、worker、adapter registry、composition root | Reader/API 展示；Mobile | 单消费者、失败语义、无 lease/candidate/Run/WorkItem、原始格式 |
| C：Library 与用户能力 | library queries/commands、dashboard、filters、facets、shelf、authorization、progress owner、organize、metadata | importer 私有实现、Web 内部；Mobile | Book/Resource/Asset 查询授权完整，旧 Library/Version API 删除 |
| D：Reader、Publication、Media、reader-core | Reader bootstrap/progress/bookmark、publication/navigation cache、media streaming/page/cover、formats、packages/reader-core | Mobile、Library schema 私有文件 | resourceId/assetId 全链路，Parser-authoritative，无派生格式 |
| E：附属后端 | download、Kindle、backup、OPDS、auth/system、跨能力 contracts 和 bootstrap wiring | A/B/C/D 私有实现；Mobile | 新身份、授权和错误契约，无旧 queue/identity re-export |
| F：Web | API adapters、schemas/mappers、features、routes、generated OpenAPI/client、i18n | apps/mobile、后端 ORM、generated 手工内容 | Web 生产代码只用新身份，旧路由/字段/Version 清零 |
| G：最终测试与验收 | 阶段 2 后统一更新所有适用测试、fixtures、guards、docs 与 acceptance evidence | 生产实现和 Mobile | 测试只验证新契约，所有矩阵通过，无 skip/弱化断言 |

任务 A 是唯一 schema owner；任务 B 是唯一 production import owner；任务 F 不得手工编辑
generated 目录；任务 G 在阶段 2 之前不得修改测试以迁就旧身份。

## 11. 零残留禁止清单

以下内容在当前生产代码、runtime schema、API、Web、reader-core、fixtures 和测试中必须
不存在；历史 ADR、迁移禁止项清单和本文件的反例表可以包含这些文字。

### 11.1 旧模型和表

- LibraryWork、LibraryVersion、LibraryVolume、LibraryFile；
- LibraryReadingUnit、LibraryReadingProgress、LibraryMetadata；
- LibraryWorkFacet、LibraryVolumeFacet、ShelfWork、WorkDetailPreference；
- ImportTask、ImportScanJob、ImportWorkItem、ImportAsset、ImportLog；
- BookIdentityCache；
- LibraryImportRun、ResourceCandidate、AssetCandidate；
- QueueControlOperation 以及只服务 legacy import 的 queue runtime/control 表。

目标 LibraryImportTask 是唯一允许的同义新表，不得与旧 ImportTask 混淆。

### 11.2 旧身份和 API

- workId、versionId、volumeId、fileId 及 snake_case 版本；
- /works、/versions、/volumes 和旧 file identity 路由；
- WorkVersion、VersionResource、versions、availableVolumes；
- continueVolumeId、continueVersionId、selectedVersionId；
- 旧 File path、file_id、volume_id 作为公开资源访问身份。

### 11.3 旧模块和导入机制

- services/book_identity.py、library/domain/version_identity.py；
- persistent_import_queue、library_scanner、旧 claim/process/transactions/query adapter；
- 只写 Work/Version/Volume/File 的 legacy format importer；
- ImportScanJob、ImportWorkItem、scan candidate、batch、Run、WorkItem bridge；
- requeue_library_volumes、enqueue_library_scan 等过渡入口。

生产导入根只能依赖 ContinueImport、ScanSourceTree、ProcessReadableResourceImportTask、
SqlAlchemyReadableResourceWorkQueue、LibraryImportTask 和 target adapter registry。

### 11.4 兼容和技术债

禁止：

- compatibility wrapper、deprecated re-export、旧 DTO alias；
- 双读、双写、ID 映射、feature flag、动态表检测；
- 410 tombstone、redirect、旧路由兼容 handler；
- TODO/FIXME、skip、弱化断言、广泛 noqa/type ignore；
- 派生 EPUB、ZIP、目录打包、持久解包；
- raw SQL、隐藏 commit、后台 fire-and-forget task；
- 仅为旧测试保留的空壳文件或 symbol。

## 12. 最终验收矩阵

| 领域 | 必须验证 | 通过标准 |
| --- | --- | --- |
| Fresh baseline | 空库创建、baseline 表清单、重复初始化 | 只有目标新表；无 upgrade/backfill；重复初始化幂等 |
| ORM 对齐 | runtime metadata 与 baseline 对比 | 表、列、FK、索引、约束、默认值完全一致 |
| SourceNode | pathKey、父子、类型、环、symlink、traversal、百万节点 | 规则符合 ADR0018；已有节点 observed 不更新；内存为 O(depth + probe budget) |
| Import queue | FIFO、单消费者、成功、失败、重启、再次 ContinueImport | RUNNING → FAILED/WORKER_INTERRUPTED；无自动 retry/lease/heartbeat/fencing |
| Import 结果 | ContinueImport 后 Library/Reader 立即可查询 | Asset 直接写稳定结果；READY 资源不因后续单项失败回滚 |
| Library | catalog/detail/dashboard/recent/filter/facet/shelf/empty Book | 查询只用 Book/Resource/Asset，排序稳定，授权在 SQL 阶段生效 |
| Authorization | admin、manager、scoped user、ordinary user、anonymous、跨 Library | owner/visibility/resource scope 正确；防枚举语义保持 |
| Reader | bootstrap、open、progress、bookmark、cursor、mutation、recovery | 只用 bookId/resourceId/assetId；进度失败不阻塞打开/关闭 |
| Publication | EPUB/PDF/TXT/MOBI/AZW/AZW3/PRC/FB2/comic/audio | 原始格式或 parser-backed Publication；无派生 EPUB/ZIP/解包目录 |
| Navigation | TOC、positions、cache、asset/source 变更 | cache owner 是 resourceId/assetId；parser authoritative；旧 projection 删除 |
| Media | 文件、页面、封面、Range、下载 | 授权 → READY Asset → REGULAR_FILE SourceNode → root/path 安全校验 |
| Metadata/organize | lookup、writeback、facet、organize、undo | owner 仅为 Book/Resource/Asset/SourceNode；无 Version target |
| Kindle/backup/OPDS | task、restore、feed、download completion | 只认新 schema；下载完成触发 ContinueImport；不读取旧备份 |
| API | 新路由、status、envelope、错误 code、OpenAPI | 新身份字段完整；旧路由未注册并返回 404；无兼容 handler |
| Web | adapters、models、hooks、UI、generated、i18n | 生产代码旧字段零命中；generated 由流程产生；zh-CN/en-US 完整 |
| reader-core | 纯规则、Locator、状态机、adapter ports | 无框架/ORM/旧身份依赖，行为测试通过 |
| 旧残留扫描 | 表、ORM、routes、DTO、modules、symbols、queue、derived format | 除历史 ADR/禁止项文件外零命中 |
| Mobile 边界 | apps/mobile diff、扫描和测试 | 本批无 Mobile 修改、无 Mobile 验收要求、后端无 Mobile 兼容 shim |
| 质量门禁 | format、lint、typecheck、pytest、Web tests、i18n、必要 smoke | 无新增 warning、无 skip、无弱化断言、所有适用门禁通过 |

推荐最终命令由项目实际脚本解析后执行，至少包括：

~~~text
git diff --check
Python syntax/compile check
ruff format --check .
ruff check .
mypy app
pytest --cov=app --cov-report=term-missing
pnpm lint
pnpm typecheck
pnpm test
pnpm i18n:check
reader-core tests
capability-specific import/worker/API/runtime smoke
~~~

本文件重建期间不运行上述命令；这些命令属于实现完成后的最终验收流程。

## 13. 交付证据与完成定义

交付前必须提供：

- 最终 commit hash；不得有中间切换 commit；
- fresh baseline 和 runtime ORM 的表、约束清单；
- 删除的旧表、旧 ORM、旧路由、旧 DTO、旧模块、旧 importer/worker 清单；
- 新 API、Reader、Media、Library、Web 和 reader-core 的身份切换摘要；
- ContinueImport 单消费者、失败恢复和事务边界证据；
- 授权、删除级联、路径安全、原始格式和导航缓存测试证据；
- 旧身份、旧队列、派生格式静态扫描结果；
- Web generated 产物生成记录；
- Mobile 未修改的证据；
- 统一测试和质量门禁结果。

完成定义：

1. 生产代码全部切换到新身份；
2. Web 和 reader-core 与后端 contract 一致；
3. Mobile 没有被本批次触碰；
4. 旧表、旧路由、旧 DTO、旧模块、兼容层和 legacy importer 零残留；
5. 测试已在生产代码冻结后统一更新并通过；
6. 没有未拥有、无退出条件的技术债；
7. 形成唯一最终交付。

## 14. 与相关 ADR 的关系

- ADR 0018 继续权威规定 SourceNode、FLAT/VOLUMES、ContinueImport、单消费者队列和
  物理源树导入规则；
- ADR 0012 继续权威规定 Publication 拥有 reflowable navigation；
- ADR 0014 继续权威规定 Parser-authoritative Reader opening；
- ADR 0016 继续权威规定原始格式 Publication、MOBI/TXT parser-backed 内容和禁止派生格式；
- ADR 0002 的复杂持久队列只属于被删除的 legacy importer，不得带入本目标实现；
- Mobile 相关 ADR 继续约束未来 Mobile 重建，但不扩大本批次范围；
- 旧 ADR、历史 migration 和历史 commit 可以描述旧身份，但不得被当前运行时导入或作为
  当前产品契约。

## 15. 实施结果（非规范性台账）

截至 2026-08-22，本 ADR 的生产切换已完成：后端、API、Web 与 reader-core 使用
Book/ReadableResource/ResourceAsset 身份；生产导入只使用 ADR 0018 的 ContinueImport 与
简单单消费者 LibraryImportTask 队列；旧表、旧路由、旧 DTO、旧 importer 与兼容层由架构
守卫持续禁止。Mobile 按本 ADR 范围明确未修改。

为防止开发环境再次丢失修改，用户在实施期间明确要求每个完整子任务使用 Windows Git
提交并立即推送。该交付安全要求取代第 9 节“仅一个最终 commit”的流程约束，但不改变
fresh-only、无双轨、无兼容层和最终生产状态一次性切换的架构决定；这些提交不是可部署的
旧/新兼容阶段。

最终验证证据：

- Backend：Ruff format/check 通过，mypy 411 个源文件零错误，compileall 通过，完整 pytest
  **851 passed**（包含固定源码编译的 MOBI runtime）；
- Web/reader-core：reader-core typecheck、Web typecheck、ESLint 通过，Web tests
  **339 passed**；
- API 合同复验 **143 passed**；导入单元/集成复验 **138 passed**；
- i18n catalog 生成器只提取显式用户可见的后端错误、事件、健康状态、筛选与 provider
  元数据边界，不再把正则、内部 prompt 和普通实现异常当作 Web message key；
  `pnpm i18n:check` 验证 zh-CN/en-US **2017 条**消息及占位符完全对齐。
