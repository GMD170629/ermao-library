# 2026-08-11 全系统真实 API 与事务审计

## 结论

本轮按运行中服务的 OpenAPI 完成 **152 paths / 209 operations，覆盖 209/209，遗漏 0**。所有覆盖请求均经过真实 uvicorn TCP；写链路使用真实 SQLite，队列链路使用真实 Worker，下载、SMTP、Kindle、备份恢复、Range 文件读取均走真实适配器或本地可控服务，没有使用 TestClient、ASGITransport 或 mock 代替 HTTP。

首轮确认了 5 类产品缺陷，其中两项直接违背本次“GET 零写入 / 数据库失败不发布文件”的事务目标。修复后重新创建三组全新实例，按相同清单复测 **48/48 + 87/87 + 74/74 = 209/209**；下表问题均已关闭：

| 严重度 | 首轮缺陷 | 最终复测 |
|---|---|---|
| P0 | 头像先发布文件、后写数据库且无补偿 | 已修复：writer lock 下 324ms 返回稳定 503；数据库路径、可见 SHA 不变，无 part/孤儿文件 |
| P0 | `GET /api/volumes/{volume_id}/pages` 懒建漫画页索引 | 已修复：缺索引 fallback 在读 Session 关闭后解析；锁下 1.86ms/200，ReadingUnit 与 Volume.updatedAt 不变 |
| P1 | HTTP 响应 schema 落后于数据库投影 | 已修复：OPF status、含监控目录/任务的 dashboard 均为 200 |
| P1 | 新库没有默认整理策略行 | 已修复：首次 GET 返回稳定默认投影，连续 GET 零 DML，仍不创建策略行 |
| P1 | OpenAPI 请求体/响应状态不完整 | 已修复：实际消费 body 的路由使用显式模型，空 body 为 4xx 而非 raw 500；Shelf 201 与 Range 206 已声明 |
| P2 | OrganizerScheduler 未统一处理 database busy | 已修复：12 秒锁内只记录一次限频 deferred，无堆栈；释放后保留状态并自动成功 |

复测期间还发现并修复了一个条件性备份问题：`ImportTask.recognizedMetadata` 含字典时，恢复前关系校验曾把 JSON 放入 `set` 而返回 500；修复后含嵌套 JSON 的真实 restore 返回 200，内容完整保留。

完整逐操作结果见 [209 项执行矩阵](./api-operation-matrix.md)。

## 模块报告

- [认证、用户、偏好、系统与健康](./auth-system.md)：48/48
- [书库、媒体、书架与 Reader](./library-reader.md)：87/87
- [导入、元数据、整理、下载与 Kindle](./queues-metadata.md)：74/74
- [认证/系统修复复测](./auth-system-fix-rerun.md)：48/48
- [书库/媒体修复复测](./library-media-shelf-fix-rerun.md)：87/87，113 次真实请求
- [队列/元数据修复复测](./queues-metadata-fix-rerun.md)：74/74

## 关键事务结论

- 外部 SQLite writer 持锁时，认证、系统设置、作品列表、facet、书架、Reader v3 bootstrap、数据源和 metadata provider 等关键 GET 均在 0.9–10.7ms 返回，表快照无变化。数据源请求不再和后台队列争写锁。
- session refresh 使用短写连接：锁下约 324ms 返回可重试 503，Session 行不变；释放后约 5ms 成功，只更新当前 Session。
- 真实 EPUB 导入后，Work/Media/Volume/File/ReadingUnit/Facet/关系表一致；元数据更新显式写入 preparation，Worker 完成后队列计数归零，并保持 Work 之外的无关 updatedAt 不变。
- Reader v3 progress 使用 sequence CAS；并发真实请求最终保留较高 sequence。Progress/History/Bookmark 正确，Work/Volume.updatedAt 不变。
- 系统设置与 SystemEvent、用户与偏好、Shelf 与 ShelfWork、Kindle task 与事件均验证为同一事务；失败探针未留下部分数据库行。
- 最终书库审计数据库的外键/孤儿检查为 0，12/12 个数据库引用文件存在。
- 含嵌套 `recognizedMetadata` 的 backup create/download/live restore/delete 全链路通过，恢复事务未损坏用户、目录、任务或设置。

## 方法与范围

1. 每个审计实例使用新的临时 `STORAGE_ROOT` 和独立端口启动 uvicorn。
2. 从该实例的 `/openapi.json` 获取实时 operation 清单，并按 tag 唯一分配。
3. 先构造合法用户、监控目录、EPUB/CBZ、书架、下载、SMTP、Kindle 等数据，再逐 operation 发真实 HTTP 请求。
4. 每个关键请求前后使用 SQLAlchemy typed select 核对行数、内容、外键关系和 updatedAt；GET 额外验证零 DML。
5. 使用第二个独立 Engine 持有 SQLite writer lock，验证前台 GET、短写退让、Worker 恢复与待处理状态。
6. 额外严格按 OpenAPI 发送“文档没有 requestBody 的空请求”，检查契约是否能独立指导客户端。
7. 审计完成后停止全部 API、Worker、本地 HTTP 与 SMTP 服务，并保留临时数据库和日志。

## 原始证据

- 认证/系统：`/tmp/shuku-auth-system-api-audit.9TFrWi`
- 书库/Reader：`/tmp/shuku-api-audit-library-reader-POGX9K`
- 队列/元数据：`/tmp/shuku-api-audit-dXLh9i`
- 根审计实例：`/tmp/shuku-full-api-root.iZHc3S`

这些目录包含 OpenAPI 快照、逐请求 JSON、SQLite 数据库、文件哈希、writer-lock 结果、uvicorn/Worker 日志和停止证明。

## 最终集成门禁

- 三组修复后 live OpenAPI：48/48、87/87、74/74，共 209/209。
- 主集成聚焦门禁：45 passed。
- 完整后端测试：1058 passed、5 个既有 skip、0 failed，耗时 239.91s。
- OpenAPI quality 与 response DTO constrained schema：通过。
- Python `compileall`、`git diff --check`：通过。
- 本轮 40 个缺陷修复文件的 Ruff format 及 `E4,E7,E9,F,I,UP`：通过。
- 全仓 Ruff format 仍报告 82 个未纳入本缺陷波次的既有未格式化文件；没有全仓重写用户的脏工作区，也没有降低规则或新增 blanket suppression。
- 唯一测试 warning 是环境中 FastAPI `TestClient` 对旧 `httpx` 适配层的 `StarletteDeprecationWarning`；真实 API 测试不使用该适配层。
- 审计端口 `18100–18113`（本轮使用的子集）均已停止；用户原有的 `8000` 实例未被触碰。
