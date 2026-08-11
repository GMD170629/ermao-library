# 书库、媒体与书架缺陷修复复测

复测时间：2026-08-11。使用全新的 `STORAGE_ROOT`、真实 Uvicorn、真实后台 Worker 和本地 HTTP 元数据源，按运行时 OpenAPI 对本组接口重新执行真实 TCP 请求；未使用路由 mock 或数据库 mock。

## 修复结果

- 分配的 OpenAPI operations：87；覆盖 87/87。
- 实际 HTTP 请求：113；复核后通过 113/113，失败 0。
- `GET /api/volumes/{volume_id}/pages` 和单页 Range fallback 在缺失持久页索引时只读解析 CBZ，不插入 `LibraryReadingUnit`，不修改 `LibraryVolume.updatedAt`。
- 独立 Engine 持有 SQLite writer lock 时，缺页索引列表请求 1.86ms 返回 200，单页 Range 请求 2.08ms 返回 206；均低于 750ms，数据库快照零变化。
- 审计列出的 11 个 library/shelf JSON 或 multipart 接口均有显式 OpenAPI `requestBody`；已认证空 body 均返回 422，无 raw 500，数据库零变化。
- `POST /api/shelves` 的 OpenAPI 与实际状态均为 201。
- 文件、卷册文件和漫画单页 Range 响应在 OpenAPI 中列出 206，真实请求也返回 206。
- 终态 8 组外键/关系孤儿检查全部为 0；没有缺失的 `LibraryFile` 路径。

## writer-lock 只读回归

| 接口 | 状态/结果 | 耗时 | 数据库变化 |
| --- | --- | ---: | --- |
| `GET /api/works` | 200 | 10.89ms | 无 |
| `GET /api/library/facets` | 200 | 10.24ms | 无 |
| `GET /api/shelves` | 200 | 2.10ms | 无 |
| `GET /api/reader/v3/volumes/{volume_id}/bootstrap` | 200 | 2.06ms | 无 |
| `GET /api/volumes/{volume_id}/pages` | 200 | 1.86ms | 无 |
| `GET /api/volumes/{volume_id}/pages/{page_index}` Range | 206 | 2.08ms | 无 |

媒体 fallback 的固定顺序是：先用只读投影查询卷册、已有页和源文件，结束数据库读会话，再在事务外解析 archive 并返回 DTO。它是历史缺失索引的兼容读取路径，不会把维护写入重新带回 GET。

## 数据写入复核

脚本的通用时间戳保护器原始标出 4 条请求；逐条对照请求语义、代码链路和前后表快照后，均是预期的结构联动，不是回归：

- 卷册移动会更新目标 sibling volume 时间戳；
- 卷册拆分会更新 sibling volume 时间戳；
- 批量 `SET_MEDIA_KIND` 会更新所属 Work 时间戳；
- 批量 `SPLIT` 会更新保留 sibling volume 时间戳。

这 4 条请求状态均为 200，目标行、关系和联动时间戳与原有业务契约一致。因此原始脚本为 109 通过、4 待复核；人工与表级复核后的有效结果为 113 通过、0 失败。

## 自动化门禁

- 聚焦 architecture、媒体 SQLite 锁回归和 OpenAPI 契约：20 passed。
- `tests/test_compat_api.py` 与 `tests/test_audiobook_support.py`：136 passed，5 skipped。
- `compileall`：通过。
- `git diff --check`：通过。
- 主集成阶段通过 `uvx ruff` 对本轮 40 个缺陷修复文件执行 format 及 `E4,E7,E9,F,I,UP` 检查，全部通过；全仓仍有未纳入本缺陷波次的既有格式债务。

## 原始证据

- 复核后总汇：`/tmp/shuku-api-rerun-library-reader-clean.W2hdYG/reports/final-reviewed-summary.json`
- 逐请求运行结果：`/tmp/shuku-api-rerun-library-reader-clean.W2hdYG/reports/runtime-results.json`
- OpenAPI 修复证明：`/tmp/shuku-api-rerun-library-reader-clean.W2hdYG/reports/openapi-fix-proof.json`
- 4 条预期结构联动：`/tmp/shuku-api-rerun-library-reader-clean.W2hdYG/reports/reviewed-structural-side-effects.json`
- 测试脚本：`/tmp/shuku-api-rerun-library-reader-clean.W2hdYG/run_assigned_audit.py`

复测完成后，Uvicorn、Worker 与本地 provider 均已停止；复测端口没有残留监听进程。
