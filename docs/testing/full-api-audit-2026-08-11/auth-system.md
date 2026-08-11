# 认证、用户、偏好、系统与健康 API 报告

- OpenAPI operations：48
- 真实覆盖：48/48
- 主流程：48 项均得到预期 2xx
- 实例：真实 uvicorn `127.0.0.1:18101`、真实 Worker、全新 SQLite
- 逐 operation：见[总执行矩阵](./api-operation-matrix.md)中的 `auth`、`users`、`preferences`、`system`、`health`

## 数据库与事务断言

- setup 同事务创建 `User + UserPreference(locale) + Session`。
- 登录只新增 Session；refresh 只条件更新当前 Session；密码修改和密码重置集合删除该用户全部 Session。
- 用户创建、授权更新、删除与 `SystemEvent` 同事务；删除用户级联个人数据，并匿名化历史审计引用。
- 六项偏好使用集合 upsert，`User.updatedAt` 未改变。
- 系统设置、OPDS、日志限制均与审计事件同事务；SMTP 密码实际保存但响应不泄露。
- event clear 集合删除后保留一条 `events.cleared`。
- backup restore 在维护屏障内恢复 live DB；备份后 marker 被删除，备份前设置和登录 Session 保留。
- health run 达到终态，version、finishedAt 和完成事件一致；queue restart 经真实 Worker 达到 `completed`。
- 12 个关键 GET 在独立 writer lock 下均为 200，0.94–10.08ms，相关表计数和内容不变。

## 首轮缺陷与修复结果

以下问题均已修复并在全新实例重新覆盖 48/48；详见[修复复测报告](./auth-system-fix-rerun.md)。

### P0：头像 DB/文件系统非原子（已修复）

成功上传红色头像后，外部连接持有 writer lock，再上传蓝色头像：

- HTTP 500，耗时 10.624s；
- `User.avatarPath` 回滚并保持原值；
- 头像文件 SHA 从 `b8866e…` 变为 `07e0ac…`。

调用链为 auth upload route 先 `os.replace()`，再执行账户 avatarPath 写事务；数据库失败没有文件补偿。失败请求因此改变了用户可见内容。

最终流程使用唯一版本文件和 250ms 短写；失败时新文件被丢弃，旧路径/哈希不变。

### P1：dashboard schema 拒绝合法投影（已修复）

新库无监控目录时 dashboard 200；真实创建 `mediaKindPolicy=MIXED` 的启用目录后，同一 GET 返回 500。数据库行有效且未被错误请求修改，Pydantic 拒绝 `enabledMonitorFolders.0.mediaKindPolicy`。存在完成的 ImportTask 时还会拒绝 `mediaKindPolicy`、`recognizedMetadata`、`sourceKey`。

最终 dashboard 合同显式包含目录策略、任务来源及受约束的 recognized metadata 投影。

### P2：整理调度器 busy 日志未收敛（已修复）

锁竞争下普通后台写能在约 250–330ms 退让，但 OrganizerScheduler 仍输出完整 `OperationalError: database is locked` 堆栈。

最终该调度器使用实例级 30 秒限频，锁释放后自动重试；完整堆栈已消失。

## 原始证据

- 模块报告：`/tmp/shuku-auth-system-api-audit.9TFrWi/auth-system-api-report.md`
- 结构化结果：`/tmp/shuku-auth-system-api-audit.9TFrWi/auth-system-api-results.json`
- 头像冲突：`/tmp/shuku-auth-system-api-audit.9TFrWi/avatar-contention-result.json`
- dashboard 复现：`/tmp/shuku-auth-system-api-audit.9TFrWi/dashboard-repro-with-folder-response.txt`
- 日志：`/tmp/shuku-auth-system-api-audit.9TFrWi/uvicorn.log`、`worker.log`
