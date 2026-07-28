# 阅读器 V1 退役接口 OpenAPI 实际检查

- 检查日期：2026-07-28
- 实际请求接口：10 个（每个 method + path 均至少一次）
- 环境：独立临时 SQLite、临时存储/监控目录、真实 uvicorn TCP 服务
- 数据库证据：每次请求前后反射全部表，比较行数和按行内容摘要

## 逐接口结果

| 接口 | 代码位置 | 文档与代码核查 | 实际能力/响应 | 数据库写入证据 |
|---|---|---|---|---|
| `GET /api/editions/{edition_id}/progress`<br>实测 `/api/editions/audit-edition-epub/progress` | `app/modules/reader/presentation/http.py:54` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 410，标准错误 envelope。Reader V1 progress 已退役 | 无（请求前后全表行数与内容摘要一致） |
| `PATCH /api/editions/{edition_id}/progress`<br>实测 `/api/editions/audit-edition-epub/progress` | `app/modules/reader/presentation/http.py:59` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 410，标准错误 envelope。Reader V1 progress 写入已退役 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/editions/{edition_id}/progress`<br>实测 `/api/editions/audit-edition-epub/progress` | `app/modules/reader/presentation/http.py:59` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 410，标准错误 envelope。Reader V1 progress 写入已退役 | 无（请求前后全表行数与内容摘要一致） |
| `PUT /api/editions/{edition_id}/progress`<br>实测 `/api/editions/audit-edition-epub/progress` | `app/modules/reader/presentation/http.py:59` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 410，标准错误 envelope。Reader V1 progress 写入已退役 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/reader/preferences`<br>实测 `/api/reader/preferences` | `app/modules/reader/presentation/http.py:28` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 410，标准错误 envelope。Reader V1 已明确退役 | 无（请求前后全表行数与内容摘要一致） |
| `PUT /api/reader/preferences`<br>实测 `/api/reader/preferences` | `app/modules/reader/presentation/http.py:33` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 410，标准错误 envelope。Reader V1 已明确退役 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/reader/preferences/{reader_type}`<br>实测 `/api/reader/preferences/epub` | `app/modules/reader/presentation/http.py:38` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 410，标准错误 envelope。Reader V1 已明确退役 | 无（请求前后全表行数与内容摘要一致） |
| `PATCH /api/reader/preferences/{reader_type}`<br>实测 `/api/reader/preferences/epub` | `app/modules/reader/presentation/http.py:43` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 410，标准错误 envelope。Reader V1 已明确退役 | 无（请求前后全表行数与内容摘要一致） |
| `PUT /api/reader/preferences/{reader_type}`<br>实测 `/api/reader/preferences/epub` | `app/modules/reader/presentation/http.py:43` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 410，标准错误 envelope。Reader V1 已明确退役 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/reader/{edition_id}/bootstrap`<br>实测 `/api/reader/audit-edition-epub/bootstrap` | `app/modules/reader/presentation/http.py:49` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 410，标准错误 envelope。Reader V1 bootstrap 已退役 | 无（请求前后全表行数与内容摘要一致） |

## 模块内缺失接口核查

未发现已注册但未进入 OpenAPI 的接口；本模块所有实际注册的 method + path 都能在 `/openapi.json` 中找到，也没有 `include_in_schema=False` 隐藏路由。

这里的“未发现”以 FastAPI 注册表、OpenAPI paths 和路由装饰器入口对账为准；不把普通内部函数误判为 HTTP 接口。
