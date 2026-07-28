# 邮件与 Kindle OpenAPI 实际检查

- 检查日期：2026-07-28
- 实际请求接口：10 个（每个 method + path 均至少一次）
- 环境：独立临时 SQLite、临时存储/监控目录、真实 uvicorn TCP 服务
- 数据库证据：每次请求前后反射全部表，比较行数和按行内容摘要

## 逐接口结果

| 接口 | 代码位置 | 文档与代码核查 | 实际能力/响应 | 数据库写入证据 |
|---|---|---|---|---|
| `GET /api/email-settings`<br>实测 `/api/email-settings` | `app/modules/kindle/presentation/http.py:118` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取邮件设置。 | 无（请求前后全表行数与内容摘要一致） |
| `PUT /api/email-settings`<br>实测 `/api/email-settings` | `app/modules/kindle/presentation/http.py:129` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。保存 SMTP 配置；密码不得出现在响应/事件。 | SystemEvent 29→30，内容变化；SystemSetting 17→25，内容变化 |
| `POST /api/email-settings/smtp-test`<br>实测 `/api/email-settings/smtp-test` | `app/modules/kindle/presentation/http.py:160` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody；实际 400 未列入 responses | ⚠️ HTTP 400，标准错误 envelope。实际连接本机关闭端口，确认失败路径正常；本次没有可用 SMTP 服务，未声称发信成功。 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/kindle-send-tasks`<br>实测 `/api/kindle-send-tasks` | `app/modules/kindle/presentation/http.py:219` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取当前用户发送任务列表。 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/kindle-send-tasks`<br>实测 `/api/kindle-send-tasks` | `app/modules/kindle/presentation/http.py:258` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody；实际 201 未列入 responses | ✅ HTTP 201，标准成功 envelope。基于真实库内 EPUB 文件创建个人 Kindle 发送任务。 | KindleSendTask 0→1，内容变化；SystemEvent 30→31，内容变化 |
| `DELETE /api/kindle-send-tasks/{task_id}`<br>实测 `/api/kindle-send-tasks/kindle_1785233373587111000` | `app/modules/kindle/presentation/http.py:401` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。删除已取消的终态发送记录。 | KindleSendTask 1→0，内容变化；SystemEvent 34→35，内容变化 |
| `POST /api/kindle-send-tasks/{task_id}/cancel`<br>实测 `/api/kindle-send-tasks/kindle_1785233373587111000/cancel` | `app/modules/kindle/presentation/http.py:353` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。取消 queued 任务。 | KindleSendTask 1→1，内容变化；SystemEvent 31→32，内容变化 |
| `POST /api/kindle-send-tasks/{task_id}/retry`<br>实测 `/api/kindle-send-tasks/kindle_1785233373587111000/retry` | `app/modules/kindle/presentation/http.py:374` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。把 cancelled 任务重新排队。 | KindleSendTask 1→1，内容变化；SystemEvent 32→33，内容变化 |
| `GET /api/kindle-settings`<br>实测 `/api/kindle-settings` | `app/modules/kindle/presentation/http.py:180` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取当前用户 Kindle 设置。 | 无（请求前后全表行数与内容摘要一致） |
| `PUT /api/kindle-settings`<br>实测 `/api/kindle-settings` | `app/modules/kindle/presentation/http.py:200` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。保存当前用户 Kindle 邮箱。 | UserPreference 3→4，内容变化 |

## 模块内缺失接口核查

未发现已注册但未进入 OpenAPI 的接口；本模块所有实际注册的 method + path 都能在 `/openapi.json` 中找到，也没有 `include_in_schema=False` 隐藏路由。

这里的“未发现”以 FastAPI 注册表、OpenAPI paths 和路由装饰器入口对账为准；不把普通内部函数误判为 HTTP 接口。
