# 整理与识别 OpenAPI 实际检查

- 检查日期：2026-07-28
- 实际请求接口：9 个（每个 method + path 均至少一次）
- 环境：独立临时 SQLite、临时存储/监控目录、真实 uvicorn TCP 服务
- 数据库证据：每次请求前后反射全部表，比较行数和按行内容摘要

## 逐接口结果

| 接口 | 代码位置 | 文档与代码核查 | 实际能力/响应 | 数据库写入证据 |
|---|---|---|---|---|
| `GET /api/organize/candidates`<br>实测 `/api/organize/candidates` | `app/modules/organize/presentation/http.py:181` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。统计待整理候选 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/organize/jobs`<br>实测 `/api/organize/jobs` | `app/modules/organize/presentation/http.py:201` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。分页列出整理任务 | 无（请求前后全表行数与内容摘要一致） |
| `DELETE /api/organize/jobs/{job_id}`<br>实测 `/api/organize/jobs/audit-organize-job-2` | `app/modules/organize/presentation/http.py:336` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。删除整理任务图并刷新作品/运行状态 | LibraryWork 3→3，内容变化；MetadataLookupTask 1→0，内容变化；OrganizeJob 3→2，内容变化；OrganizeRun 2→2，内容变化 |
| `GET /api/organize/jobs/{job_id}`<br>实测 `/api/organize/jobs/audit-organize-job-2` | `app/modules/organize/presentation/http.py:304` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取整理任务详情 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/organize/jobs/{job_id}/recognize`<br>实测 `/api/organize/jobs/audit-organize-job-2/recognize` | `app/modules/organize/presentation/http.py:318` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。清理旧识别产物并创建 MetadataLookupTask | LibraryWork 3→3，内容变化；MetadataLookupTask 0→1，内容变化；OrganizeJob 3→3，内容变化；OrganizeRun 2→2，内容变化 |
| `GET /api/organize/pending`<br>实测 `/api/organize/pending` | `app/modules/organize/presentation/http.py:274` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。列出待处理整理任务 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/organize/policy`<br>实测 `/api/organize/policy` | `app/modules/organize/presentation/http.py:156` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取整理调度策略 | 无（请求前后全表行数与内容摘要一致） |
| `PUT /api/organize/policy`<br>实测 `/api/organize/policy` | `app/modules/organize/presentation/http.py:167` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。更新手动整理策略 | OrganizePolicy 0→1，内容变化 |
| `GET /api/organize/runs`<br>实测 `/api/organize/runs` | `app/modules/organize/presentation/http.py:192` | ✅ 读取投影会把旧或无效 scope 归一化为文档要求的 workIds/rules | ✅ 修复复测 HTTP 200；`scopeJson={}` 返回 `workIds=[]` 和两项默认规则。 | 无（只读；数据库中原始 `scopeJson={}` 未被改写） |

## 模块内缺失接口核查

未发现已注册但未进入 OpenAPI 的接口；本模块所有实际注册的 method + path 都能在 `/openapi.json` 中找到，也没有 `include_in_schema=False` 隐藏路由。

这里的“未发现”以 FastAPI 注册表、OpenAPI paths 和路由装饰器入口对账为准；不把普通内部函数误判为 HTTP 接口。
