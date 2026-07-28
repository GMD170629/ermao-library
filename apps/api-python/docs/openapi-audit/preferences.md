# 用户偏好 OpenAPI 实际检查

- 检查日期：2026-07-28
- 实际请求接口：2 个（每个 method + path 均至少一次）
- 环境：独立临时 SQLite、临时存储/监控目录、真实 uvicorn TCP 服务
- 数据库证据：每次请求前后反射全部表，比较行数和按行内容摘要

## 逐接口结果

| 接口 | 代码位置 | 文档与代码核查 | 实际能力/响应 | 数据库写入证据 |
|---|---|---|---|---|
| `GET /api/auth/preferences`<br>实测 `/api/auth/preferences` | `app/modules/auth/presentation/users.py:521` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取当前用户偏好 | 无（请求前后全表行数与内容摘要一致） |
| `PATCH /api/auth/preferences`<br>实测 `/api/auth/preferences` | `app/modules/auth/presentation/users.py:539` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。更新 locale/library.view/audio.playbackRate 偏好（有效键） | UserPreference 1→3，内容变化 |

## 模块内缺失接口核查

未发现已注册但未进入 OpenAPI 的接口；本模块所有实际注册的 method + path 都能在 `/openapi.json` 中找到，也没有 `include_in_schema=False` 隐藏路由。

这里的“未发现”以 FastAPI 注册表、OpenAPI paths 和路由装饰器入口对账为准；不把普通内部函数误判为 HTTP 接口。
