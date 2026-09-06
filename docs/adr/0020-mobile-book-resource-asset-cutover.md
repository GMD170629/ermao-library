# ADR 0020：Mobile Book / ReadableResource / ResourceAsset 身份与协议

- 状态：Accepted
- 类型：Mobile 公共身份、兼容握手和本地下载边界

## 决策

Mobile 生产代码与 [ADR 0019](0019-book-readable-resource-system-cutover.md) 共享唯一
身份：

```text
Book(bookId) → ReadableResource(resourceId) → ResourceAsset(assetId)
```

Reader、进度和书签的内容 owner 是 `resourceId`；媒体、音频和原始文件传输使用
`assetId`。书架、详情、metadata、Kindle、备份、OPDS 和下载均使用当前 Book/Resource/Asset
contract，不维护 Work/Version/Volume/File 转换层。

兼容握手由 `apps/api-python/app/modules/mobile/domain/compatibility.py` 唯一生成：

- `protocol.version = 3`，`minimumSupportedClientVersion = 3`；
- `readerSchemaVersion = 5`，`librarySchemaVersion = 1`；
- `readerV5`、`mediaRange`、`managedOfflineDownloads` 和 `bookResourceAsset` 能力必须
  与实际服务端能力一致；`bookDetailManagement` 是能力字段，不是绕过资源授权的全局开关。

Mobile 必须在进入业务 Shell 前验证握手，旧 protocol/client 直接失败。当前 Reader 路径
使用 `/api/reader/v5/resources/{resourceId}/...`，Library/Media 路径使用
`/api/books`、`/api/resources` 和 `/api/assets`；不注册旧身份兼容路由。

本地 Downloads 是完整原始文件的唯一设备 owner。KMP `DownloadResourceRuntime` 统一任务
创建、去重、鉴权传输、校验和完成登记；平台 adapter 负责 app-private staging、原子发布、
生命周期和文件清理。Reader 只观察或打开同一合格工件，不复制文件、不拼第二套下载流程，
也不持久化派生 EPUB、ZIP 或解包目录。下载 artifact 由授权 namespace、resource/asset identity
和版本/长度隔离；账号或授权 namespace 变化时按现有安全边界清理。

## 当前证据

KMP server and Reader repositories use v5 paths and `ReaderPositionReport`; the backend
compatibility contract and `apps/mobile/shared` tests pin protocol 3/schema 5. Native Android
and iOS wrappers own platform navigation and file handling; shared application code owns the
download workflow.

## 后果

Mobile 与旧协议不兼容是显式握手结果，而不是延迟到业务 404。没有物理设备、签名或解锁
条件时只能记录运行时验收待完成，不能用编译或模拟器结果宣称设备行为已通过。
