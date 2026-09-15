# 资源级导入综合验收（任务 6）

## 结论与范围

**本次资源级导入改造通过。** 此结论针对下述本地真实 SQLite、真实应用链路和故障注入验收；真实 NAS 与 Windows 专属行为的未验证项单列。

- 基线：`1257f3d091cf1251f5800c60e10745d5bc079f94`，`develop`，执行前工作区干净；任务 1～5 为基线既有实现。
- 本任务删除旧逐资产入队方法、worker 消费分支及无调用方的扫描分支；旧单文件处理能力继续由资源任务调用。
- 修复综合回归发现的目录探测问题：原枚举复用会先读完整目录，绕过采样上限；现在按预算迭代，仅完整枚举可缓存，提前停止不缓存，并关闭迭代器。
- 扩展既有升级、规模、回滚、混合资源阅读测试；更新过时的迁移列表、约束计数和旧任务测试替身。
- 未改变资源身份、识别规则、支持格式、书库组织、Reader 定位、数据库/队列中间件或 worker 数量；没有新迁移、框架、生产故障开关。未操作生产数据库。

## 实际执行命令与结果

在仓库根目录执行，以下命令均使用锁定依赖。

```sh
uv run --project apps/api-python --extra dev --locked pytest -q -rs \
  apps/api-python/tests/integration/modules/imports \
  apps/api-python/tests/unit/modules/imports \
  apps/api-python/tests/integration/modules/library \
  apps/api-python/tests/unit/modules/library \
  apps/api-python/tests/integration/modules/metadata \
  apps/api-python/tests/unit/modules/metadata \
  apps/api-python/tests/integration/modules/reader \
  apps/api-python/tests/unit/modules/reader \
  apps/api-python/tests/test_sqlite_database.py \
  apps/api-python/tests/test_audiobook_support.py \
  apps/api-python/tests/test_metadata_lookup_queue.py \
  apps/api-python/tests/test_capability_architecture.py \
  apps/api-python/tests/architecture/test_write_transaction_contract.py \
  apps/api-python/tests/contract/api/test_import_continue_contract.py --tb=short
```

结果：**988 passed, 2 skipped，72.24 秒**。两项跳过均为 `test_audiobook_support.py` 的 Windows pipe regression；共同警告为 Starlette/httpx 弃用提示。

补充测量与删除无调用方测试替身方法后验证（单独运行，没有同时运行另一组回归）：

```sh
uv run --project apps/api-python --extra dev --locked pytest -q \
  apps/api-python/tests/integration/modules/imports/test_first_page_covers.py \
  apps/api-python/tests/integration/modules/metadata/test_metadata_opf_observer.py \
  apps/api-python/tests/unit/modules/imports/test_scan_short_transactions.py \
  apps/api-python/tests/unit/modules/imports/test_readable_resource_queue_minimize.py --tb=short
```

结果：**60 passed，18.39 秒**，下表来自这次运行。

```sh
uv run --project apps/api-python --extra dev --locked ruff check \
  apps/api-python/app/modules/imports \
  apps/api-python/tests/integration/modules/imports \
  apps/api-python/tests/integration/modules/metadata/test_metadata_opf_observer.py \
  apps/api-python/tests/test_sqlite_database.py \
  apps/api-python/tests/test_capability_architecture.py \
  apps/api-python/tests/unit/modules/imports/test_readable_resource_queue_minimize.py \
  apps/api-python/tests/unit/modules/imports/test_filesystem_streaming.py \
  apps/api-python/tests/unit/modules/imports/test_scan_short_transactions.py
uv run --project apps/api-python --extra dev --locked mypy --follow-imports=skip \
  apps/api-python/app/modules/imports/application/readable_resource/process_import_task.py \
  apps/api-python/app/modules/imports/application/readable_resource/scan_source_tree.py \
  apps/api-python/app/modules/imports/infrastructure/readable_resource/filesystem.py \
  apps/api-python/app/modules/imports/infrastructure/readable_resource/task_queue.py \
  apps/api-python/app/modules/imports/infrastructure/readable_resource/worker.py
git diff --check
rg -n 'IMPORT_ASSET' apps scripts docs
rg -n 'ensure_import_asset_task|requeue_import_asset_task' apps/api-python scripts
```

Ruff、上述 5 个文件的局部 mypy、diff 检查通过。旧方法名检索无结果。mypy 使用跳过导入模式，不声称完成全应用类型检查。

过程中曾运行的相关子集：核心导入 92 passed；封面与升级 65 passed；第一轮广义回归 873 passed/5 failed/2 skipped；相邻检查 107 passed/2 failed。失败分别定位为预算探测回归、旧类型测试替身、过时的架构清单，均在最终回归消除。新增混合接口测试起初错误要求所有 reader 都有 publication 字段，已按现有契约改为检查资产访问与 comic manifest；新增回滚测试的一处测试导入路径错误也已修正。

额外扩大到整个 imports 单测目录的 Ruff 检查发现既有 `test_limited_import_reads.py:138` 导入顺序问题；未修改该无关文件，未声称此扩大检查通过。所有本任务改动文件的检查通过。

## 真实链路与升级验收

测试路径以 `apps/api-python/tests/` 为根。

| 条件 | 结果 | 证据 |
| --- | --- | --- |
| 实际入口、队列、worker、最终阅读接口 | 通过 | `integration/modules/imports/test_comic_pipeline_reader.py::test_mixed_book_resources_scan_worker_and_reader_bootstrap`：真实 PNG、WAV、PDF、TXT；1 Book、4 resources、6 assets；全部 READY；真实登录后 bootstrap、全部资产 URL、comic manifest 返回成功 |
| 多资源 Book 不提前识别 | 通过 | 混合样例完成扫描后无 IDENTIFY；4 资源完成后才 identified；`test_resource_requests_coalesce_and_book_waits_for_both_resources` 检查重复请求与多资源等待 |
| 既有代表格式仍可导入 | 通过 | 全 imports 回归覆盖既有格式与适配器；`test_audiobook_support.py`、comic pipeline 检查真实读取；替代解析器样例不用于宣称真实格式解码成功 |
| 升级保留书库、Book、资源、有效资产 | 通过 | `test_sqlite_database.py::test_directory_legacy_tasks_upgrade_keeps_asset_ids_and_progress` 从改造前 0011 直接升级；图片、音频各含 4 个 READY 资产 |
| 排队、失败、中断旧任务合并可继续 | 通过 | 同一样例含 QUEUED/FAILED/RUNNING，升级后仅一个非成功 IMPORT_RESOURCE，锚点正确、role 空；真实 worker 完成；成功旧任务作为历史保留 |
| 无新旧同时消费 | 通过 | 升级断言只剩一个资源待办；生产扫描/worker 不再有旧类型生产/消费分支；单消费者约束不变 |
| 稳定 ID、阅读引用、保护字段和封面 | 通过 | asset-1～4、progress.assetId、标题 User title、受保护封面路径及内容保持；增量测试保留未变章节 ID 和进度引用 |
| 不伪造历史成功版本 | 通过 | 升级后所有旧资产 processed_source_version 均为空；不能确定旧版本的资源保守重处理一次；成功后版本与结果一起落库 |
| 重复升级不重复任务/资产 | 通过 | `apply_schema` 连续运行两次；仍一资源待办、4 个原 ID 资产；单文件升级样例 `test_resource_tasks_upgrade_preserves_assets_and_pending_work` 同时通过 |
| 不清空数据库重建书库 | 通过 | 测试在原 0011 实例原位升级，不清空资产、图书或进度；仅测试临时目录/数据库 |

## 故障恢复验收

以下均复用真实事务/队列；故障点可替换，未新增生产测试模式。

| 窗口 | 结果 | 证据 |
| --- | --- | --- |
| 资产批次提交前 | 通过 | `test_image_first_batch_interruption_rolls_back_results`：真实保存 SQL 后抛 KeyboardInterrupt，重新打开 Session 无资产残留；startup＋ContinueImportTask 恢复，3 个唯一有效资产 |
| 第 3 批提交后 | 通过 | 1000 图在 600 张提交后中断，恢复复用 600 张；累计解析仍 1000、资产提交仍 5 批 |
| 全资产完成、收尾前 | 通过 | `test_audio_resource_batches_reuse_tracks_and_finalize_once[interrupted]`：音轨和章节已持久化，重启后不重复提取；`test_image_finalization_rollback_reuses_committed_pages` 收尾失败重试不解析图片 |
| 资源提交、终态未提交 | 通过 | `test_resource_committed_asset_survives_interruption_before_completion`：终态处中断，重启继续仅解析一次；`test_import_worker_completion_recovery.py` 验证终态写重试不重跑业务且阻塞后续任务 |
| 执行期间新变化 | 通过 | `test_resource_changes_during_parse_remain_pending`、`test_resource_change_after_asset_commit_is_not_consumed_by_completion`：不把旧结果标成新版本，保留后续待办 |
| 取消或删除资源 | 通过 | `test_image_cancellation_prevents_batch_writeback` 从真实 worker 运行；解析期间删任务/资源，批次不回写；单文件取消与终态取消恢复回归通过 |
| 扫描批次提交后中断 | 通过 | `test_scan_committed_batch_keeps_intent_and_blocks_incomplete_resource`：已提交节点有持久意图；恢复前不导入部分清单；恢复最终 403 资产 |
| 目录中途异常、路径不可访问 | 通过（本地注入） | `test_source_snapshot_semantics.py` 缺失目录/根目录、保护快照、PRUNE/PRESERVE 与枚举失败；`test_filesystem_streaming.py` 权限错误标记、预算探测和路径安全 |
| 单文件失败、修复后继续 | 通过 | 图片/音频批量样例保存具体错误且成功资产可读；修复仅解析该文件；失败不推进成功版本 |
| 封面发布失败、重试 | 通过 | first-page-covers 中取消/发布失败/收尾回滚测试；旧封面不被异常覆盖；正常仅选中封面发布，必要恢复可再次收尾 |

共同不变量：不丢待办、不伪造版本、不重复资产、不复活删除数据、不误删未完整枚举范围；必要收尾可重试，不要求崩溃下严格一次。

## 规模测量口径

环境：macOS 26.6.2 arm64，Python 3.11.15，SQLite 3.50.4，本地临时目录；最大业务批次 200。耗时来自 perf_counter，单位秒；不设不稳定耗时阈值，不据一次缓存差异断言复杂度。

图片使用真实 32×32 PNG 与生产解析路径，普通页不全量解码；有效 OPF 指定首图封面。音频规模样例仅替换 BoundedAudioMetadataInspector，返回固定标签、3 章节和同一封面候选；**音频耗时只能说明调度与数据库行为，不能代表真实媒体解析性能**。真实 WAV 功能另由混合 Book 测试覆盖。

SQL 列格式：**总驱动调用 / SELECT 调用 / 影响行数 / 实际写事务提交**。SELECT 的 rowcount 不作读取行数；实际返回行数另对音频全局查询用真实结果计数。executemany 是驱动调用数，不是 SQL 只处理一行。连接 commit 回调中没有开启 SQLite 写事务的情况不计实际提交。统计包括阶段内校验 SELECT，不能全部视为生产查询；资产批次与全局整理的计数由对应真实入口包围。

扫描统计包含扫描队列状态和节点/意图事务；资产列仅资产保存业务批次；finish 列是资源收尾及 worker 状态等余下操作，正常含一次收尾提交、一次终态提交。运行状态在前置事务写入，未冒充资产批次。音频 aggregate 为 finish 事务内单列 SQL，不另算提交。

### 初次正常执行

| 样例 | 扫描秒 | 导入秒 | 资源任务 | 媒体解析 | 资产批次 | 元数据汇总/音频整理/封面发布 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 图片 100 | 0.038238 | 0.038389 | 1 | 100 | 1 | 1 / 0 / 1 |
| 图片 1000 | 0.175394 | 0.383365 | 1 | 1000 | 5 | 1 / 0 / 1 |
| 图片 2000 | 0.413464 | 0.612588 | 1 | 2000 | 10 | 1 / 0 / 1 |
| 音轨 10 | 0.022915 | 0.023690 | 1 | 10 | 1 | 1 / 1 / 1 |
| 音轨 20 | 0.025310 | 0.027993 | 1 | 20 | 1 | 1 / 1 / 1 |
| 音轨 100 | 0.038223 | 0.087294 | 1 | 100 | 1 | 1 / 1 / 1 |

| 样例 | 扫描 SQL | 资产 SQL | finish SQL | 音频 aggregate SQL |
| --- | --- | --- | --- | --- |
| 图片 100 | 65/50/210/7 | 8/5/200/1 | 36/31/5/2 | — |
| 图片 1000 | 116/70/2010/11 | 55/25/2000/5 | 36/31/5/2 | — |
| 图片 2000 | 176/95/4010/16 | 110/50/4000/10 | 36/31/5/2 | — |
| 音轨 10 | 64/50/30/7 | 10/6/50/1 | 30/26/4/2 | 7/3/71/0 |
| 音轨 20 | 64/50/50/7 | 11/6/100/1 | 30/26/4/2 | 7/3/141/0 |
| 音轨 100 | 65/50/210/7 | 18/6/500/1 | 30/26/4/2 | 7/3/701/0 |

图片资产写行数为 2N（资产与资产元数据）；音频资产批次为 5N（资产、元数据、3N 章节）。音频全局查询 3 次，分别处理 N 音轨、3N 章节、一行资源元数据：10/20/100 轨真实返回 41/81/401 行。全局写行数 7N+1：音轨顺序、章节安全临时/最终序号及资源统计。3 次 executemany 中包含章节重排的 2 次；整个资源整理仅一次。图片收尾对 N 个成功资产执行一次 COUNT、一次资源元数据应用，无逐图片全集合读取；100/1000/2000 图的 finish SELECT 数均为 31。

这些实际行数与固定次数的汇总证明不存在 N(N+1)/2 累计资源汇总；排序本身允许自然排序的 O(N log N)。1000→2000 图片扫描/导入本轮约 2.36/1.60 倍，没有接近四倍的持续信号。

### 增量与元数据变化

OPF-only 在各样例新增 10 图之后执行；表中规模为初始图片数。

| 初始图片数/操作 | 扫描秒 | 导入秒 | 解析 | 资产提交 | 扫描 SQL | 资产 SQL | finish SQL |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| 100/add_10 | 0.018270 | 0.021298 | 10 | 1 | 49/39/26/6 | 7/5/20/1 | 28/25/3/2 |
| 100/opf_only | 0.013966 | 0.016040 | 0 | 0 | 44/38/5/4 | 0/0/0/0 | 28/25/3/2 |
| 1000/add_10 | 0.065539 | 0.115654 | 10 | 1 | 73/58/25/7 | 7/5/20/1 | 28/25/3/2 |
| 1000/opf_only | 0.054965 | 0.100270 | 0 | 0 | 59/53/5/4 | 0/0/0/0 | 28/25/3/2 |
| 2000/add_10 | 0.196663 | 0.203065 | 10 | 1 | 98/77/25/9 | 7/5/20/1 | 28/25/3/2 |
| 2000/opf_only | 0.110913 | 0.194980 | 0 | 0 | 74/68/5/4 | 0/0/0/0 | 28/25/3/2 |

各增量/OPF-only 组资源逻辑待办均为 1，目录元数据与资源汇总各 1 次，封面发布 0。新增仅写新增资产；原资产 ID、updated_at 不变。OPF-only 无资产保存 SQL。音频同样验证只改一轨、仅 OPF、仅封面时的提取次数与章节 ID，未将其宣称为真实解码性能。

### 无变化扫描

| 已导入图片 | 扫描秒 | worker idle 秒 | 扫描 SQL 调用/SELECT/写行/提交 | 资源执行/解析/资产章节重写/封面发布 |
| --- | ---: | ---: | --- | --- |
| 200 | 0.013048 | 0.001969 | 41/38/3/3 | 0/0/0/0 |
| 2000 | 0.057917 | 0.002181 | 68/65/3/3 | 0/0/0/0 |

3 行写入为扫描任务生命周期；节点 observed_at、资产 updated_at、资源任务 finished_at 都不因无变化扫描推进。无新识别。必要文件系统枚举和状态读取仍存在。

### 中断与恢复单独统计

1000 图在提交 600 图后中断：累计解析 1000、资产提交 5、元数据汇总/发布各 1；finish 驱动调用 58、影响行 8、提交 5（正常为 36/5/2）。音频全部资产提交后中断：各规模仍只解析 N 次、资产提交 1、音频整理/封面各 1；finish 调用 53、影响行 7、提交 5（正常 30/4/2）。音频恢复会话的全局读取行数监听未附加，恢复组不声称已测得该值；正常组三组有完整行数证据。

回滚重试 PDF 样例允许两次解析、两次发布尝试，两次收尾；失败事务无有效成功版本。此行为与已提交可复用结果的崩溃恢复区分，未声称故障后封面发布永远一次。

## 硬性条件汇总

| 条件 | 判定 | 证据 |
| --- | --- | --- |
| A 目录任务数不随文件数增长 | 通过 | 所有正常规模均 1 个 IMPORT_RESOURCE，独立统计扫描/IDENTIFY |
| B 正常汇总/音频整理不超过一次、封面只发布选中产物 | 通过 | 正常计数均 1；图片无音频整理；保护字段不生成无意义封面 |
| C 资产事务按批次增长 | 通过 | 100/1000/2000 图片 1/5/10，增量 10 为 1，OPF-only 为 0 |
| D 无逐文件上下文、祖先、全资产/章节查询 | 通过 | 资产 SELECT 每业务批图片 5、音频整批 6；扫描 200/2000 SQL 调用 67/175；全局读取计数及源代码核对 |
| E 汇总累计处理规模近似线性 | 通过 | 音频查询实际 4N+1、写 7N+1；图片一次 COUNT 和元数据汇总，循环内无全资源汇总 |
| F 无变化无重做 | 通过 | 无变化表及时间戳/任务终态相等断言 |
| G 少量变化仅解析变化媒体 | 通过 | 每规模新增 10 仅解析 10；单音轨修改仅解析 1；OPF-only 为 0 |

## 剩余旧类型与保留理由

生产扫描和 worker 无 IMPORT_ASSET；`ensure_import_asset_task`、`requeue_import_asset_task` 全仓 Python/scripts 无引用。保留项如下（不是另一套导入业务）：

| 位置 | 用途 |
| --- | --- |
| `app/db/alembic/versions/0001*`、`0010*`、`0012*`～`0014*` | 已发布历史结构与逐资产→资源转换，不改写迁移 |
| `app/modules/imports/infrastructure/readable_resource_import_schema.py` | 接纳成功历史行，历史 shape/唯一约束仍有效 |
| `app/contracts/imports.py`、imports `ports.py`、presentation `schemas.py` | 历史任务返回类型兼容 |
| imports `book_completion.py`、library `infrastructure/books.py` | 历史/兼容活动任务查询防提前识别；包含资源类型，不消费旧任务 |
| Web `features/import-tasks/api/client.ts`、`import-tasks-page.tsx` | 历史任务解析与显示；资源类型已接入；未重构 UI |
| `scripts/import-public-domain-format-library.py` | 兼容历史查询统计，不入队或消费旧类型 |
| Python 升级/队列/查询测试、Web client.test、Mobile commonTest | 历史数据兼容样例及禁止产生旧任务断言 |
| ADR 0029 | 明确旧类型只供升级和历史查询 |

## 改动统计与局限

相对任务基线，生产 Python **+48/-204**；测试 Python **+286/-49**；独立测试辅助代码 **+0/-0**。测试内的计数器、替身、固定样例全部计入测试行数，没有新测试框架。另有 ADR 一行替换与本验收文档；提交 SHA 见本次交付消息及 git log。

- 真实 NAS 断连、网络文件系统缓存和权限恢复：**未验证**；本地异常注入不能替代 NAS 实机证据。
- Windows 管道 2 项：**未验证**；本机 macOS 跳过，不冒称通过。
- 属性式版本仍依赖大小、mtime 与适配器版本，不能识别刻意保持属性不变的内容替换；未默认全文哈希。
- 大体积真实媒体吞吐、全部格式的外部解码器部署组合：**未验证**；此处小媒体与替代音频解析不支持这类结论。
- 普通封面文件名如何参与目录识别仍沿用原规则；没有顺手修复或固化新的识别规则。
- 未发现阻塞本轮验收的剩余项；上述平台/真实 NAS 缺口不被包装为通过，不自动开始下一任务。

## 返修：输入未变化的目录失败任务恢复

基线：`develop / 02c4988ddd848e64601ff02b6b3133d2ee1fb8e8`；执行前工作区干净。本节补齐原验收遗漏：此前通过 `ContinueImportTask` 恢复的证据，不能证明书库和目录扫描入口也会恢复未变化输入的失败任务。上文任务 6 数据保留为当时记录，本节说明此次修复后的证据。

### 修改前失败与最小修复

真实调用链：`ContinueLibraryImport → RequestLibraryScan` 或 `ContinueSourceImport → request_source_scan`，然后 `worker → ScanLibrarySourceTree`。目录锚点原来仅在上下文或封面变化时调用 `request_import_resource`，所以 FAILED 任务没有得到恢复机会。

先只增加回归、保持生产代码不变，执行：

```sh
uv run --project apps/api-python --extra dev --locked pytest -q \
  apps/api-python/tests/integration/modules/imports/test_first_page_covers.py \
  -k unchanged_directory_continue --tb=short
```

修改前 **4 failed, 43 deselected（1.08 秒）**：`library-image`、`library-audio`、`directory-image`、`directory-audio` 都在扫描后的同一个断言失败：`assert task.state == "QUEUED"`，实际为 `FAILED`。每例已有两个 READY 资产、一个失败资产，故障注入移除后没有写媒体、OPF、封面或配置。未调用 `request_import_resource` 或 `ContinueImportTask` 绕过入口。

生产修复只修改 `scan_source_tree.py` 的目录资源锚点：完整枚举后统一申请资源待办，`changed` 仍取真实上下文变化或封面缺失。现有队列负责缺失创建、FAILED 复用重排、QUEUED 合并、未变 SUCCEEDED 跳过。未使用 force、未清除成功版本、未改变事务边界、未增加逐文件任务检查或自动重试循环。扫描失败屏障保持原实现。

同一命令修复后 **4 passed（0.96 秒）**；随后扩展临时错误、永久错误、中断、枚举失败四种场景，**16 passed, 43 deselected（4.02 秒）**。

### 验收矩阵

所有场景复用现有 `library` 测试夹具、真实 SQLite、Continue 应用入口和 worker。图片为真实 PNG；音频仅替换昂贵音频元数据提取，返回固定音轨及章节，队列、保存、事务和收尾均真实执行。

| 资源 / 恢复入口 | A 临时错误 | B 提交后中断 | C 成功后无变化 | D 永久错误 | E 身份与复用 | F 枚举失败 |
| --- | --- | --- | --- | --- | --- | --- |
| IMAGE_DIR / ContinueLibraryImport | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 |
| IMAGE_DIR / ContinueSourceImport（锚点） | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 |
| AUDIOBOOK_DIR / ContinueLibraryImport | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 |
| AUDIOBOOK_DIR / ContinueSourceImport（锚点） | 通过 | 通过 | 通过 | 通过 | 通过 | 通过 |

- A：每例 3 个资产；原失败任务由 FAILED → QUEUED → SUCCEEDED，资源任务 ID 不变且总数为 1；只解析失败的 `10.png`/`10.mp3` 一次，其余成功资产版本和更新时间不变。文件内容、大小、mtime 的前后完整快照相等。
- B：真实资产批次提交后、收尾前抛 KeyboardInterrupt，关闭 Session，重新装配 worker，`startup()` 将 1 个中断任务标为 FAILED；两个扫描入口都可恢复，新增解析次数为 0。资源收尾可完成必要排序，未声称首次音频收尾不会更新排序字段。
- C：成功后再次通过同一入口扫描，下一 worker 返回 idle；解析次数 0，资产/资产元数据/章节 INSERT、UPDATE、DELETE 为 0；任务完成时间不变，封面目录全部产物内容和 mtime 不变。
- D：保留故障注入后，仅重试失败文件一次；仍有明确 `IMAGE_FILE_UNREADABLE` / `AUDIO_FILE_UNREADABLE` 和任务错误摘要，失败资产成功版本为空；worker 在有界步数内到 idle，无同轮重新排队循环，其他资产可读。
- E：资源 ID、全部资产 ID、未变化章节 ID、真实持久化阅读进度中的资产/章节引用有效；原有 100/1000/2000 图片与 10/20/100 音轨批量计数测试同时运行。
- F：目录枚举返回首项后抛 PermissionError，扫描进入 FAILED，资源任务仍 FAILED，worker idle、不解析、不删资产；移除目录故障后由同一继续入口完成恢复。既有扫描已提交批次/不完整清单屏障回归同时通过。

### 本次相关回归与性能边界

```sh
uv run --project apps/api-python --extra dev --locked pytest -q \
  apps/api-python/tests/integration/modules/imports \
  apps/api-python/tests/unit/modules/imports/test_scan_short_transactions.py \
  apps/api-python/tests/unit/modules/imports/test_filesystem_streaming.py \
  apps/api-python/tests/unit/modules/imports/test_readable_resource_queue_minimize.py \
  apps/api-python/tests/contract/api/test_import_continue_contract.py --tb=short
uv run --project apps/api-python --extra dev --locked ruff check \
  apps/api-python/app/modules/imports/application/readable_resource/scan_source_tree.py \
  apps/api-python/tests/integration/modules/imports/test_first_page_covers.py
uv run --project apps/api-python --extra dev --locked mypy --follow-imports=skip \
  apps/api-python/app/modules/imports/application/readable_resource/scan_source_tree.py
git diff --check
```

回归结果：**202 passed，50.45 秒**，无失败或跳过；保留既有 Starlette/httpx 弃用警告。Ruff、局部 mypy 与 diff 检查通过。

本次新增的是每个已完整枚举的资源锚点一次队列申请，不按图片/音轨数量判断失败任务。200/2000 张图片无变化扫描实际驱动调用分别为 43/70（原 41/68），SELECT 40/67（原 38/65），均只增加固定 2 次查询；写行数仍为 3、写事务提交仍为 3，全部属于扫描任务生命周期。资源执行、媒体解析、资产/章节重写与封面发布仍为 0。

图片 100/1000/2000 初次资产提交仍为 1/5/10，资产保存 SELECT 为 5/25/50；每个音频资源的全局整理仍为一次。没有恢复逐文件事务或逐文件全集合汇总。

本次未验证真实 NAS 断连与权限恢复，也未执行移动端、浏览器或全仓回归；本地权限异常注入不替代 NAS 实机证据，音频替代解析不代表真实解码性能。没有生产数据库操作或 schema 变更。本次仅提交返修文件，不推送。

本次相对返修基线仅 3 个文件：生产 `scan_source_tree.py` **+11/-9**；测试 `test_first_page_covers.py` **+257/-0**；本验收文档追加记录。没有独立测试辅助代码或新测试平台；测试内固定样例与计数器计入测试行数。提交 SHA 见本次交付消息和 git log。
