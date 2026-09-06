# ADR 0018：物理 SourceNode 树与可阅读资源导入

- 状态：Accepted
- 范围：SourceNode 扫描、Book/ReadableResource/ResourceAsset 拓扑、ContinueImport

## 决策

运行时的物理与语义关系为：

```text
Library
  └─ LibrarySourceNode
       └─ LibraryBook
            └─ LibraryReadableResource
                 └─ LibraryResourceAsset
  └─ LibraryImportTask
```

`SourceNode` 是 Library 内保存相对路径和最近观察值的扫描快照，不是实时文件系统镜像。
`Book` 是图书聚合，`ReadableResource` 是可独立打开的文件或目录资源，`ResourceAsset` 是
资源实际使用的常规文件。公开内容、Reader、媒体、进度和下载使用 `bookId`、`resourceId`
和 `assetId`；物理路径管理才使用 `sourceNodeId`。

书库组织方式只有 `FLAT` 和 `VOLUMES`。组织方式不能在已有来源节点时原地切换。
符号链接只记录、不跟随；相对路径按精确段边界比较，不能通过大小写、Unicode 归一化或
字符串前缀放宽范围。目录资源的 Asset 必须处于自身范围内；有声书的透明音轨目录规则
由 [ADR 0022](0022-audiobook-directory-resource-boundaries.md) 负责。

首次导入、补齐和用户重试都调用 ContinueImport。生产组合根
`app/bootstrap/readable_resource_pipeline.py` 只构造 `ContinueImport`、
`ScanLibrarySourceTree`、`ProcessReadableResourceImportTask` 和
`SqlAlchemyLibraryImportTaskQueue`。任务种类是 `SCAN_LIBRARY`、`CONTINUE_SOURCE`、
`IMPORT_ASSET`，状态是 `QUEUED`、`RUNNING`、`SUCCEEDED`、`FAILED`；失败由用户再次
ContinueImport，生产路径没有 legacy queue、lease、heartbeat、自动接管或自动重试。

扫描和文件解析在数据库事务外执行；写入使用短 ORM 事务。部分成功保留已写入的有效
SourceNode、Resource 和 Asset，单项失败不回滚其他 READY 资源。手动扫描仅在目录完整遍历
后按 `MissingEntryPolicy` 清理缺失节点，自动扫描保留本轮未见节点。

## Schema 与边界

目标拓扑由 `app/modules/library` 和 `app/modules/imports` 的 capability public ports
实现，Alembic 使用不可变线性 revision，当前 head 为
`0009_reader_v5_opaque_progress`。此 ADR 不定义 Reader v5 的 progress、Mobile handshake
或安全规则；这些契约由对应 ADR 和 `packages/reader-contracts/reader-safety-policy.json`
所有。

## 后果

路径观察、资源识别和导入补齐共享一条可重入管线，避免旧 Work/Version/Volume/File
兼容层与第二套队列。移动、重命名和普通自动扫描不会暗中迁移或删除身份；用户可以再次
继续导入以观察变化并按显式清理策略处理缺失项。
