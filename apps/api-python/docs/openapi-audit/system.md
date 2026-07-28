# 系统管理与备份 OpenAPI 实际检查

- 检查日期：2026-07-28
- 实际请求接口：13 个（每个 method + path 均至少一次）
- 环境：独立临时 SQLite、临时存储/监控目录、真实 uvicorn TCP 服务
- 数据库证据：每次请求前后反射全部表，比较行数和按行内容摘要

## 逐接口结果

| 接口 | 代码位置 | 文档与代码核查 | 实际能力/响应 | 数据库写入证据 |
|---|---|---|---|---|
| `GET /api/app-config`<br>实测 `/api/app-config` | `app/modules/system/presentation/http.py:75` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。公开应用配置 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/backups`<br>实测 `/api/backups` | `app/modules/system/presentation/http.py:257` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。列出备份归档 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/backups`<br>实测 `/api/backups` | `app/modules/system/presentation/http.py:285` | ❌ 实际 201 未列入 responses | ✅ HTTP 201，标准成功 envelope。创建包含 SQLite 与设置的备份归档 | 无（请求前后全表行数与内容摘要一致） |
| `DELETE /api/backups/{backup_id}`<br>实测 `/api/backups/manual-20260728-095316-3114d8` | `app/modules/system/presentation/http.py:318` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。删除备份归档 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/backups/{backup_id}`<br>实测 `/api/backups/manual-20260728-095316-3114d8` | `app/modules/system/presentation/http.py:269` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取备份详情 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/backups/{backup_id}/download`<br>实测 `/api/backups/manual-20260728-095316-3114d8/download` | `app/modules/system/presentation/http.py:335` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，二进制/流式响应。下载备份 ZIP | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/backups/{backup_id}/restore`<br>实测 `/api/backups/manual-20260728-095316-3114d8/restore` | `app/modules/system/presentation/http.py:298` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。从 ZIP 恢复 SQLite 数据 | SystemSetting 6→6，内容变化 |
| `GET /api/dashboard/system-status`<br>实测 `/api/dashboard/system-status` | `app/modules/system/presentation/http.py:152` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。管理端系统状态聚合 | 无（请求前后全表行数与内容摘要一致） |
| `DELETE /api/management/events`<br>实测 `/api/management/events` | `app/modules/system/presentation/http.py:226` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。清理 info/warning 事件并保留审计事件 | SystemEvent 9→1，内容变化 |
| `GET /api/management/events`<br>实测 `/api/management/events` | `app/modules/system/presentation/http.py:175` | ✅ 响应模型使用受约束的递归 JSON metadata，与持久化事件对应 | ✅ 修复复测 HTTP 200；实际返回 sourceFormat、skipped=list 和嵌套对象，标准成功 envelope。 | 无（只读；SystemEvent 内容未变化） |
| `GET /api/system-settings`<br>实测 `/api/system-settings` | `app/modules/system/presentation/http.py:80` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取系统设置 | 无（请求前后全表行数与内容摘要一致） |
| `PATCH /api/system-settings`<br>实测 `/api/system-settings` | `app/modules/system/presentation/http.py:92` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。恢复前制造数据库差异 | SystemEvent 8→9，内容变化；SystemSetting 6→6，内容变化 |
| `PUT /api/system-settings`<br>实测 `/api/system-settings` | `app/modules/system/presentation/http.py:92` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。PUT 写入 locale 与导入设置并记录事件 | SystemEvent 4→5，内容变化；SystemSetting 3→5，内容变化 |

## 模块内缺失接口核查

未发现已注册但未进入 OpenAPI 的接口；本模块所有实际注册的 method + path 都能在 `/openapi.json` 中找到，也没有 `include_in_schema=False` 隐藏路由。

这里的“未发现”以 FastAPI 注册表、OpenAPI paths 和路由装饰器入口对账为准；不把普通内部函数误判为 HTTP 接口。
