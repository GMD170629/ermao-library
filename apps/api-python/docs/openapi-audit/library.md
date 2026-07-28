# 书库管理 OpenAPI 实际检查

- 检查日期：2026-07-28
- 实际请求接口：35 个（每个 method + path 均至少一次）
- 环境：独立临时 SQLite、临时存储/监控目录、真实 uvicorn TCP 服务
- 数据库证据：每次请求前后反射全部表，比较行数和按行内容摘要

## 逐接口结果

| 接口 | 代码位置 | 文档与代码核查 | 实际能力/响应 | 数据库写入证据 |
|---|---|---|---|---|
| `GET /api/dashboard/continue-reading`<br>实测 `/api/dashboard/continue-reading` | `app/modules/library/presentation/http.py:350` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。继续阅读聚合 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/dashboard/recent-books`<br>实测 `/api/dashboard/recent-books` | `app/modules/library/presentation/http.py:324` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。最近入库 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/dashboard/recent-reading`<br>实测 `/api/dashboard/recent-reading` | `app/modules/library/presentation/http.py:337` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。最近阅读 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/dashboard/summary`<br>实测 `/api/dashboard/summary` | `app/modules/library/presentation/http.py:304` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。书库摘要 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/library/categories`<br>实测 `/api/library/categories` | `app/modules/library/presentation/http.py:1644` | ✅ 响应模型与 bookCount/aliases 分类投影一致 | ✅ 修复复测 HTTP 200，标准成功 envelope。 | 无（只读） |
| `POST /api/library/categories/merge`<br>实测 `/api/library/categories/merge` | `app/modules/library/presentation/http.py:1688` | ❌ 实际读取请求体，但 OpenAPI 仍无 requestBody；✅ 响应契约已对齐 targetId/mergedIds/operation | ✅ 修复复测 HTTP 200。 | 目标分类 aliases 包含来源名称；来源 facet 删除；作品 tags 和操作记录已提交 |
| `DELETE /api/library/categories/{facet_id}`<br>实测 `/api/library/categories/facet_52bbc3c58f2ae1d3cbcf592c` | `app/modules/library/presentation/http.py:1676` | ✅ 删除响应明确包含 facetId/kind/name/affectedBookCount/operation | ✅ 修复复测 HTTP 200。 | facet 及作品 tag 删除并写入可撤销操作；随后撤销复测恢复 |
| `PATCH /api/library/categories/{facet_id}`<br>实测 `/api/library/categories/facet_9b7b9ccbb7056a24c465ce48` | `app/modules/library/presentation/http.py:1663` | ❌ 实际读取请求体，但 OpenAPI 仍无 requestBody；✅ 响应契约已对齐 facetId/name/operation | ✅ 修复复测 HTTP 200。 | facet 名称与作品 tags 均更新为 `HTTP硬科幻`，操作记录已提交 |
| `GET /api/library/duplicates`<br>实测 `/api/library/duplicates` | `app/modules/library/presentation/http.py:1707` | ✅ DuplicateGroup 与真实 id/confidence/reasons/WorkView 投影一致 | ✅ 有真实重复组时修复复测 HTTP 200；初检空数据未暴露的相邻故障已补回归测试。 | 无（只读） |
| `POST /api/library/duplicates/merge`<br>实测 `/api/library/duplicates/merge` | `app/modules/library/presentation/http.py:1718` | ❌ 实际读取请求体，但 OpenAPI 仍无 requestBody；✅ 响应契约已对齐 targetWorkId/sourceWorkIds/operation | ✅ 修复复测 HTTP 200。 | 来源作品标记 hidden，来源版本迁移到目标作品，合并操作已提交 |
| `GET /api/library/facets`<br>实测 `/api/library/facets` | `app/modules/library/presentation/http.py:1510` | ✅ 文档模型为 author/tag/series/publisher 分组，statuses/mediaKinds 均含 label | ✅ 修复复测 HTTP 200，标准成功 envelope。 | 无（只读） |
| `GET /api/library/filter-schema`<br>实测 `/api/library/filter-schema` | `app/modules/library/presentation/http.py:1636` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取动态筛选字段/options | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/library/operations`<br>实测 `/api/library/operations` | `app/modules/library/presentation/http.py:1736` | ✅ 公开契约为安全操作摘要，不暴露 payloadJson/inverseJson/userId | ✅ 修复复测 HTTP 200；真实列表共 3 条操作且内部字段无泄漏。 | 无（只读） |
| `POST /api/library/operations/{operation_id}/undo`<br>实测 `/api/library/operations/op_1785235491582849000/undo` | `app/modules/library/presentation/http.py:1745` | ✅ 返回 operation/restored，与实际撤销结果一致 | ✅ 修复复测 HTTP 200，restored=true，operation.status=UNDONE。 | 被删 facet 与作品 tag 恢复；LibraryOperation 状态、undoneAt、updatedAt 正常写入 |
| `GET /api/management/folders`<br>实测 `/api/management/folders` | `app/modules/library/presentation/http.py:475` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。目录存储概览 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/management/overview`<br>实测 `/api/management/overview` | `app/modules/library/presentation/http.py:428` | ✅ recentEvents 使用可表达真实嵌套 JSON 的 SystemEvent 契约 | ✅ 修复复测 HTTP 200；最近事件含 sourceFormat、skipped=list、嵌套对象。 | 无（只读） |
| `GET /api/series`<br>实测 `/api/series` | `app/modules/library/presentation/http.py:559` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。系列聚合 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/works`<br>实测 `/api/works` | `app/modules/library/presentation/http.py:589` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。作品分页/筛选 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/works/bulk`<br>实测 `/api/works/bulk` | `app/modules/library/presentation/http.py:1113` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。批量添加标签并同步 facet | LibraryFacet 6→8，内容变化；LibraryWork 3→3，内容变化；LibraryWorkFacet 6→8，内容变化；SystemEvent 16→17，内容变化 |
| `POST /api/works/bulk/cover`<br>实测 `/api/works/bulk/cover` | `app/modules/library/presentation/http.py:1342` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。批量重建封面引用 | LibraryWork 3→3，内容变化；SystemEvent 17→18，内容变化 |
| `POST /api/works/bulk/find-replace/preview`<br>实测 `/api/works/bulk/find-replace/preview` | `app/modules/library/presentation/http.py:1307` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。预览批量查找替换 | 无（请求前后全表行数与内容摘要一致） |
| `DELETE /api/works/{work_id}`<br>实测 `/api/works/work_1785232913026852000` | `app/modules/library/presentation/http.py:851` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。删除拆分出的测试作品及数据库关联 | LibraryEdition 6→5，内容变化；LibraryFile 6→5，内容变化；LibraryVolume 5→4，内容变化；LibraryWork 4→3，内容变化；LibraryWorkFacet 16→12，内容变化；SystemEvent 20→21，内容变化 |
| `GET /api/works/{work_id}`<br>实测 `/api/works/audit-work-a` | `app/modules/library/presentation/http.py:680` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。作品详情及媒介导航 | 无（请求前后全表行数与内容摘要一致） |
| `PATCH /api/works/{work_id}`<br>实测 `/api/works/audit-work-a` | `app/modules/library/presentation/http.py:755` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。更新作品元数据并同步 facet | LibraryConsumptionState 1→1，内容变化；LibraryFacet 3→6，内容变化；LibraryWork 3→3，内容变化；LibraryWorkFacet 3→6，内容变化 |
| `POST /api/works/{work_id}/cover/regenerate`<br>实测 `/api/works/audit-work-a/cover/regenerate` | `app/modules/library/presentation/http.py:1484` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。重新选择作品默认/版本封面 | LibraryWork 3→3，内容变化 |
| `POST /api/works/{work_id}/cover/upload`<br>实测 `/api/works/audit-work-a/cover/upload` | `app/modules/library/presentation/http.py:1458` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。上传作品封面并写文件/数据库 | LibraryWork 3→3，内容变化 |
| `PUT /api/works/{work_id}/detail-preference`<br>实测 `/api/works/audit-work-a/detail-preference` | `app/modules/library/presentation/http.py:717` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。保存用户详情页媒介选项 | WorkDetailPreference 0→1，内容变化 |
| `PATCH /api/works/{work_id}/editions/{edition_id}`<br>实测 `/api/works/py_907612437b164344af8bb7368b5c864f/editions/py_3f1032d73a2848fc9066c4fc5fb8d0e8` | `app/modules/library/presentation/http.py:1782` | ❌ 实际读取请求体，但 OpenAPI 仍无 requestBody；✅ 返回完整 LibraryEdition/WorkView 投影 | ✅ 修复复测 HTTP 200，edition.versionName=`HTTP修订版`。 | LibraryEdition.versionName 正常持久化，响应中的 edition 与 book.editions 一致 |
| `POST /api/works/{work_id}/editions/{edition_id}/convert`<br>实测 `/api/works/audit-work-a/editions/audit-edition-txt/convert` | `app/modules/library/presentation/http.py:1817` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 202，标准成功 envelope。修正为运行期预期的绝对源路径后加入 EPUB 转换队列 | ImportTask 0→1，内容变化；SystemEvent 21→22，内容变化 |
| `POST /api/works/{work_id}/editions/{edition_id}/primary`<br>实测 `/api/works/audit-work-a/editions/audit-edition-epub/primary` | `app/modules/library/presentation/http.py:1877` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。设置同媒介主版本 | LibraryEdition 6→6，内容变化；LibraryWork 3→3，内容变化；SystemEvent 18→19，内容变化 |
| `POST /api/works/{work_id}/editions/{edition_id}/split`<br>实测 `/api/works/audit-work-a/editions/audit-edition-split/split` | `app/modules/library/presentation/http.py:1877` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。把版本拆分为独立作品 | LibraryEdition 6→6，内容变化；LibraryEditionFacet 1→1，内容变化；LibraryOperation 3→4，内容变化；LibraryWork 3→4，内容变化；LibraryWorkFacet 10→14，内容变化 |
| `POST /api/works/{work_id}/metadata/apply`<br>实测 `/api/works/audit-work-a/metadata/apply` | `app/modules/library/presentation/http.py:1877` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。应用选择的元数据字段并完成整理状态 | LibraryEdition 6→6，内容变化；LibraryEditionFacet 1→1，内容变化；LibraryFacet 9→11，内容变化；LibraryWork 3→3，内容变化；LibraryWorkFacet 11→10，内容变化；OrganizeJob 1→1，内容变化 |
| `POST /api/works/{work_id}/metadata/search`<br>实测 `/api/works/audit-work-a/metadata/search` | `app/modules/library/presentation/http.py:1758` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。调用已注册但禁用的 Bangumi provider，返回稳定空候选/禁用消息 | OrganizeJob 1→2，内容变化 |
| `POST /api/works/{work_id}/volumes/{volume_id}/move`<br>实测 `/api/works/audit-work-a/volumes/audit-volume-epub/move` | `app/modules/library/presentation/http.py:1877` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。卷册顺序上移（边界位置保持不变） | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/works/{work_id}/volumes/{volume_id}/move-to`<br>实测 `/api/works/audit-work-a/volumes/audit-volume-move/move-to` | `app/modules/library/presentation/http.py:1877` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。把版本/卷册转移到另一作品 | LibraryEdition 6→6，内容变化；LibraryFile 6→6，内容变化；LibraryVolume 5→5，内容变化；LibraryWork 3→3，内容变化；SystemEvent 19→20，内容变化 |

## 模块内缺失接口核查

未发现已注册但未进入 OpenAPI 的接口；本模块所有实际注册的 method + path 都能在 `/openapi.json` 中找到，也没有 `include_in_schema=False` 隐藏路由。

这里的“未发现”以 FastAPI 注册表、OpenAPI paths 和路由装饰器入口对账为准；不把普通内部函数误判为 HTTP 接口。
