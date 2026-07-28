# 健康检查与队列控制 OpenAPI 实际检查

- 检查日期：2026-07-28
- 实际请求接口：10 个（每个 method + path 均至少一次）
- 环境：独立临时 SQLite、临时存储/监控目录、真实 uvicorn TCP 服务
- 数据库证据：每次请求前后反射全部表，比较行数和按行内容摘要

## 逐接口结果

| 接口 | 代码位置 | 文档与代码核查 | 实际能力/响应 | 数据库写入证据 |
|---|---|---|---|---|
| `GET /api/__db-ping`<br>实测 `/api/__db-ping` | `app/modules/system/presentation/health.py:94` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。数据库探针 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/health`<br>实测 `/api/health` | `app/modules/system/presentation/health.py:64` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。基础健康摘要 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/system/health`<br>实测 `/api/system/health` | `app/modules/system/presentation/health.py:84` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。详细健康检查 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/system/health/runs`<br>实测 `/api/system/health/runs` | `app/modules/system/presentation/health.py:111` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 201，标准成功 envelope。创建或复用健康检查运行 | SystemHealthRun 0→1，内容变化 |
| `GET /api/system/health/runs/{run_id}`<br>实测 `/api/system/health/runs/health_9deff9183f394f0ca40e0204949f8622` | `app/modules/system/presentation/health.py:137` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取健康检查运行结果 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/system/health/runs/{run_id}/events`<br>实测 `/api/system/health/runs/health_9deff9183f394f0ca40e0204949f8622/events` | `app/modules/system/presentation/health.py:160` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，二进制/流式响应。读取健康检查 SSE 直至终态 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/system/log-settings`<br>实测 `/api/system/log-settings` | `app/modules/system/presentation/health.py:295` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取日志容量设置 | 无（请求前后全表行数与内容摘要一致） |
| `PUT /api/system/log-settings`<br>实测 `/api/system/log-settings` | `app/modules/system/presentation/health.py:316` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。更新日志容量并写 SystemSetting/SystemEvent | SystemEvent 7→8，内容变化；SystemSetting 5→6，内容变化 |
| `GET /api/system/queue-operations/{operation_id}`<br>实测 `/api/system/queue-operations/queue_04254716b4a546179d6a04fe9abe07c7` | `app/modules/system/presentation/health.py:270` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取队列控制操作 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/system/queues/import/restart`<br>实测 `/api/system/queues/import/restart` | `app/modules/system/presentation/health.py:238` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 202，标准成功 envelope。创建导入队列重启控制操作 | QueueControlOperation 0→1，内容变化 |

## 模块内缺失接口核查

未发现已注册但未进入 OpenAPI 的接口；本模块所有实际注册的 method + path 都能在 `/openapi.json` 中找到，也没有 `include_in_schema=False` 隐藏路由。

这里的“未发现”以 FastAPI 注册表、OpenAPI paths 和路由装饰器入口对账为准；不把普通内部函数误判为 HTTP 接口。
