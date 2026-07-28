# 媒体文件与封面 OpenAPI 实际检查

- 检查日期：2026-07-28
- 实际请求接口：9 个（每个 method + path 均至少一次）
- 环境：独立临时 SQLite、临时存储/监控目录、真实 uvicorn TCP 服务
- 数据库证据：每次请求前后反射全部表，比较行数和按行内容摘要

## 逐接口结果

| 接口 | 代码位置 | 文档与代码核查 | 实际能力/响应 | 数据库写入证据 |
|---|---|---|---|---|
| `GET /api/editions/{edition_id}/cover`<br>实测 `/api/editions/audit-edition-epub/cover` | `app/modules/media/presentation/http.py:154` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，二进制/流式响应。读取版本封面 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/editions/{edition_id}/file`<br>实测 `/api/editions/audit-edition-epub/file` | `app/modules/media/presentation/http.py:117` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，二进制/流式响应。按版本读取主文件 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/files/{file_id}`<br>实测 `/api/files/audit-file-epub` | `app/modules/media/presentation/http.py:92` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，二进制/流式响应。流式读取 EPUB 文件 | 无（请求前后全表行数与内容摘要一致） |
| `HEAD /api/files/{file_id}`<br>实测 `/api/files/audit-file-epub` | `app/modules/media/presentation/http.py:92` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，二进制/流式响应。HEAD 获取文件响应头 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/metadata/cover-proxy`<br>实测 `/api/metadata/cover-proxy` | `app/modules/media/presentation/http.py:206` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，二进制/流式响应。代理已显式配置的 Bangumi 测试源图片 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/volumes/{volume_id}/cover`<br>实测 `/api/volumes/audit-volume-comic/cover` | `app/modules/media/presentation/http.py:154` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，二进制/流式响应。读取卷册封面（回退到版本/作品封面） | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/volumes/{volume_id}/pages`<br>实测 `/api/volumes/audit-volume-comic/pages` | `app/modules/media/presentation/http.py:245` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。列出 CBZ 页索引 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/volumes/{volume_id}/pages/{page_index}`<br>实测 `/api/volumes/audit-volume-comic/pages/1` | `app/modules/media/presentation/http.py:266` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，二进制/流式响应。从 CBZ 实际解压并返回第 1 页 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/works/{work_id}/cover`<br>实测 `/api/works/audit-work-a/cover` | `app/modules/media/presentation/http.py:154` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，二进制/流式响应。读取作品封面 | 无（请求前后全表行数与内容摘要一致） |

## 模块内缺失接口核查

未发现已注册但未进入 OpenAPI 的接口；本模块所有实际注册的 method + path 都能在 `/openapi.json` 中找到，也没有 `include_in_schema=False` 隐藏路由。

这里的“未发现”以 FastAPI 注册表、OpenAPI paths 和路由装饰器入口对账为准；不把普通内部函数误判为 HTTP 接口。
