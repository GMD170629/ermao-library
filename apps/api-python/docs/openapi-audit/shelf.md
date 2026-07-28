# 书架 OpenAPI 实际检查

- 检查日期：2026-07-28
- 实际请求接口：5 个（每个 method + path 均至少一次）
- 环境：独立临时 SQLite、临时存储/监控目录、真实 uvicorn TCP 服务
- 数据库证据：每次请求前后反射全部表，比较行数和按行内容摘要

## 逐接口结果

| 接口 | 代码位置 | 文档与代码核查 | 实际能力/响应 | 数据库写入证据 |
|---|---|---|---|---|
| `GET /api/shelves`<br>实测 `/api/shelves` | `app/modules/shelf/presentation/http.py:73` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。列出个人书架 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/shelves`<br>实测 `/api/shelves` | `app/modules/shelf/presentation/http.py:245` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody；实际 201 未列入 responses | ✅ HTTP 201，标准成功 envelope。创建静态书架并加入两本作品 | Shelf 0→1，内容变化；ShelfWork 0→2，内容变化 |
| `DELETE /api/shelves/{shelf_id}`<br>实测 `/api/shelves/py_1785233001853180000` | `app/modules/shelf/presentation/http.py:336` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。删除书架并级联成员关系 | Shelf 1→0，内容变化；ShelfWork 1→0，内容变化 |
| `GET /api/shelves/{shelf_id}`<br>实测 `/api/shelves/py_1785233001853180000` | `app/modules/shelf/presentation/http.py:217` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取书架详情和分页作品 | 无（请求前后全表行数与内容摘要一致） |
| `PATCH /api/shelves/{shelf_id}`<br>实测 `/api/shelves/py_1785233001853180000` | `app/modules/shelf/presentation/http.py:287` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。更新书架名称、说明和成员 | Shelf 1→1，内容变化；ShelfWork 2→1，内容变化 |

## 模块内缺失接口核查

未发现已注册但未进入 OpenAPI 的接口；本模块所有实际注册的 method + path 都能在 `/openapi.json` 中找到，也没有 `include_in_schema=False` 隐藏路由。

这里的“未发现”以 FastAPI 注册表、OpenAPI paths 和路由装饰器入口对账为准；不把普通内部函数误判为 HTTP 接口。
