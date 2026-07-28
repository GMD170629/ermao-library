# 外部下载源（退役） OpenAPI 实际检查

- 检查日期：2026-07-28
- 实际请求接口：17 个（每个 method + path 均至少一次）
- 环境：独立临时 SQLite、临时存储/监控目录、真实 uvicorn TCP 服务
- 数据库证据：每次请求前后反射全部表，比较行数和按行内容摘要

## 逐接口结果

| 接口 | 代码位置 | 文档与代码核查 | 实际能力/响应 | 数据库写入证据 |
|---|---|---|---|---|
| `GET /api/source-search-records`<br>实测 `/api/source-search-records` | `app/modules/download/presentation/sources.py:103` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。退役能力记录列表应为空。 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/source-search-records`<br>实测 `/api/source-search-records` | `app/modules/download/presentation/sources.py:111` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 404，标准错误 envelope。退役来源记录不可创建。 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/source-search-records/create-download-task`<br>实测 `/api/source-search-records/create-download-task` | `app/modules/download/presentation/sources.py:118` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 404，标准错误 envelope。退役搜索结果不可创建下载任务。 | 无（请求前后全表行数与内容摘要一致） |
| `DELETE /api/source-search-records/{record_id}`<br>实测 `/api/source-search-records/missing-record` | `app/modules/download/presentation/sources.py:131` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 404，标准错误 envelope。不存在记录。 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/source-search-records/{record_id}`<br>实测 `/api/source-search-records/missing-record` | `app/modules/download/presentation/sources.py:125` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 404，标准错误 envelope。不存在记录。 | 无（请求前后全表行数与内容摘要一致） |
| `PUT /api/source-search-records/{record_id}`<br>实测 `/api/source-search-records/missing-record` | `app/modules/download/presentation/sources.py:137` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 404，标准错误 envelope。不存在记录。 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/source-search-records/{record_id}/create-download-task`<br>实测 `/api/source-search-records/missing-record/create-download-task` | `app/modules/download/presentation/sources.py:150` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 404，标准错误 envelope。不存在记录。 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/source-search-records/{record_id}/ignore`<br>实测 `/api/source-search-records/missing-record/ignore` | `app/modules/download/presentation/sources.py:143` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 404，标准错误 envelope。不存在记录。 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/source-search-records/{record_id}/save`<br>实测 `/api/source-search-records/missing-record/save` | `app/modules/download/presentation/sources.py:143` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 404，标准错误 envelope。不存在记录。 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/sources`<br>实测 `/api/sources` | `app/modules/download/presentation/sources.py:41` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。退役能力列表应为空；只读。 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/sources`<br>实测 `/api/sources` | `app/modules/download/presentation/sources.py:54` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 410，标准错误 envelope。退役能力创建应明确返回 410。 | 无（请求前后全表行数与内容摘要一致） |
| `DELETE /api/sources/{source_id}`<br>实测 `/api/sources/missing-source` | `app/modules/download/presentation/sources.py:81` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 404，标准错误 envelope。不存在来源。 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/sources/{source_id}`<br>实测 `/api/sources/missing-source` | `app/modules/download/presentation/sources.py:75` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 404，标准错误 envelope。不存在来源。 | 无（请求前后全表行数与内容摘要一致） |
| `PATCH /api/sources/{source_id}`<br>实测 `/api/sources/missing-source` | `app/modules/download/presentation/sources.py:67` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 404，标准错误 envelope。不存在的退役来源应返回 404。 | 无（请求前后全表行数与内容摘要一致） |
| `PUT /api/sources/{source_id}`<br>实测 `/api/sources/missing-source` | `app/modules/download/presentation/sources.py:67` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 404，标准错误 envelope。不存在的退役来源应返回 404。 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/sources/{source_id}/search`<br>实测 `/api/sources/missing-source/search` | `app/modules/download/presentation/sources.py:93` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 404，标准错误 envelope。有效关键词下来源不存在。 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/sources/{source_id}/test`<br>实测 `/api/sources/missing-source/test` | `app/modules/download/presentation/sources.py:87` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 404，标准错误 envelope。退役来源测试不可用。 | 无（请求前后全表行数与内容摘要一致） |

## 模块内缺失接口核查

未发现已注册但未进入 OpenAPI 的接口；本模块所有实际注册的 method + path 都能在 `/openapi.json` 中找到，也没有 `include_in_schema=False` 隐藏路由。

这里的“未发现”以 FastAPI 注册表、OpenAPI paths 和路由装饰器入口对账为准；不把普通内部函数误判为 HTTP 接口。
