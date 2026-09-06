# ADR 0019：Book / ReadableResource / ResourceAsset 系统身份

- 状态：Accepted
- 类型：当前运行时身份与跨 capability 边界

## 决策

产品和运行时代码统一使用以下身份：

```text
LibrarySourceNode
    └─ LibraryBook
        └─ LibraryReadableResource
            └─ LibraryResourceAsset
```

SourceNode 只表示物理源树中的 Library 内相对路径。Book 拥有图书级可见性、策展、元数据
和授权；ReadableResource 拥有格式、可读性、启用状态和 Reader 资源身份；ResourceAsset
拥有实际常规文件、角色、顺序、媒体信息和下载/媒体访问身份。

所有公开 Library、Reader、Media、Metadata、Organize、Backup、OPDS、Web 和 Mobile
合同使用 `bookId`、`resourceId`、`assetId`。跨 capability 只通过 public API、application
port 或稳定 contract。旧 Work/Version/Volume/File 不得作为运行时 DTO、路由身份、数据库
查询 owner 或兼容映射；不存在双读、双写、旧接口 shim 或运行时表检测。

导入使用 [ADR 0018](0018-physical-source-tree-book-readable-resource-overlay.md) 的
ContinueImport 管线。导航 projection 使用 [ADR 0012](0012-publication-navigation-cache.md)；
Reader opening、原始格式和安全分别由 [ADR 0014](0014-parser-authoritative-reader-opening.md)、
[ADR 0016](0016-source-preserving-reader-publications.md)、[ADR 0025](0025-reflowable-original-download-before-reading.md)
和 [ADR 0026](0026-versioned-reader-safety-policy-contract.md) 约束。Reader public API 为
v5，progress 使用 [ADR 0028](0028-reader-v5-opaque-position-report.md)。

数据库使用当前线性 Alembic 链，head 为 `0009_reader_v5_opaque_progress`；空数据库由启动
流程创建到当前 head，已知 ancestor 可升级到 head，未知 revision 或已存在的无版本数据库
被拒绝。行为由 `docs/python-backend-runtime.md` 和 `app/db/runner.py` 实现。该身份决策不
要求新旧模型并存，也不保留 legacy importer。

## 当前证据

后端模型位于 `apps/api-python/app/models/library.py` 及各 capability 的 public port；
Reader v5 路由位于 `app/modules/reader/presentation/v5.py`；Web 和 KMP wire tests 使用
同一组三层身份；`tests/test_capability_architecture.py` 守护 capability 私有边界。

## 后果

资源、媒体、阅读进度和下载可以共享稳定身份而不复制旧领域层。历史迁移或归档资料中的旧
名称只能说明背景，不能被当前运行时、API 或产品文案当作事实。
