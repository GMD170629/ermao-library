# 导入、元数据、整理、下载与 Kindle API 报告

- OpenAPI operations：74
- 覆盖：74/74，遗漏 0
- 实例：真实 uvicorn `18103`、文件服务 `18104`、SMTP `18105`、独立 import/metadata/organize Worker
- 逐 operation：见[总执行矩阵](./api-operation-matrix.md)

## 数据库与事务断言

- multipart 上传后由真实 Worker 创建 Work/Volume/File；ImportTask 状态和日志完整。
- ScanJob、WorkItem、SystemEvent 同批写；取消、rescan、clear 均验证最终状态和引用行。
- provider PUT/PATCH、pipeline 集合更新只改变目标 provider/media kind；provider test 网络调用在事务外，结果随后短事务写回。
- metadata apply 更新目标作品并同事务写 Operation、Preparation 和 queue counter；Worker 完成后 preparation/target/operation 清理、计数归零。
- DownloadTask 先 claim，真实 HTTP 下载和文件原子发布在事务外，finalize 后 downloaded/progress=100，字节一致。
- SMTP 测试使用真实本地服务；Kindle 经真实 Worker queued→sent，attemptCount/messageId/事件顺序一致。
- queue clear 返回 202 后由 Worker 达到 completed，并集合清空 ImportTask；LibraryWork 保留。
- 退役 Source/SearchRecord 操作按 200/404/410 契约返回，表行数不变。
- 外部 writer lock 15s 时，providers、sources、search records GET 均为 200，1.9–3.3ms，无 DML。

## 首轮缺陷与修复结果

以下问题均已修复，并在全新实例重新覆盖 74/74；详见[修复复测报告](./queues-metadata-fix-rerun.md)。

### P0：OPF status schema 未包含 0019 字段（已修复）

`GET /api/metadata/opf-sync/status` 固定 500。数据库 `MetadataOpfQueueState` 的 `pendingTargets=0`、`pendingPreparations=0` 正常，但 presentation schema 未声明 `pendingPreparations`，触发 Pydantic `extra_forbidden`。

最终响应为 200，并同时返回 `pendingTargets`、`pendingPreparations`、capacity 和 utilization。

### P1：新库首次 organize policy GET 503（已修复）

新库没有 default `OrganizePolicy` 行，首次 GET 构造 `updatedAt=None`，不满足响应 schema；PUT 初始化后 GET 恢复 200。

最终首次 GET 使用固定 epoch 的只读默认投影，连续请求稳定且零 DML；显式 PUT 后正常返回数据库投影。

### P1：OpenAPI body 缺失（已修复）

严格按文档向缺少 requestBody 的写接口发送空 body，9 个返回 raw 500。Source、SearchRecord、DownloadTask、SystemSetting、SystemEvent 等相关表计数前后完全不变，因此没有部分数据库写，但 HTTP 契约无法供生成客户端正确调用。

最终本模块 22 个消费 body 的 operation 均有显式模型；20 个空 body 探针 raw 500 为 0、表计数不变。

### P2：OrganizerScheduler busy 异常（已修复）

外部 writer lock 下普通 GET 正常，后台短写也能退让；OrganizerScheduler 重试后仍两次打印完整 database-locked traceback，并产生大量约 270–335ms rollback 慢事务日志。

最终 12 秒 writer lock 只产生一次结构化 deferred 日志，无 traceback；释放后 run 自动完成且 job 终态未丢失。

## 原始证据

- 模块报告：`/tmp/shuku-api-audit-dXLh9i/api-audit-imports-metadata-organize-download-kindle.md`
- 逐 operation：`/tmp/shuku-api-audit-dXLh9i/assigned-api-results.json`
- 空 body：`/tmp/shuku-api-audit-dXLh9i/openapi-no-body-results.json`
- 日志：`/tmp/shuku-api-audit-dXLh9i/uvicorn.log`、`import-worker.log`
- 真实外部适配器：`http-file-server.log`、`smtp.log`、`kindle-delivery-after.json`
