# 导入与监控目录 OpenAPI 实际检查

- 检查日期：2026-07-28
- 实际请求接口：17 个（每个 method + path 均至少一次）
- 环境：独立临时 SQLite、临时存储/监控目录、真实 uvicorn TCP 服务
- 数据库证据：每次请求前后反射全部表，比较行数和按行内容摘要

## 逐接口结果

| 接口 | 代码位置 | 文档与代码核查 | 实际能力/响应 | 数据库写入证据 |
|---|---|---|---|---|
| `DELETE /api/import-tasks`<br>实测 `/api/import-tasks` | `app/modules/imports/presentation/writes.py:667` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。清空终态导入记录 | ImportTask 1→0，内容变化；SystemEvent 12→13，内容变化 |
| `GET /api/import-tasks`<br>实测 `/api/import-tasks` | `app/modules/imports/presentation/http.py:312` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。分页列出导入任务 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/import-tasks/rescan`<br>实测 `/api/import-tasks/rescan` | `app/modules/imports/presentation/writes.py:832` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。记录全局重新扫描请求 | SystemEvent 9→10，内容变化；SystemSetting 14→15，内容变化 |
| `POST /api/import-tasks/scan-directory`<br>实测 `/api/import-tasks/scan-directory` | `app/modules/imports/presentation/writes.py:581` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。扫描受管目录并把候选文件写入持久队列 | ImportTask 1→2，内容变化；SystemEvent 8→9，内容变化 |
| `DELETE /api/import-tasks/{task_id}`<br>实测 `/api/import-tasks/py_1785232514568654000` | `app/modules/imports/presentation/writes.py:695` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。仅删除终态导入记录，保留源文件 | ImportTask 2→1，内容变化；SystemEvent 11→12，内容变化 |
| `GET /api/import-tasks/{task_id}`<br>实测 `/api/import-tasks/py_1785232514568654000` | `app/modules/imports/presentation/http.py:355` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取上传任务详情 | 无（请求前后全表行数与内容摘要一致） |
| `GET /api/import-tasks/{task_id}/logs`<br>实测 `/api/import-tasks/py_1785232514568654000/logs` | `app/modules/imports/presentation/http.py:371` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取任务日志分页 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/import-tasks/{task_id}/retry`<br>实测 `/api/import-tasks/py_1785232514568654000/retry` | `app/modules/imports/presentation/writes.py:885` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。失败且源文件存在的任务重置为待处理 | ImportTask 2→2，内容变化；SystemEvent 10→11，内容变化 |
| `GET /api/monitor-folders`<br>实测 `/api/monitor-folders` | `app/modules/imports/presentation/http.py:76` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。列出监控文件夹 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/monitor-folders`<br>实测 `/api/monitor-folders` | `app/modules/imports/presentation/http.py:125` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody；实际 201 未列入 responses | ✅ HTTP 201，标准成功 envelope。创建监控文件夹并记录系统事件 | MonitorFolder 0→1，内容变化；SystemEvent 4→5，内容变化 |
| `GET /api/monitor-folders/tree`<br>实测 `/api/monitor-folders/tree` | `app/modules/imports/presentation/http.py:102` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。读取监控根目录树 | 无（请求前后全表行数与内容摘要一致） |
| `DELETE /api/monitor-folders/{folder_id}`<br>实测 `/api/monitor-folders/py_1785232514047186000` | `app/modules/imports/presentation/http.py:277` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。删除监控文件夹并记录授权失效范围 | MonitorFolder 1→0，内容变化；SystemEvent 13→14，内容变化 |
| `PATCH /api/monitor-folders/{folder_id}`<br>实测 `/api/monitor-folders/py_1785232514047186000` | `app/modules/imports/presentation/http.py:196` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。PATCH 更新名称/说明 | MonitorFolder 1→1，内容变化；SystemEvent 5→6，内容变化 |
| `PUT /api/monitor-folders/{folder_id}`<br>实测 `/api/monitor-folders/py_1785232514047186000` | `app/modules/imports/presentation/http.py:196` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。PUT 更新启用状态和最小文件大小 | MonitorFolder 1→1，内容变化；SystemEvent 6→7，内容变化 |
| `GET /api/tracking/release-title-parser`<br>实测 `/api/tracking/release-title-parser` | `app/modules/imports/presentation/http.py:408` | ✅ 请求参数和实际状态有文档；响应经过运行时契约处理 | ✅ HTTP 200，标准成功 envelope。GET 解析卷/章节标题 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/tracking/release-title-parser`<br>实测 `/api/tracking/release-title-parser` | `app/modules/imports/presentation/http.py:435` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。POST 解析卷/章节标题 | 无（请求前后全表行数与内容摘要一致） |
| `POST /api/works/import`<br>实测 `/api/works/import` | `app/modules/imports/presentation/writes.py:300` | ❌ 实际读取请求体，但 OpenAPI 无 requestBody | ✅ HTTP 200，标准成功 envelope。multipart 上传 TXT，原子保存并创建 ImportTask/SystemEvent/SystemSetting | ImportTask 0→1，内容变化；SystemEvent 7→8，内容变化；SystemSetting 13→14，内容变化 |

## 模块内缺失接口核查

未发现已注册但未进入 OpenAPI 的接口；本模块所有实际注册的 method + path 都能在 `/openapi.json` 中找到，也没有 `include_in_schema=False` 隐藏路由。

这里的“未发现”以 FastAPI 注册表、OpenAPI paths 和路由装饰器入口对账为准；不把普通内部函数误判为 HTTP 接口。
