# 认证与账号 OpenAPI 实际检查

- 检查日期：2026-07-28
- 实际请求接口：14 个（每个 method + path 均至少一次）
- 环境：独立临时 SQLite、临时存储/监控目录、真实 uvicorn TCP 服务
- 数据库证据：每次请求前后反射全部表，比较行数和按行内容摘要

## 逐接口结果

| 接口 | 代码位置 | 文档与代码核查 | 实际能力/响应 | 数据库写入证据 |
|---|---|---|---|---|
| `PATCH /api/auth/account/email`<br>实测 `/api/auth/account/email` | `app/modules/auth/presentation/http.py:313` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。修改账户邮箱（有效 currentPassword） | User 1→1，内容变化 |
| `PATCH /api/auth/account/name`<br>实测 `/api/auth/account/name` | `app/modules/auth/presentation/http.py:352` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。修改账户名称 | User 1→1，内容变化 |
| `PATCH /api/auth/account/password`<br>实测 `/api/auth/account/password` | `app/modules/auth/presentation/http.py:376` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。修改密码并撤销会话 | Session 3→0，内容变化；User 1→1，内容变化 |
| `DELETE /api/auth/avatar`<br>实测 `/api/auth/avatar` | `app/modules/auth/presentation/http.py:483` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。删除头像记录与文件 | User 1→1，内容变化 |
| `GET /api/auth/avatar`<br>实测 `/api/auth/avatar` | `app/modules/auth/presentation/http.py:462` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，二进制/流式响应。读取已上传头像 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/auth/avatar`<br>实测 `/api/auth/avatar` | `app/modules/auth/presentation/http.py:406` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。上传 PNG 头像并写入用户记录/文件 | User 1→1，内容变化 |
| `GET /api/auth/capabilities`<br>实测 `/api/auth/capabilities` | `app/modules/auth/presentation/http.py:175` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取密码重置能力 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/auth/login`<br>实测 `/api/auth/login` | `app/modules/auth/presentation/http.py:256` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。用重置后的密码重新登录 | Session 0→1，内容变化 |
| `POST /api/auth/logout`<br>实测 `/api/auth/logout` | `app/modules/auth/presentation/http.py:602` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。删除当前会话并清理 cookie | Session 1→0，内容变化 |
| `GET /api/auth/me`<br>实测 `/api/auth/me` | `app/modules/auth/presentation/http.py:293` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取当前会话 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/auth/password-reset/confirm`<br>实测 `/api/auth/password-reset/confirm` | `app/modules/auth/presentation/http.py:564` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。消费重置令牌、修改密码并撤销会话 | PasswordResetToken 1→1，内容变化；Session 3→0，内容变化；User 1→1，内容变化 |
| `POST /api/auth/password-reset/request`<br>实测 `/api/auth/password-reset/request` | `app/modules/auth/presentation/http.py:508` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 202，标准成功 envelope。创建密码重置令牌及本地重置文件 | PasswordResetToken 0→1，内容变化 |
| `POST /api/auth/setup`<br>实测 `/api/auth/setup` | `app/modules/auth/presentation/http.py:198` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 409，标准错误 envelope。已初始化系统拒绝重复 setup（首次 201 已在隔离实例初始化时验证） | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/auth/setup/status`<br>实测 `/api/auth/setup/status` | `app/modules/auth/presentation/http.py:187` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。已初始化状态 | 无（请求前后全表行数与内容摘要一致） |

## 模块内缺失接口核查

未发现已注册但未进入 OpenAPI 的接口；本模块所有实际注册的 method + path 都能在 `/openapi.json` 中找到，也没有 `include_in_schema=False` 隐藏路由。

这里的“未发现”以 FastAPI 注册表、OpenAPI paths 和路由装饰器入口对账为准；不把普通内部函数误判为 HTTP 接口。
