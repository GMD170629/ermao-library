# 1.0 发布证据与最终签收

当前结论：**NOT_RUN / 尚无放行依据**。R0 仅进行只读盘点与四份文档整理，没有构建、部署、真机、协议、回归或性能实测。

## R0 基线与工作树边界

| 字段 | 2026-09-06 记录 |
|---|---|
| 分支 / HEAD | develop / `9a4901edba41fab786bd28ff92144ff802ddfab3` |
| HEAD 时间 | 2026-09-05T08:05:15+08:00 |
| 模板基线 | `9ff93969bf46c24d24e97c0103cae50244fd64aa`；没有回退 |
| 已提交差异 | 一条提交 `9a4901ed feat: unify cross-platform reader and mobile UI`；111 文件，7306 additions / 2370 deletions；覆盖移动 UI、Reader、设计契约、工作流与开发入口 |
| 开始时工作树 | porcelain v1：326 个修改、120 个删除、47 个未跟踪条目（未跟踪目录按条目计，不是文件数）；四份模板已存在，目录为未跟踪 |
| 结束前增量观察 | porcelain条目493→494：新增已修改 `apps/mobile/androidApp/src/androidTest/kotlin/com/ermao/library/features/reader/ReaderFb2InstrumentedTest.kt`；本轮未写该文件，未推断修改来源，保留现场。计数为当时快照，不声称工作树已冻结 |
| 解释边界 | 源码、README、工作流、测试均有既有修改；下述静态盘点来自当前工作树，不是纯 HEAD 证据；路径行号随后续修改可能变化 |
| 本轮写入范围 | 仅本目录四份 Markdown；没有 commit/push、分支切换、stash/reset、清理旧数据或业务修复 |
| Git 读取方式 | `git -c safe.directory=D:/www/ermao-library ...`，仅命令级设置；未修改全局 Git 配置 |
| 本机工具探测 | Windows / PowerShell；Get-Command 可定位 adb、docker、pnpm，未定位 xcodebuild、uv；工具存在不证明服务运行、设备在线或签名可用 |
| RC | 尚未冻结；不能用此脏工作树直接声明同一 RC 放行 |

## 静态证据登记（不是测试 PASS）

| ID | 方法 / 来源 | 范围与结论 | 验收效力 |
|---|---|---|---|
| ST-01 | `git ... branch --show-current`、`rev-parse HEAD`、`status --porcelain=v1`、`log 基线..HEAD`、`diff --stat 基线..HEAD` | 上表真实分支、提交差异与工作树计数 | 仅基线盘点 |
| ST-02 | 读取 AGENTS.md、.cursor/rules/{architecture,quality-and-i18n,refactoring,release-version}.mdc、docs/testing/test-execution-policy.md、四份原模板 | 当前适用开发、测试与发布规则；本轮无业务改动，不执行其发布全量检查 | 仅规则依据 |
| ST-03 | release-gate.md §6 中源码锚点 | 发布范围、构建/入口、格式、OPDS、v5 静态调用链 | 不证明功能成功 |
| ST-04 | `Get-Command adb,xcodebuild,docker,uv,pnpm -ErrorAction SilentlyContinue` | 本机命令可用性；未启动设备/服务、未检查凭据 | 仅环境探测 |
| ST-05 | scripts/prepare-public-domain-format-library.py:432–444、:465；scripts/import-public-domain-format-library.py:39；scripts/python_worker_import_smoke.py:39 | 现有小样本准备/内部导入/Worker smoke，不是规模验收；AZW/PRC 同源复制及缺编码器需另补实样 | 仅样本与入口风险 |
| ST-07 | Get-FileHash -Algorithm SHA256与Get-Item读取18份test-data候选 | 矩阵§3.1记录实际大小/hash；MOBI/AZW/PRC同源得到相同hash；没有解析或播放 | 仅素材登记 |
| ST-06 | 本轮四文档的引用、ID、状态、写入边界复核 | 独立只读复核并修正文档命令描述；Markdown表列数、阻塞ID唯一性及引用检查；起止porcelain对比；未运行应用测试 | 只证明 R0 文档检查 |

原始工具读取结果保留于本任务记录；正式证据不得依赖聊天中的静态摘要。

## 门禁汇总

| 门禁 | 状态 | 覆盖 | 关联阻塞/待决 |
|---|---|---|---|
| RG-01 | NOT_RUN | ART-01..05：同 RC 全套产物、双架构服务、APK/IPA、签名、安装 | ENV-01..03、ENV-07、DEC-01 |
| RG-02 | NOT_RUN | INI/IMP/CON/OPDS：新数据闭环、两种组织模式、三种网络、两个独立客户端 | ENV-02..05、RISK-01 |
| RG-03 | NOT_RUN | REF/PDF/COM/AUD：逐格式×三端×正常/复杂/异常 | ENV-02..06、DEC-02、RISK-02..04 |
| RG-04 | NOT_RUN | 六方向×各格式，POS-01..11 与 OPDS-04 | ENV-02..05、DEC-03、RISK-01 |
| RG-05 | NOT_RUN | LOAD-00/10K/100K/300K/FULL/RESCAN/RECOVER/EVIDENCE | ENV-02、ENV-03、ENV-06、DEC-04 |

子项缺明确前提标 BLOCKED；门禁汇总仍为 NOT_RUN，不能把环境阻塞转成已执行失败或通过。

## RC 与产物清单（全部待填）

| 字段 | 记录 |
|---|---|
| RC commit / 版本 / 源码可追溯快照 | 待冻结；tag 未创建 |
| 工作树 / 子模块 / 依赖锁摘要 | 待对实际 RC 记录；同版本号不能代替同一二进制 |
| Web/API/Worker | linux/amd64、linux/arm64 各产物路径、digest、构建/部署日志待补 |
| Android | Release APK 路径、SHA-256、签名证书指纹、applicationId、versionName/versionCode、设备/安装日志待补 |
| iOS | Release Archive/IPA 路径、SHA-256、Bundle ID、版本/build、Team/描述文件有效期/导出方式、适用安装路径及真机日志待补（不记录私钥） |
| 完整回归 / 真机 / OPDS / 性能 | 均待执行；无本轮 RC PASS |
| 范围、环境、阈值冻结 / 负责人 | 待签收；所有者尚待指定 |

## 历史报告隔离登记

| ID | 日期 / 对应 commit | 来源与覆盖范围 | 限制与本轮状态 |
|---|---|---|---|
| HIST-01 | 2026-09-05 工作记录；报告未固定执行 commit，待补 | docs/reader-safety-v4-verification.md:17：原生安全、WebKit 缓存、Reader UI、符号链接环境缺口 | 历史未闭合事项，R0 未复现；NOT_RUN，不照搬失败数或通过数 |
| HIST-02 | 2026-09-05；报告未固定执行 commit，待补 | docs/mobile-reader-toc-verification.md:17：Android 目录/跳转/面板/冷启动；iOS、TalkBack/键盘等缺口 | 不是本工作树重验；NOT_RUN |
| HIST-03 | 目录标记 2026-09-03；执行 commit 未记，待补 | apps/mobile/design-qa/visual-runs/20260903-android-settings-v1/final-report.md 与 run-manifest.json：Android 设置视觉、局部仪器与 debug 构建 | manifest 仍 IN_PROGRESS，产物栏空；不是 Release APK/全量回归；历史设备不证明当前在线；NOT_RUN |

上述文件记录的缺陷或失败仅作为待复现线索。未固定日期/commit/hash 的报告不得晋升为当前证据。

## 执行证据位置与必填字段

后续约定受控证据根 `E = artifacts/releases/1.0/<rc-commit>/`，本轮未创建、未声称有文件；可改为等价持久 CI artifact URL，但必须记录访问和保留期限。矩阵中 `E/<case-id>/` 均为**计划位置**。

每个展开后的用例须记录：case_id、gate_id、RC commit、工作树状态、产物 digest/hash、设备/OS/浏览器/第三方名称版本、账号角色、样本 ID/SHA-256/容器编码/大小、前置、实际命令或人工操作、预期/实际、状态、时间、执行人、日志/截图/录屏/请求时序路径、blocker ID。运行后不可只保留汇总 PASS。故障注入与正常请求分开统计；日志脱敏，不公开令牌、密码、私钥、真实读物正文或完整 Locator。

## GO 签收

以下全部完成才可 GO：五个门禁所有适用硬要求 PASS；P0/P1 清零；无任何门禁内失败；N/A 有预先批准的范围依据；产物和证据属于同一 RC；公开能力与实测一致；负责人签收。无缺陷条目不等于零缺陷。

| 复核字段 | 当前 |
|---|---|
| RG-01 / RG-02 / RG-03 / RG-04 / RG-05 | NOT_RUN / NOT_RUN / NOT_RUN / NOT_RUN / NOT_RUN |
| P0/P1 清零与门禁失败清零 | 未核实 |
| 同 RC 产物与完整证据 | 未具备 |
| 范围/阈值批准，负责人/日期 | 待填 |
| 最终结论 | NOT_RUN / 尚无放行依据 |
| 实际发布操作授权 | 本轮未授权 |


