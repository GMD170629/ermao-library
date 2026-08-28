# ADR 0020：Mobile Book / ReadableResource / ResourceAsset 一次性切换

- 状态：Accepted（实现与真机验收进行中）
- 日期：2026-08-23
- 依据：ADR 0006、0011、0014、0015、0016、0018、0019
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
- `capabilities.bookDetailManagement = true`；该历史详情管理依据已于 2026-08-26 废弃，当前动作范围以 Web Work Detail 实现和权限过滤为准；
- `capabilities.managedOfflineDownloads = true`。

客户端必须同时验证 protocol、Reader schema、Library schema 与
`bookResourceAsset`。v2 客户端在进入 App Shell 前失败为 `CLIENT_UPDATE_REQUIRED` 或
`UNSUPPORTED_PROTOCOL_VERSION`，不得延迟到业务接口 404。

`managedOfflineDownloads=true` 表示服务端提供经过授权的 Asset/Resource 媒体与 Range
能力；设备下载清单、临时文件、完整性校验、原子发布、清理和离线 Reader handoff 仍完全
由 Mobile 所有。它不表示服务端维护设备下载 manifest 或下载任务。

## 4. 本地数据处理

当前流式阅读迁移不改变 Book/Resource/Asset 身份、进度含义或书签合同。
保留用户主动下载、本地导入、书签、精确进度及待同步变更。已有下载清单在原位置
验证并升级结构，不重复复制原文件，不清空损坏清单来伪装成功。

旧自动在线副本与未完成临时文件只有在元数据能确认其来源时才能清理；来源不明的
文件必须保留。用户显式退出账号时仍按既有授权边界清除该账号私有数据。
凭据、服务器 profile 和账户偏好不受本次阅读迁移影响。

## 5. 保留的下载边界

移动端 completed 下载继续保留。设备拥有 managed-download manifest 与 app-private
内容目录，命名空间为 `serverIdentity + userId + authorizationVersion`。该清单不是服务端
页面快照，也不提供独立授权；明确 logout、身份或授权 namespace 变化时必须清理。下载
与 Reader 访问遵守以下边界：

1. 从 Library Resource/Asset 公开合同取得原文件下载描述，不启动 Reader；
2. 只接受 `/api/assets/{assetId}` 或 `/api/resources/{resourceId}/asset`；
3. 流式写入 app-private staging；
4. 校验声明长度、实际长度、MIME/格式和非空响应；
5. 原子发布后，将 completed 任务与文件引用在同一 catalog 记录中原子登记；发布后中断可通过实际文件恢复登记；
6. 取消、截断、越界、重定向异常和空间不足不得留下可读 completed 工件；
7. 在线 Reader 只使用 Publication、漫画分页或 PDF Range；离线入口通过 Downloads 公开接口读取同一 namespace 的已验证工件，既不复制原文件，也不补下载。

只有通过完整性和格式验证并已原子发布的工件可以标记为 completed。partial、取消、长度
不符、格式不符、缺失或发布失败的文件均不可读。弱 ETag 不得充当 `If-Range` 验证器；在
续传前必须核对原文件版本、实际 partial 长度及 Range 响应；版本变化创建独立任务，保留已有 completed 文件。

Download Center 是 completed 本地下载、活动任务和失败任务的唯一发现入口，按 Book
组织并可搜索本地 Book、作者与 Resource 元数据。Library 不提供 downloaded-only 筛选，
不得通过网络 Library 列表推断设备清单。

Shared KMP 的 `DownloadResourceRuntime` 是唯一下载业务入口，拥有任务创建、去重、暂停恢复、重试、鉴权传输、校验和完成登记。
单项、批量与下载中心都调用同一入口；IMAGE_DIR 的各页复用同一传输机制，仅资源组织不同。Android/iOS 拥有 app-private 文件、staging、原子 manifest 持久化、平台
生命周期协调、原生导航和破坏性确认。后台继续下载只有在 Cookie、base path、TLS、进程
终止和锁屏行为通过对应物理设备验收后才能作为发布能力。

IMAGE_DIR 将原图作为有序页面集原子保存，不合成 ZIP、EPUB 或其他派生出版物。

## 6. 后果与验收

- Mobile 与 protocol v2 服务端不兼容；旧客户端与 protocol v3 服务端不兼容；
- 流式阅读迁移必须保留主动下载与既有精确阅读状态；
- 测试 fixture 不得继续出现生产 `/api/works`、`/versions`、`/volumes`、`/files` 路由；
- Android 最终验收必须构建 APK、对精确物理设备执行保留数据 replace-install、冷启动并
  验证真实 Book → Resource → Asset → Reader/下载流程；
- iOS 最终验收只允许 `iosArm64`/`iphoneos` 与物理 iPhone/iPad，不使用 Simulator；
- 无物理设备、签名或解锁条件时，只能报告对应运行时门禁待完成，不能用编译结果替代。
