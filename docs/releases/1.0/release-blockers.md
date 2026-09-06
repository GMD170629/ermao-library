# 1.0 发布阻塞项

R1 日期：2026-09-06。正在自主执行代码回归和确认缺陷；下方 R0 事实保留为历史线索，当前状态以下表覆盖。环境/决策解除后用例回到 NOT_RUN，不能直接改 PASS。

## R1 状态覆盖与外部条件

本轮确证及修复：

| ID | 类型 / 证据 | 当前处理 |
|---|---|---|
| DEC-05 / RISK-01 / ENV-05 | 全新测试库复现 OPDS 与 v5 各自持久化、双向不可见；`opds-investigation/`。用户批准 1.0 暂不支持第三方进度同步 | 原互通范围 N/A；`f3748d58` 端点和能力声明关闭，主代理独立41项 OPDS/v5 回归 PASS，零进度写入；真实客户端目录/搜索/下载继续验收 |
| TEST-01 | schema 验证器不支持合法 nullable type union；原 33 tests 中 2 errors | 已修复 `6cfbf7bb`，33 PASS；新增正反例，未改 schema 或弱化断言 |
| TEST-02 | 后端同名测试模块收集冲突且锁中缺 coverage 执行依赖 | 已修复 `aa02e0ae`，完整收集 1255；仍有运行失败，另行处理 |
| TEST-03 | Web Reader 测试强制 SDK 不承诺的 selector 字段、移动视口硬编码点击/桌面间距假设 | Chrome 两视口专项 42 PASS；SDK round-trip、原有真实段落恢复与新增缓存重开保护保留，详见 evidence |
| RUN-01 | Windows 后端 36 个运行失败；Android shared/unit/lint/instrumentation 均有失败 | 正在隔离 Linux 重验和分类修复；不得宣告代码门禁通过 |
| RUN-02 | Web 原四浏览器回归失败，含环境启动、过期 fixtures/断言、TXT 章节识别等不同原因 | Chrome 全套 126 PASS / 0 skipped，`854712bb` Web/C 源码；前轮两个 Chrome newPage 启动超时另存，不改断言/超时；该批关闭，最终 RC 仍须完整验收 |
| TEST-04 | Android 仪器 fixture 与已实现契约不符：CRC 完好 bytes、音频 ALLOW 报告、双页偏好、显式章节 identity、目录宿主、双语资源及弹窗坐标等 | 针对性 32 项真机 PASS，见 evidence R1-ANDROID-FIXTURES；其余仪器失败继续，尚未关闭整套 RUN-01 |
| TEST-05 | 旧后端 smoke 请求退役 v4，并存在 uv/PIPE 子进程清理阻塞 | `76707cce`：共享文件日志/有界进程回收，迁移至 v5 原文件；两个真实 smoke PASS，4 个过程/HTTP 正负测试 PASS |
| WEB-01 | Chrome 移动视口新增书库弹窗 max-height 限制下 overflow-visible，底部提交不可达 | 仅调整弹窗 overflow-y-auto；初始化完整向导与桌面/移动布局回归通过；最终 Chrome 全套随后执行 |
| TEST-06 | Web 详情 fixture 缺 canonical chapter fields；封面 mock 不匹配 size 查询串；触摸端套用精确指针菜单假设；旧按钮/目录交互过期 | 修正 fixtures/真实入口，保留封面比例、触摸可达、键盘管理、当前章节和翻页断言；生产封面/菜单视觉未改，Chrome 全套随后留完整日志 |
| READER-01 | 共享 C 章节核未识别“第 1 章”含数词空白的合法标题，Chrome TXT 实际失败 | `854712bb` 修复唯一 C owner、针对性正负例与 WASM 同步；C warning-as-error 测试及 Chrome 全套 PASS |
| ANDROID-01 | 真机漫画目录截图显示按钮 0/1、第二页摘要仍称第 1 页；长目录 Row 无滚动入口 | `805be838` 修复，千页目录与全套目录19项真机 PASS；截图复核继续。早期新测试自身目录 fixture 问题已纠正并保留失败日志；不将 EPUB 早期截图空白推定为产品缺陷 |
| RISK-05 | 视觉夹具追踪发现旧 `legacy_views.book_view` 按进度推导 completed，可能未合并独立 reading status；尚未通过真实请求复现 | 已安排专用新库 FINISHED/UNREAD 与详情/列表投影对照；保留 Locator/进度不变，不直接当作确证缺陷或通过 |

RUN-01 最新拆分：`f3748d58` 后端 Linux 完整1250 PASS + 原有平台2 skip，Windows 两项补测均 PASS；Android host216 PASS、集成 lint PASS。Android 同源码集成真机147项正在运行；不能用局部测试替代这一结果。ANDROID-01 截图已由主代理复核确认页码修正。真实音频短时引擎测试 PASS，长时/逐编码/实际服务端恢复仍待执行。

| ID | 当前事实与证据 | 当前处理 |
|---|---|---|
| ENV-01 | 当前 develop `197e81a8` 干净，已创建隔离发布分支；见 evidence R1 | 旧脏工作树阻塞解除；最终 RC 冻结仍 NOT_RUN |
| ENV-02 | Windows 可用，未登记 Mac/Xcode/配对 iOS 设备 | iOS 编译/适配器/真机 BLOCKED；继续其他平台 |
| ENV-03 | Android `9e896bbc` 在线，用户授权测试；可创建本机专用数据目录 | Android 开发验证、本机新库不再因旧交接缺失停工；正式签名/最终部署条件另记 |
| ENV-07 / DEC-01 | 用户明确暂缓正式安装包构建/导出 | ART-03/04 正式交付 NOT_RUN（用户暂缓），不构建替代物、不填 PASS |
| DEC-03 | 用户接受 ADR 0028 最后事务提交生效及首次迟到离线写的语义 | 语义决策已完成；仍需真实回归，不凭决策计 PASS |
| DEC-04 | 用户接受门禁现有建议阈值；低功耗 NAS 暂缓、本轮本机预检即可 | 阈值冻结；记录本机配置/实际范围，不外推 NAS 结果 |
| ENV-08 | Docker Desktop 已尝试启动但引擎仍不可达；宿主日志确认 Inference manager socket 访问错误 | ART-02 容器路径 BLOCKED；不执行 factory reset 或系统级修复，继续宿主隔离 API/Worker/Web |

ART-02 的本地构建入口现已补充：既有镜像脚本 `--output-dir` 导出 OCI 与版本/hash manifest，命令边界回归17项 PASS；此项仅解除“必须 push 才能构建”的工程缺口。Docker 引擎与双架构实际运行验收仍未解除。

ENV-06 局部进展：10000份紧凑有效 EPUB/PDF/CBZ 已生成、重新打开及校验，负载采集保护4项测试 PASS；真实扫描/延迟/RSS 测量仍 NOT_RUN。约14 MB 紧凑库不代表大文件或10万/30万表现。原工作区后续出现未提交变化，保留并排除于本分支验收，归属核查中。

尚未解除：真实第三方目录客户端（ENV-04）、逐格式完整样本与平台播放承诺（ENV-06/DEC-02）、iOS 执行条件。Progression 客户端不再是 1.0 前提。先检查现有素材与可安全补齐的测试样本，不把旧缺项一概视为无法推进。

## 已确认阻塞项（只登记本轮确证事实）

| ID | Gate/Case | 类型/严重性 | 确证事实与证据 | 状态 / 解阻条件 | 修复 commit / 回归 |
|---|---|---|---|---|---|
| ENV-01 | RG-01 / ART-01..05 | 追溯阻塞；非已复现 P0/P1 | ST-01：develop 工作树非净，RC 未冻结；四模板原已存在且未跟踪 | BLOCKED；负责人确定可追溯 RC，保留用户工作树，记录全部产物来源后重新验证 | — / 未执行 |
| ENV-07 | RG-01 / ART-02..04 | 构建交付入口缺项；非运行缺陷 | ST-03：Android build.gradle.kts未设signingConfigs，CI只组装Debug；iOS有Release ArchiveAction但未找到export脚本/ExportOptions；镜像现有发布脚本默认push，隔离RC构建参数待补 | BLOCKED；交接可审查的正式签名APK流程、Xcode Archive与IPA导出/安装流程、无推送RC镜像构建部署方案；本轮不改配置 | — / 未执行 |
| ENV-02 | RG-01..05 / 所有 iOS 路径 | 环境阻塞 | ST-04：当前 Windows 主机未提供 xcodebuild；本任务无可用的已登记 Mac/Xcode/配对 iOS 真机运行环境 | BLOCKED；提供授权 Mac、Xcode/iphoneos、配对解锁且 Developer Mode 可用设备、可达测试服务器；禁止 Simulator 或禁用签名绕过 | — / 未执行 |

这里只确认本轮执行环境的缺口，不推断用户没有其他机器、证书或设备。

## 未交接的执行前提（环境待补，不是业务缺陷）

| ID | Gate/Case | 缺项与现有事实 | 状态 / 确切解阻条件 |
|---|---|---|---|
| ENV-03 | RG-01..05 / 原生与新部署 | 未提供同 RC 测试服务器/空数据根、两种架构部署目标；Android 正式签名配置/指纹及当前授权真机序列号未登记；iOS Team、证书、描述文件、有效期与 IPA 安装方式未登记。adb/docker 可定位不等于上述条件具备 | BLOCKED（执行前提未交接）；提供隔离数据/源文件目录、服务器与代理 HTTP/HTTPS/端口配置、有效 Release 签名和精确设备、安装权限；不清理真实旧数据，不以历史设备号默认选机 |
| ENV-04 | RG-02 / OPDS-01..03 | 静读天下具体版本/平台/安装环境待补；第二个独立实现的真实客户端名称/版本未确定 | BLOCKED；登记两个真实应用及可验证各项能力的设备、合法样本和测试账号；不能以 curl 或同一应用两版本代替两个客户端 |
| ENV-05 | RG-02/RG-04 / OPDS-04 | 未交接明确支持 OPDS Progression 扩展的真实客户端与版本；目录客户端不推定支持进度 | BLOCKED；保留承诺时提供支持扩展的客户端，在全新数据上做 GET/PUT 与第一方互通；如调整承诺必须负责人先决策，本轮不删除声明 |
| ENV-06 | RG-03/RG-05 / 样本、LOAD-* | 已有18份候选文件及本轮SHA-256登记于矩阵§3.1，但未交接完整逐格式正常/复杂/异常实样、音频容器编码探测清单、1万/10万/30万有效书籍/可读资源数据集、低功耗目标机预算及采集执行入口 | BLOCKED；合法实样与清单到位，区分 file/Node/Book/Resource/Asset；批准隔离空间与数据分布；补齐请求级延迟/锁等待/内存等采集步骤；现有生成器不能证明这些已准备 |

## 静态风险 / 待复现（不是已确认缺陷）

| ID | Gate/Case | 源码/历史线索 | 下一步与关闭依据 | 状态 |
|---|---|---|---|---|
| RISK-01 | RG-02/RG-04 / OPDS-04 | README.md:38仍承诺同步；opds_runtime.py:660→bootstrap/reader.py:27明确retired v4→resource_reader.py:299/resource_repository.py:338旧ReaderResourceProgress，与v5_repository.py:203的ReaderResourceProgressV5不同；完整路径见release-gate.md §6 | 新数据协议探针与支持扩展真实客户端双向联调；记录协议位置与第一方 opaque Locator 能力边界，不只检查目录 | 静态风险/待复现 |
| RISK-02 | RG-03 / REF-AZW、REF-PRC | scripts/prepare-public-domain-format-library.py:432–444 将 MOBI 同源复制到 AZW/PRC；test-data/library/mobi/CORPUS.md:3也说明扩展名变体，本轮hash相同；:465记录不可编码音频；现有PDF/漫画极小样本不证明正常读物/大页体验 | 同源文件最多证明扩展名路由；补独立来源和内部变体事实。缺编码器不是产品 REJECT_EXPECTED | 样本覆盖风险 |
| RISK-03 | RG-03 / 全端安全、缓存、目录 | HIST-01/02 留有 WebKit 缓存、Reader UI、原生与权限环境缺口；历史执行 commit 不完整 | 当前 RC 逐项复现，分别登记实际失败；保留可读输出、危险副作用缺失、原文件不变证据，不搬历史失败数 | 历史线索/待复现 |
| RISK-04 | RG-01/RG-03 | README.md:39仍称原生Reader建设中；AGENTS.md的早期Mobile“音频不可用”/Reader v4文字与现行播放器/v5源码并存；HIST-03 曾报告 lint/全量套件缺口 | 按现行入口验收，不能依据旧阶段说明取消音频；当前 RC 重跑必要检查，不能照抄历史结果 | 范围冲突/待复现 |

## 范围和阈值待决（不改变既有承诺）

| ID | 关联 | 需要冻结的决定 | 状态 |
|---|---|---|---|
| DEC-01 | RG-01 / ART-04 | iOS Release IPA 合法导出/安装方式、适用设备、有效期与负责人；不默认商店/TestFlight；Android 仅正式 APK | 待决定；未冻结不可放行 |
| DEC-02 | RG-03 / AUD-* | 逐容器+编码+平台/浏览器冻结 PLAYBACK_REQUIRED / IMPORT_ONLY / REJECT_EXPECTED；常用可播组合不得失败后降级；未知能力不能直接列 REJECT_EXPECTED | 待范围签收；矩阵保留所有源格式 |
| DEC-03 | RG-04 / POS-07 | 记录 ADR 0028 最后事务提交写入生效；离线首次迟到可能覆盖当前位置，是否符合 1.0 产品接受范围由负责人签收；若不接受另授权修复 | 待实测与签收，不引入新冲突算法 |
| DEC-04 | RG-04/RG-05 | release-gate.md 的保存间隔/确认延迟/音频恢复误差与性能建议阈值、机器预算、并发、数据分布、采样方法 | 待冻结；建议值不是实测值；失败后不得临时放宽 |

## 后续缺陷登记规则

后续确认缺陷应补：ID、Gate/Case、严重级别、平台/格式/账号角色、RC/产物、前置与最小复现、预期/实际、脱敏证据、修复 commit、原失败和相邻用例回归、关闭人/时间。状态为待复现→已复现→修复中→待回归→已关闭；证据可标自动失败/真机复现/压力复现。没有回归证据不能关闭。

门禁内硬要求失败无论 P0/P1/P2 均阻塞放行。延期只允许门禁外轻微问题且须负责人明确同意；本轮无已批准延期项。
