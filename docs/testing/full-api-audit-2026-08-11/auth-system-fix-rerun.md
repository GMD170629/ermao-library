# 认证、系统、OPDS 与备份缺陷修复复测

复测时间：2026-08-11。使用全新的 `STORAGE_ROOT`、真实 Uvicorn、真实 Import Worker 和真实 SQLite，从运行中服务的 OpenAPI 获取操作清单后逐项发送 TCP 请求；没有用 TestClient、ASGITransport 或数据库 mock 代替本轮真实 API 复测。

## 结论

- OpenAPI 分配操作：48。
- 覆盖：48/48，遗漏 0，额外操作 0。
- 分布：auth 15、users 6、preferences 2、health 10、system 15。
- 48 项状态、响应合同和逐链路数据库断言全部通过。
- 备份创建、详情、真实 ZIP 下载、含嵌套 JSON 的 live restore 和删除均通过。
- 复测结束后 Uvicorn 与本轮 Worker 已停止，没有残留 `18112` 端口监听进程。

## 修复项

### 头像数据库与文件发布一致性

头像不再覆盖固定的已发布文件。新流程为：

1. 在目标目录生成唯一版本的同目录 `.part` 文件；
2. 完成图片归一化、WebP 保存和重新打开校验；
3. 原子发布唯一版本文件，但数据库仍引用旧版本；
4. 使用 250ms 短写连接切换 `User.avatarPath`；
5. 数据库成功后删除旧文件；数据库失败则删除未引用的新文件。

删除头像也改为先提交数据库引用变更，成功后再清理旧文件，避免数据库失败但可见文件已消失。

独立 Engine 持有 SQLite writer lock 时，真实 `POST /api/auth/avatar`：

- 0.3243 秒返回 503；
- 稳定错误码为 `AVATAR_UPDATE_DEFERRED`；
- `User.avatarPath` 保持原值；
- `GET /api/auth/avatar` 返回内容的 SHA 保持不变；
- 头像目录只存在数据库仍引用的旧版本，没有 `.part` 或未引用新版本残留。

### Dashboard 合法投影

Dashboard 响应合同已包含：

- `enabledMonitorFolders[].mediaKindPolicy`；
- `currentImportTask/latestImportTask.mediaKindPolicy`；
- `recognizedMetadata`；
- `sourceKey`。

真实数据库构造 `mediaKindPolicy=COMIC` 的启用目录及包含字典、列表 JSON 的完成 ImportTask 后，`GET /api/dashboard/system-status` 返回 200。外部 writer lock 下仍在 8.9ms 返回，响应中的 folder policy、source key 和 recognized metadata 与数据库完全一致。

### 日志设置 OpenAPI requestBody

`PUT /api/system/log-settings` 现在使用显式 `UpdateLogSettingsRequest` Pydantic 模型。运行时 OpenAPI 已声明 `application/json` request body；真实请求返回 200，并原子更新日志容量设置和审计事件。

### OPDS GET 零 DML

OPDS 漫画页 fallback 改为固定顺序：

1. 只读查询卷册、已有页和源文件投影；
2. 关闭对应数据库 Session；
3. 在事务外解析 CBZ archive；
4. 使用只读 DTO 返回媒体类型或指定页。

OPDS Basic Auth 的成功、失败和限流审计不再插入 `SystemEvent`，改为不含密码的结构化日志，从而保证认证后的 GET 也不会竞争数据库写锁。

在数据库没有任何持久页索引、外部 Engine 持有 writer lock 时，真实 `GET /opds/v1.2/volumes/opds-live-volume/pages/0`：

- 30.2ms 返回 200、`image/png`；
- 读取真实 CBZ 中的页面；
- `LibraryReadingUnit` 数量保持 0 → 0；
- 请求期间没有 DML，也没有修改卷册时间戳。

### 含 JSON 的备份恢复

第一次真实 48 项复测在 restore 阶段发现：恢复前关系校验把 `ImportTask.recognizedMetadata` 字典加入 `set`，触发 `TypeError: unhashable type: 'dict'`。修复后，关系校验只为显式外键目标列建立值集合；普通 JSON、列表和字典字段仍按列类型准备，但不参与外键成员判断。全部解析、类型转换和关系校验继续在 live 写事务外完成，live restore 仍由维护屏障保护的 SQL-only 原子事务执行。

最终复测中：

- `POST /api/backups` 返回 201；
- 真实下载内容以 ZIP `PK` 文件头开始；
- `POST /api/backups/{backup_id}/restore` 返回 200；
- restore 后 ImportTask 状态仍为 `COMPLETED`；
- `recognizedMetadata.subjects` 列表及其他嵌套 JSON 完整保留；
- `DELETE /api/backups/{backup_id}` 返回 200。

## writer-lock 复测

| 链路 | 状态 | 耗时 | 数据库/文件断言 |
| --- | ---: | ---: | --- |
| `POST /api/auth/avatar` | 503 | 324.3ms | avatarPath、可见 SHA 不变；无 part/孤儿文件 |
| `GET /api/dashboard/system-status` | 200 | 8.9ms | 合法 folder/task 投影完整；零写入 |
| `GET /opds/v1.2/volumes/{volume_id}/pages/0` | 200 | 30.2ms | 真实 CBZ fallback；ReadingUnit 0→0 |

最终 API 与 Worker 日志没有 `ERROR`、`Traceback`、`Internal Server Error` 或未处理的 `database is locked`。头像 503 是预期的短写退让合同。

## 数据库终态断言

48 项真实请求和 backup restore 完成后，直接使用 SQLAlchemy typed select 检查 live SQLite：

- `User=1`，临时 member 已按显式删除请求移除；
- 管理员名称仍为 `Live Admin Updated`；
- `SystemSetting=6`、`SystemEvent=2`，与最终设置和审计步骤一致；
- Dashboard ImportTask 为 `COMPLETED`；
- `recognizedMetadata` 的字典和列表值与备份前一致；
- MonitorFolder 的 `mediaKindPolicy=COMIC`；
- backup restore 没有损坏登录用户、目录、任务或设置数据。

## 自动化门禁

- 认证、系统、OPDS、事务聚焦回归：90 passed。
- SQLite 与备份恢复回归：24 passed。
- 写事务与能力边界架构门禁：40 passed。
- Python `compileall`：通过。
- `git diff --check`：通过。
- 主集成阶段通过 `uvx ruff` 对本轮 40 个缺陷修复文件执行 format 及 `E4,E7,E9,F,I,UP` 检查，全部通过；全仓仍有未纳入本缺陷波次的既有格式债务。

## 原始证据

- 48 项逐 operation 结果：`/tmp/shuku-auth-system-fix-live-final.GSfyj5/live-48-results.json`
- 头像锁竞争：`/tmp/shuku-auth-system-fix-live-final.GSfyj5/avatar-lock-result.json`
- Dashboard 锁下结果：`/tmp/shuku-auth-system-fix-live-final.GSfyj5/dashboard-lock-result.json`
- OPDS 缺页锁下结果：`/tmp/shuku-auth-system-fix-live-final.GSfyj5/opds-page-lock-result.json`
- Uvicorn 日志：`/tmp/shuku-auth-system-fix-live-final.GSfyj5/api.log`
- Worker 日志：`/tmp/shuku-auth-system-fix-live-final.GSfyj5/worker.log`
- 复测 SQLite：`/tmp/shuku-auth-system-fix-live-final.GSfyj5/storage/database/shuku.sqlite3`

证据目录保留了 OpenAPI 逐操作状态、响应断言、数据库终态、文件哈希、writer-lock 耗时和运行日志，可用于后续发布复核。
