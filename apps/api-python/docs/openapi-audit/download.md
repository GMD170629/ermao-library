# 下载任务 OpenAPI 实际检查

- 检查日期：2026-07-28
- 实际请求接口：9 个（每个 method + path 均至少一次）
- 环境：独立临时 SQLite、临时存储/监控目录、真实 uvicorn TCP 服务
- 数据库证据：每次请求前后反射全部表，比较行数和按行内容摘要

## 逐接口结果

| 接口 | 代码位置 | 文档与代码核查 | 实际能力/响应 | 数据库写入证据 |
|---|---|---|---|---|
| `GET /api/download-tasks`<br>实测 `/api/download-tasks` | `app/modules/download/presentation/http.py:122` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。任务列表只读。 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/download-tasks`<br>实测 `/api/download-tasks` | `app/modules/download/presentation/http.py:141` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody；实际 201 未列入 responses | ✅ HTTP 201，标准成功 envelope。创建真实 HTTP 下载任务；应写任务、最近目标设置和审计事件。 | DownloadTask 0→1，内容变化；SystemEvent 22→23，内容变化；SystemSetting 16→17，内容变化 |
| `DELETE /api/download-tasks/{task_id}`<br>实测 `/api/download-tasks/py_1785233371665169000` | `app/modules/download/presentation/http.py:187` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。删除下载任务并记录审计事件。 | DownloadTask 1→0，内容变化；SystemEvent 28→29，内容变化 |
| `GET /api/download-tasks/{task_id}`<br>实测 `/api/download-tasks/py_1785233371665169000` | `app/modules/download/presentation/http.py:175` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。任务详情只读。 | 无（请求前后全表行数与内容摘要一致） |
| `PUT /api/download-tasks/{task_id}`<br>实测 `/api/download-tasks/py_1785233371665169000` | `app/modules/download/presentation/http.py:200` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。恢复 queued 以执行真实下载。 | DownloadTask 1→1，内容变化；SystemEvent 26→27，内容变化 |
| `POST /api/download-tasks/{task_id}/cancel`<br>实测 `/api/download-tasks/py_1785233371665169000/cancel` | `app/modules/download/presentation/http.py:232` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。取消排队任务。 | DownloadTask 1→1，内容变化；SystemEvent 25→26，内容变化 |
| `POST /api/download-tasks/{task_id}/import`<br>实测 `/api/download-tasks/py_1785233371665169000/import` | `app/modules/download/presentation/http.py:232` | ❌ 实际 400 未列入 responses | ✅ HTTP 400，标准错误 envelope。该接口已退役，实际返回“由监控文件夹自动识别”。 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/download-tasks/{task_id}/retry`<br>实测 `/api/download-tasks/py_1785233371665169000/retry` | `app/modules/download/presentation/http.py:232` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。失败任务重新排队。 | DownloadTask 1→1，内容变化；SystemEvent 24→25，内容变化 |
| `POST /api/download-tasks/{task_id}/start`<br>实测 `/api/download-tasks/py_1785233371665169000/start` | `app/modules/download/presentation/http.py:232` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。从本地 HTTP 服务实际下载 EPUB 到监控目录，并更新任务。 | DownloadTask 1→1，内容变化；SystemEvent 27→28，内容变化 |

## 模块内缺失接口核查

未发现已注册但未进入 OpenAPI 的接口；本模块所有实际注册的 method + path 都能在 `/openapi.json` 中找到，也没有 `include_in_schema=False` 隐藏路由。

这里的“未发现”以 FastAPI 注册表、OpenAPI paths 和路由装饰器入口对账为准；不把普通内部函数误判为 HTTP 接口。
