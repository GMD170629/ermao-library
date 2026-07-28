# 用户管理 OpenAPI 实际检查

- 检查日期：2026-07-28
- 实际请求接口：6 个（每个 method + path 均至少一次）
- 环境：独立临时 SQLite、临时存储/监控目录、真实 uvicorn TCP 服务
- 数据库证据：每次请求前后反射全部表，比较行数和按行内容摘要

## 逐接口结果

| 接口 | 代码位置 | 文档与代码核查 | 实际能力/响应 | 数据库写入证据 |
|---|---|---|---|---|
| `GET /api/admin/users`<br>实测 `/api/admin/users` | `app/modules/auth/presentation/users.py:188` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。列出用户 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/admin/users`<br>实测 `/api/admin/users` | `app/modules/auth/presentation/users.py:236` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 201，标准成功 envelope。创建普通用户、locale 偏好与审计事件 | SystemEvent 0→1，内容变化；User 1→2，内容变化；UserPreference 1→2，内容变化 |
| `DELETE /api/admin/users/{user_id}`<br>实测 `/api/admin/users/py_0cc25de5d67e4542911cf727ef529db1` | `app/modules/auth/presentation/users.py:445` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。按邮箱确认删除用户 | SystemEvent 3→4，内容变化；User 2→1，内容变化；UserPreference 2→1，内容变化 |
| `GET /api/admin/users/{user_id}`<br>实测 `/api/admin/users/py_0cc25de5d67e4542911cf727ef529db1` | `app/modules/auth/presentation/users.py:209` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取指定用户 | 无（请求前后全表行数与内容摘要一致） |
| `PATCH /api/admin/users/{user_id}`<br>实测 `/api/admin/users/py_0cc25de5d67e4542911cf727ef529db1` | `app/modules/auth/presentation/users.py:305` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。更新用户权限和名称 | SystemEvent 1→2，内容变化；User 2→2，内容变化；UserPreference 2→2，内容变化 |
| `PUT /api/admin/users/{user_id}/password`<br>实测 `/api/admin/users/py_0cc25de5d67e4542911cf727ef529db1/password` | `app/modules/auth/presentation/users.py:415` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。管理员重置用户密码并撤销其会话 | SystemEvent 2→3，内容变化；User 2→2，内容变化 |

## 模块内缺失接口核查

未发现已注册但未进入 OpenAPI 的接口；本模块所有实际注册的 method + path 都能在 `/openapi.json` 中找到，也没有 `include_in_schema=False` 隐藏路由。

这里的“未发现”以 FastAPI 注册表、OpenAPI paths 和路由装饰器入口对账为准；不把普通内部函数误判为 HTTP 接口。
