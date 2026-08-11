# 导入、元数据、整理、下载与 Kindle 修复复测

本报告是[原模块报告](./queues-metadata.md)中四项缺陷修复后的独立复测结果。测试使用全新 `STORAGE_ROOT`、真实 uvicorn、独立 Worker、本地 HTTP 文件服务和本地 SMTP 服务；没有使用 TestClient 或数据库模拟替代真实请求。

## 结论

- OpenAPI 分配操作：74
- 实际覆盖：74/74
- 遗漏：0
- 74 项状态、响应合同和逐项 ORM 数据库断言：全部通过
- 修复项：4/4 通过

## 修复项验证

### OPF 队列状态

`GET /api/metadata/opf-sync/status` 返回 200，稳定响应为：

```json
{
  "pendingTargets": 0,
  "pendingPreparations": 0,
  "capacity": 50000,
  "utilization": 0.0
}
```

真实工作流结束时数据库仍保留一个尚未由已停止 Worker 消费的 `MetadataWritebackPreparation` 和对应 operation，证明状态查询修复没有删除或吞掉待处理数据。

### 新库整理策略 GET

在任何 policy PUT 之前，首次及第二次 `GET /api/organize/policy` 均返回 200；默认投影的 `updatedAt` 固定为 `1970-01-01T00:00:00Z`。两次请求之间响应稳定，SQL 记录器确认 DML 为 0，数据库 `OrganizePolicy` 行数仍为 0。

随后执行真实 policy PUT 并重新 GET，数据库投影与请求内容一致，说明只读默认值不妨碍后续显式初始化。

### OpenAPI requestBody 与空 body

- 对 22 个实际消费 body 的操作逐一读取运行中服务的 `/openapi.json`：`requestBody` 遗漏 0。
- `DELETE /api/import-tasks/{task_id}` 的 body 仍为可选，没有被错误标记为 required。
- 对 20 个相关写接口发出真实空 body 请求：raw 500 为 0。
- 空 body 探测前后数据库计数完全一致：`Source=3`、`SourceSearchRecord=0`、`DownloadTask=2`、`SystemSetting=13`、`SystemEvent=34`，没有部分写入。
- provider/pipeline、scan-directory、release-title parser、download、email/Kindle、退役 source/search-record 和 organize policy 的合法请求均在 74 项清单内再次通过。

### OrganizerScheduler 写锁退让

使用第二个 SQLAlchemy Engine 持有 SQLite writer lock 12 秒，并让真实 Worker 的 OrganizerScheduler 处理一个待同步 run：

- 仅记录一次 `organizer_schedule_iteration outcome=deferred reason=database_busy`。
- 30 秒限频窗口内没有重复 scheduler busy 日志。
- 日志中没有 `organizer scheduler iteration failed` 或 `Traceback`。
- 锁期间四个真实 GET 均成功：providers 16.6ms、sources 2.2ms、organize policy 4.2ms、OPF status 2.1ms。
- 锁释放后下一次调度成功；run 从人为设置的 `RUNNING` 恢复为 `COMPLETED`，关联 job 的 `FAILED` 状态和 `failedCount=1` 均保留。

## 数据库回归摘要

74 项清单逐 operation 读取 ORM 表验证请求前后差异，覆盖：

- provider 配置、pipeline 集合替换、provider 连接测试和 lookup/writeback 队列；
- multipart 单文件及多文件字段、导入任务、扫描、重试、删除和队列控制；
- organize policy、run、job、recognition、suggestion 和 duplicate 路径；
- DownloadTask 创建、更新、真实 HTTP 下载、重试、取消、删除；
- SMTP 设置和真实连接、Kindle 设置、任务创建、取消、重试、删除；
- 退役 Source/SearchRecord 的只读/墓碑合同以及无写入保证。

最终表计数与请求链路一致，其中 `LibraryWork=2`、`LibraryVolume=2`、`LibraryFile=2`，导入任务清理没有误删书库记录；`KindleSendTask=0`、`ImportTask=0` 符合显式删除步骤；待处理 metadata preparation/operation 各 1 条，符合 Worker 停止时的续跑语义。

## 自动化门禁

- 新增合同与锁回归：11 passed
- 相关既有能力回归：31 passed，3 skipped，89 deselected
- 扩展路由/Kindle 回归：25 passed
- 架构门禁：7 passed
- Python compileall：通过
- Ruff format check：通过
- Ruff `E4,E7,E9,F,I,UP`：通过
- `git diff --check`：通过

仓库的全规则 Ruff 在既有 FastAPI route 上仍会报告历史 `Depends(...)` 默认值和旧 broad-exception 债务；本次没有降低规则、增加 blanket suppression 或将这类债务作为修复条件绕过。

## 原始证据

- 74 项逐 operation 结果：`/tmp/shuku-api-rerun-queues-metadata.F51qSK/assigned-api-results.json`
- 空 body 请求和表计数快照：`/tmp/shuku-api-rerun-queues-metadata.F51qSK/openapi-no-body-results.json`
- 新库首次 policy GET：`/tmp/shuku-api-rerun-queues-metadata.F51qSK/fresh-organize-policy.json`
- Worker 写锁日志：`/tmp/shuku-api-rerun-queues-metadata.F51qSK/worker-lock.log`
