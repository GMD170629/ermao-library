# ADR 0020：Mobile Book / ReadableResource / ResourceAsset 一次性切换

- 状态：Accepted（实现与真机验收进行中）
- 日期：2026-08-23
- 依据：ADR 0006、0010、0011、0016、0018、0019
- 类型：Mobile-only、破坏性本地契约切换

## 1. 背景

ADR 0019 已将后端、API、Web 与 Reader 服务切换为 Book、ReadableResource 和
ResourceAsset，同时明确把 Mobile 排除在该批次之外。服务端不提供 Work、Version、
Volume、File 兼容路由或旧 ID 映射，因此旧 Mobile 虽能通过 protocol v2 握手，却会在
书库、详情、Reader、进度、书签、书架和下载流程中延迟失败。

本 ADR 完成 ADR 0019 要求的 Mobile 独立切换。它不恢复旧接口，不引入双读、双写或
客户端运行时转换层。

## 2. 唯一 Mobile 身份

Mobile 生产代码只使用以下身份：

```text
Book(bookId)
  └─ ReadableResource(resourceId)
       └─ ResourceAsset(assetId)
```

- 删除 Mobile 的 Version 层；
- Work 改为 Book，Volume 改为 Resource，File 改为 Asset；
- Reader、进度、书签和阅读状态的 owner 是 `resourceId`；
- 音频位置与媒体传输使用 `assetId`；
- 本地精确进度身份为
  `serverIdentity + userId + clientId + bookId + resourceId`；
- 私有下载命名空间仍为
  `serverIdentity + userId + authorizationVersion`。

Mobile 只调用 ADR 0019 的 Book/Resource/Asset HTTP 契约，包括：

```text
GET /api/books
GET /api/books/{bookId}
GET /api/books/{bookId}/resources
GET /api/resources/{resourceId}
GET /api/resources/{resourceId}/assets
GET /api/assets/{assetId}
GET /api/resources/{resourceId}/asset
GET|PUT /api/reader/v4/resources/{resourceId}/...
```

书架、Kindle、详情管理与 metadata 请求同样使用当前 Book/Resource/Asset 路由和请求体。

## 3. 兼容性握手

Mobile 切换建立一个不可与旧客户端混用的新握手代际：

- `protocol.version = 3`；
- `protocol.minimumSupportedClientVersion = 3`；
- `readerSchemaVersion = 4`；
- `librarySchemaVersion = 1`；
- `capabilities.bookResourceAsset = true`；
- `capabilities.bookDetailManagement = false`；第 5 项 Mobile 管理产品范围未在本次决策中启用；
- `capabilities.managedOfflineDownloads = true`。

客户端必须同时验证 protocol、Reader schema、Library schema 与
`bookResourceAsset`。v2 客户端在进入 App Shell 前失败为 `CLIENT_UPDATE_REQUIRED` 或
`UNSUPPORTED_PROTOCOL_VERSION`，不得延迟到业务接口 404。

`managedOfflineDownloads=true` 表示服务端提供经过授权的 Asset/Resource 媒体与 Range
能力；设备下载清单、临时文件、完整性校验、原子发布、清理和离线 Reader handoff 仍完全
由 Mobile 所有。它不表示服务端维护设备下载 manifest 或下载任务。

## 4. 本地数据处理

旧 Work/Version/Volume/File ID 没有可靠到 Book/Resource/Asset 的映射，禁止猜测、按值
复用或请求服务端 alias。Mobile 采用明确的破坏性本地契约替换：

- Android managed-download catalog 升至 schema 3；
- Android Reader SQLite 升至 version 6；
- Android Reader navigation、bookmark、publication 和相关缓存使用新命名空间；
- iOS managed-download manifest/root 升至 contract 3；
- iOS Reader SQLite 升至 contract 7；
- 旧下载、partial、publication、导航、书签、进度和 pending mutation 被清理，不迁移；
- server/user/authorization 变化与显式 logout 必须清理不再授权的私有 Reader/下载状态。

凭据、服务器 profile 和账户偏好不属于旧内容身份，可以保留。

## 5. 保留的下载边界

移动端离线下载继续保留，并遵守 ADR 0010 的设备所有权与安全边界：

1. 从 Reader bootstrap 的 `assets/resourceUrl` 选择原始授权媒体；
2. 只接受 `/api/assets/{assetId}` 或 `/api/resources/{resourceId}/asset`；
3. 流式写入 app-private staging；
4. 校验声明长度、实际长度、MIME/格式和非空响应；
5. 原子发布后才写 completed catalog；
6. 取消、截断、越界、重定向异常和空间不足不得留下可读 completed 工件；
7. Reader 优先使用同一 namespace、Book、Resource 和 Asset 的已验证本地工件。

目录型 Resource 若服务端没有单一可下载原始工件，保持不可下载，不在客户端合成 ZIP、
EPUB 或其他派生出版物。

## 6. 后果与验收

- Mobile 与 protocol v2 服务端不兼容；旧客户端与 protocol v3 服务端不兼容；
- 第一次升级到本契约会丢弃旧离线内容和旧本地阅读状态；
- 测试 fixture 不得继续出现生产 `/api/works`、`/versions`、`/volumes`、`/files` 路由；
- Android 最终验收必须构建 APK、对精确物理设备执行保留数据 replace-install、冷启动并
  验证真实 Book → Resource → Asset → Reader/下载流程；
- iOS 最终验收只允许 `iosArm64`/`iphoneos` 与物理 iPhone/iPad，不使用 Simulator；
- 无物理设备、签名或解锁条件时，只能报告对应运行时门禁待完成，不能用编译结果替代。
