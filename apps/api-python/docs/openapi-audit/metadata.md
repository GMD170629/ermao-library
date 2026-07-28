# 元数据提供商 OpenAPI 实际检查

- 检查日期：2026-07-28
- 实际请求接口：6 个（每个 method + path 均至少一次）
- 环境：独立临时 SQLite、临时存储/监控目录、真实 uvicorn TCP 服务
- 数据库证据：每次请求前后反射全部表，比较行数和按行内容摘要

## 逐接口结果

| 接口 | 代码位置 | 文档与代码核查 | 实际能力/响应 | 数据库写入证据 |
|---|---|---|---|---|
| `PUT /api/metadata/provider-pipelines/{work_type}`<br>实测 `/api/metadata/provider-pipelines/ebook` | `app/modules/metadata/presentation/http.py:71` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。更新 ebook 提供方顺序（保持禁用避免外部依赖） | MetadataProviderPipeline 7→7，内容变化；Source 3→3，内容变化；SystemEvent 1→2，内容变化；SystemSetting 6→13，内容变化 |
| `GET /api/metadata/providers`<br>实测 `/api/metadata/providers` | `app/modules/metadata/presentation/http.py:51` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。列出内置元数据提供方及流水线 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/metadata/providers/{provider_id}`<br>实测 `/api/metadata/providers/douban` | `app/modules/metadata/presentation/http.py:112` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取豆瓣提供方 | 无（请求前后全表行数与内容摘要一致） |
| `PATCH /api/metadata/providers/{provider_id}`<br>实测 `/api/metadata/providers/douban` | `app/modules/metadata/presentation/http.py:133` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。PATCH 更新豆瓣优先级 | Source 3→3，内容变化；SystemEvent 3→4，内容变化；SystemSetting 13→13，内容变化 |
| `PUT /api/metadata/providers/{provider_id}`<br>实测 `/api/metadata/providers/douban` | `app/modules/metadata/presentation/http.py:133` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。PUT 更新豆瓣配置和优先级 | MetadataProviderPipeline 7→7，内容变化；Source 3→3，内容变化；SystemEvent 2→3，内容变化；SystemSetting 13→13，内容变化 |
| `POST /api/metadata/providers/{provider_id}/test`<br>实测 `/api/metadata/providers/douban/test` | `app/modules/metadata/presentation/http.py:178` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。实际连接测试；HTTP 200，result.ok 反映外网可达性 | Source 3→3，内容变化 |

## 模块内缺失接口核查

未发现已注册但未进入 OpenAPI 的接口；本模块所有实际注册的 method + path 都能在 `/openapi.json` 中找到，也没有 `include_in_schema=False` 隐藏路由。

这里的“未发现”以 FastAPI 注册表、OpenAPI paths 和路由装饰器入口对账为准；不把普通内部函数误判为 HTTP 接口。
