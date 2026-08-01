# 阅读器 V2 OpenAPI 实际检查

- 检查日期：2026-07-28
- 实际请求接口：6 个（每个 method + path 均至少一次）
- 环境：独立临时 SQLite、临时存储/监控目录、真实 uvicorn TCP 服务
- 数据库证据：每次请求前后反射全部表，比较行数和按行内容摘要

## 逐接口结果

| 接口 | 代码位置 | 文档与代码核查 | 实际能力/响应 | 数据库写入证据 |
|---|---|---|---|---|
| `GET /api/reader/v2/editions/{edition_id}/bookmarks`<br>实测 `/api/reader/v2/editions/audit-edition-epub/bookmarks` | `app/modules/reader/presentation/v2.py:769` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取空书签列表 | 无（请求前后全表行数与内容摘要一致） |
| `PUT /api/reader/v2/editions/{edition_id}/bookmarks`<br>实测 `/api/reader/v2/editions/audit-edition-epub/bookmarks` | `app/modules/reader/presentation/v2.py:803` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。替换书签集合并写 ReaderBookmark（按 OpenAPI kind 字段） | ReaderBookmark 0→1，内容变化 |
| `GET /api/reader/v2/editions/{edition_id}/bootstrap`<br>实测 `/api/reader/v2/editions/audit-edition-epub/bootstrap` | `app/modules/reader/presentation/v2.py:500` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。Reader V2 EPUB bootstrap | LibraryConsumptionState 0→1，内容变化；ReaderBookPreference 0→1，内容变化 |
| `PUT /api/reader/v2/editions/{edition_id}/progress`<br>实测 `/api/reader/v2/editions/audit-edition-epub/progress` | `app/modules/reader/presentation/v2.py:1055` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。保存单调进度并写 progress/cursor/consumption state | LibraryConsumptionState 1→1，内容变化；LibraryReadingProgress 0→1，内容变化；ReaderProgressCursor 0→1，内容变化 |

## 模块内缺失接口核查

未发现已注册但未进入 OpenAPI 的接口；本模块所有实际注册的 method + path 都能在 `/openapi.json` 中找到，也没有 `include_in_schema=False` 隐藏路由。

这里的“未发现”以 FastAPI 注册表、OpenAPI paths 和路由装饰器入口对账为准；不把普通内部函数误判为 HTTP 接口。
