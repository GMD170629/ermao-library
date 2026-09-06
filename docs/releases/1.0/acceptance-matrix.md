# 1.0 发布验收矩阵

最新覆盖`7e207c38`：POS-03 Chrome桌面/移动视口MP3暂停且已确认后强杀、同profile重启及真实重登录恢复子项PASS，误差0/205.804ms。登录前完整IDB保留、401后既有隐私清理、随后原服务端快照和实际播放器恢复分别验证；不覆盖未确认/播放中强杀、免重登录及其他引擎/原生平台。证据和历史测试预期修正见release-evidence首节，达到该子场景停止条件。

最新覆盖 `02d6ea2d`：POS-04 Chrome桌面/移动视口EPUB离线pending跨页面关闭/重建完整保留，重连ACK、IDB清pending与独立GET分别965ms/959ms内一致，实际恢复第二章；这两个子项PASS。原live生产Chrome相邻PASS，MP3恢复误差440ms；源码/样本/无5xx/清理复核通过。仅补当前必测用例，共用原setup owner，达到DEC-07停止条件，不继续扩工具。POS-03进程强杀及POS-04原生/另端异常交接仍待执行，不由页面重建结果覆盖；证据见release-evidence首节。

当前主候选 `d19a7942` 已整合交接测试。MP3 W→A/A→W的正常子项及原online相邻回归均PASS；TEST-11完整时窗已PASS。POS-03进程重启、POS-04离线恢复等仍须实际执行，其他格式/原生iOS状态不由这些结果覆盖；后续旧的待相邻/待整合记录保留为历史。

新增实际通过：TEST-11生产Chrome完整1800秒时窗与原后续重开/PWA流程（末条采样1805229.4ms、恢复误差433ms）；MP3 W→A与A→W正常交接（5857ms→5857ms、15749ms→15763.868ms），独立新Web会话，Android真实引擎及5/10秒确认。仅这些子项PASS；跨端测试原online相邻回归待完成，不代替异常组合、其他格式或最终RC。详见release-evidence最新证据。

最新覆盖：Android AUDIO-07/08/09原捕获、跨资源串写、Stop后迟到重启已修复并真实回归，主整合至 `b912b427`；AUDIO-06原FLAC5/10秒确认及暂停8610ms→重开8610ms通过，PCM恢复误差10ms。POS-02/08上述子场景PASS，原RED保留；不代表全部资源/账号/服务器/格式组合通过。下文旧候选和FLAC FAIL状态为历史，完整证据见release-evidence首节。W↔Android同步和进程重启仍NOT_RUN，iOS相关项仍BLOCKED；TEST-11完整时窗待实跑，未冻结RC。

配套硬要求与建议阈值唯一见 release-gate.md；事实来源见其 §6；证据登记见 release-evidence.md；缺项见 release-blockers.md。本表是可执行计划，**未执行不计 PASS**。

## 1. 执行基线与展开规则

当前处于R2逐项验收（旧R1证据编号保留）。READER-03原问题关闭；AUDIO-05已由 `9938c350` 修复，新包AAC恢复9906ms→9906ms及MP3相邻PASS；FLAC原期限失败AUDIO-06仍保留。AUDIO-07捕获饥饿已受控复现，旧候选的跨资源绑定风险RISK-06待实际验证，新候选 `9df3d412` 暂未整合。AUDIO-04原生产全用例PASS，TEST-11完整1800秒采样末段仍待补齐。SYNC-02自动修复通过；用户授权3107/3108后工具仍拒绝启动，ENV-11待手动启动，RED/GREEN未执行。IMP-01两模式实际UI及同库只读持久化/拓扑正常样本子项PASS；原执行超期/未存HTTP响应限制保留，不计完整浏览器命令或最终RC。后续旧状态保留为过程记录，具体新证据见release-evidence首节。

SYNC-02启动修复 `76a88845` 已通过受控竞态及完整Web自动回归、独立复核，实际Chrome待执行；AUDIO-04已复现Next默认超时在媒体背压下截断上游，有限空闲超时修复候选仍待原长播放验证，不改2秒阈值。

最新实际结果：RG-03/04长音频AUDIO-04在约12分钟停顿超过阈值，1800秒验收FAIL；PWA后续步骤未执行。测试错误记录/服务清理/配置恢复完成，TEST-10工具闭环停止。DEC-08：OPDS客户端由负责人放行并自行测试，不再等待环境补齐；代理未完成双客户端实测，协议自动回归保持。

RG-04新增SYNC-02：已在真实coordinator与恢复owner的受控端口链复现“旧bootstrap→新ACK清pending→启动恢复旧位置”；归属POS-01/POS-06。正在隔离修复，实际Chrome/IDB尚待验证；不扩大已关闭AUDIO-03工具。W↔A方向现具备授权设备和本机服务条件，未执行子项为NOT_RUN，不能再沿用旧ENV-03将全部方向阻塞；涉及原生iOS方向仍受ENV-02阻塞。

DEC-07：默认冻结测试辅助功能扩展，复用现有入口。辅助改动必须说明对应Gate/Case或缺陷、现有方法不足及停止条件；闭环通过即停。人工允许场景直接操作留证，必要竞态/持久化/安全自动回归保留；不以工具数量或测试数量判断发布接近完成。

ANDROID-03最新覆盖：加强原生目录完全展开前置后，默认真机完整148 PASS/0 skip、整类19 PASS、单项1 PASS。原断言及主APK保持，当前移动自动回归PASS；旧147/1原因尚不能唯一归因，失败与几何证据继续保留。此项不代表RG-03逐格式或最终RC全部通过。

AUDIO-03最新覆盖：真实Chrome原快速关闭恢复链路PASS，误差6ms，30秒观察不冒充30分钟；同一运行原文件与910应用文件hash不变且服务清理通过。测试生命周期修复40项通过，production PWA新候选待复验。下方“待真实回归”的旧记录仅保留历史。

当前执行点：AUDIO-03关闭竞态补充后完整Web465 PASS/0 skip，真实原失败链路待回归；READER-03余下MathML实体上下文对照FAIL；ANDROID-03正在补目录完全展开的可观察几何前置。上述均未冻结RC，也未将局部自动结果计为整组放行。

AUDIO-03当前为修复后待真实回归，完整Web465 PASS不能覆盖原两次真实恢复FAIL。独立PWA审查未发现断言削弱，确认有限SW/离线导航范围；测试生命周期与配置隔离另行修正（TEST-10）。正式30分钟播放尚未运行；当前没有大规模压测或数据生成任务。

当前增量：Chrome长MP3的30秒观测已跑，但随后seek/pause/reopen误差438000ms导致整个用例FAIL（AUDIO-03），不能计30分钟或完整音频恢复PASS。Android同包聚焦重现1+19+1通过未关闭原全量失败，继续测试几何/原生状态诊断。300k准备按DEC-06已实际停止，部分文件保留而非PASS。

DEC-06 最新覆盖：用户接受当前数据作为导入性能依据，将超大规模验证转为脚本按需单独运行。RG-05 本轮“本机导入性能预检”范围 PASS，依据 `local-load/measurement-20260906-065525/` 的真实 1 万导入/重扫；10万/30万及完整时长压力场景不再作为本轮代码收敛阻塞，也不填写为已实测 PASS。下方较早“仍必须完成大规模长时”描述据此调整。其他门禁和同 RC 追溯要求保持；尚未整体放行。

移动自动完整回归最新 **FAIL**：shared429/Android unit218/lint通过；默认真机148项中目录面板第二次手势滚动断言1 FAIL，其余147 PASS且零skip。失败分类与同包重现正在执行（ANDROID-03），不是已证实产品缺陷，也尚未关闭为测试问题。已通过的Android在线MP3专项与Chrome PWA子项独立保留，不宣布整组门禁放行。

Chrome PWA补充已实际通过两个视口：生产Web构建+真实新库/EPUB/MP3闭环、Service Worker控制/缓存分工、断网导航回退和联网后认证，`release-live-pwa/r1788685159444-w0/`及`r1788685202566-w1/`。这是明确范围的PASS，不等于PWA安装/更新/离线位置异常恢复、原生iOS或整个RG-01..05通过。

规模样本当前状态：100k紧凑三格式数据准备PASS（实际40000 EPUB/30000 PDF/30000 CBZ、100000唯一hash）；100k负载测量仍NOT_RUN。300k仅已启动准备，结果未定。完整窗口与真实前台媒体混合负载要求保持，样本准备与压力结果不混计，详见release-evidence当前恢复入口。

最新 Android 实际增量：`227e09f1` 生产源码，`android-live/android-1788684078319/` 独立MP3在线用例1 PASS，实际5/10秒客户端确认与服务端GET一致，暂停9930ms、重开9930ms并同步收敛。覆盖 AUD 单轨MP3短时及 POS-02/恢复部分；长时、后台、异常/跨端、其他编码仍未执行，不把之前两次bootstrap失败或第三次测试键序误报抹去。源码与测试差异、包hash、七文件不变证据见release-evidence。

`d1fc48a9` 已修复共享位置 ACK 重复解包，32 项针对性测试通过；仍须实际 Android 在线确认。独立真机入口两次全新库运行均 FAIL，第二次明确 `READER_BOOTSTRAP_INVALID`，尚未请求媒体，不计播放或同步通过。`c5157d71` 的 10万/30万负载选型工具 88 项主复核通过，100k 样本准备继续，不计规模性能通过。MOBI 第二轮独立审查仍有 noscript、删除节点尾随正文、raw-text 实体语义问题，候选未放行。

当前仍为五组门禁并行收敛，未有完整GO。`e8d4209e`之后READER-03确认MOBI族HTML公开子资源422，修复/真实回归进行中；SYNC-01检查移动端正常位置ACK解包边界。已验证的目录、原文下载、后端存储、客户端本地落盘与客户端服务端确认必须分开计数。10k短时性能通过不代替10万/30万长时验收，正式产物继续暂缓。

`61d36d02`新增AAC/WAV/FLAC×Chrome桌面/移动视口6 PASS；实际MIME、正常API无5xx、5/10秒服务端位置更新及重开误差≤200ms均已核实。结合此前MP3，四种音频组合获得短时真实链路证据；仍不覆盖全部编码、30分钟、多轨或原生同步。`32175712`已防止AIFC样本被AIFF别名冒充，18 section FB2派生样本的XML/来源限制另记。

`c7f5d5eb`安静本机10k预检完成：19685请求0失败，增长扫描列表/搜索/详情/保存p95约63/64/19/60ms，原文件hash、资源关联与重扫进度保留检查通过。记录135/180秒负载、89.1%增长活跃覆盖、紧凑三格式约14MB及仅HTTP四端点的限制，未把此项扩成完整RG-05、10万/30万或实际三端读听PASS。

`27bad491`检查点：后端`7c6c991c`完整Linux1284 PASS+Windows补测2 PASS，Ruff/mypy通过；59份实际语料的53资源bootstrap和59原文件hash/Range通过，目录环境/样本限制见证据，不代表客户端播放。Chrome安全报告66/Backend64与既有Android66一致性通过。负载原文件及关联完整性工具36项PASS，安静10k重测待执行。

`7c6c991c`后端增量：MEDIA-02默认封面修复、主7项回归及严格真实Chrome两视口2 PASS，MP3实际MIME与5/10秒服务端读回已核实，无API 5xx。后端位置HTTP探针重新PASS；完整后端和59样本验收正在执行。`b93e1025`加强开屏动画等待后另采稳定截图，具体证据与限制见最新检查点。

`d6b11360`增量：Chrome完整126 PASS、Web生产构建PASS；Android完整真机148 PASS，共享416/Android单元218/lint PASS。实际PCM播放的5/10秒生产SQLite读回及暂停重开误差8ms通过；在线确认、进程死亡、长时/逐编码不在该测试覆盖内。严格真实后端MP3两视口仍因MEDIA-02待复测。下文较旧状态保留追溯，以最新证据为准。

最新`c13a7034`：独立阅读状态投影含bootstrap修复及相邻回归PASS；音频时序的Web459/KMP23/Android6通过，Android真实落盘继续。严格MP3两Chrome视口仍FAIL（默认封面500），不得使用旧WAV测试scope误报MP3通过。10k真实导入/重扫已执行但性能与收尾失败，已修复慢查询及维护检查放大点，待独立安静复测。所有数量、源码与证据位置见 release-evidence.md 最新检查点；没有整体GO。

`c14b3033` 增量状态：RG-04 音频自动保存间隔与 reading-status 公共投影确证 FAIL，修复及复测中；真实Chrome新库→7种文件导入→EPUB保存/重开已有局部证据，整个闭环仍FAIL，不覆盖Android/iOS或全部格式。音频快速暂停修复单测3项PASS，后续完整Chrome回归待执行。两镜像锁定安装入口 `bc94df7d` 的边界测试和WSL实际安装PASS，ART-02实际容器仍BLOCKED。具体路径见证据台账最新增量。

RG-05 可执行入口：`scripts/python_release_load_precheck.py`，使用真实文件导入、实际 API/Worker、分扫描状态请求日志和进程树 RSS；10000份紧凑样本就绪。工具4项保护测试 PASS，负载结果待实际运行，命令与证据见 R1-LOAD-OBSERVER。默认短窗口仅为本机预检，完整时长/规模要求保持。

当前代码验证检查点 `80c5d5b9`：后端完整跨平台1252项覆盖、Android host216与lint通过；实际真机全套147项全部通过，Debug/test两包hash和冷启动证据见 R1-ANDROID-FULL。AUD-* 目前新增真实 Media3 短时PCM引擎证据，仅覆盖列明操作。59份公开格式样本已登记，实际播放状态继续逐组合展开，不能批量填 PASS。

R1 当前基线为干净的 `develop@197e81a808ba32595a8a6ffeda62422b3a7d3473`，在 `D:/www/ermao-release-1.0` 的 `codex/release-1.0-convergence` 分支执行。历史 R0 工作树不是当前基线。最终 RC/产物仍待冻结；每次执行须记录实际改动，不能将有源码变更的结果登记成纯 HEAD。

2026-09-06 用户决定：正式安装包构建/导出暂缓，Android 真机测试已授权；接受 RG-04/05 现有阈值及 ADR 0028 语义，低功耗 NAS 暂缓、本轮仅本机预检。下方原始计划仍保留完整门禁，实际子项执行状态以 release-evidence.md 的 R1 登记为准；本机/自动检查不替代尚未执行的真机、正式产物或真实第三方客户端路径。

以下公共前置是每行的组成部分，减少重复而不省略要求：

- **P0**：冻结同 RC 的产物/依赖锁/版本，专用新数据库与源目录、测试管理员及普通账号，备好请求/屏幕证据；不触碰真实旧数据。
- **P1**：P0 + 对应 Release 产物、真实服务器、Web 浏览器；Android 精确授权物理设备，iOS 配对解锁物理设备/Mac/签名/安装方式。每行均注明平台；W/A/I 分别为 Web/Android/iOS。
- **P2**：P1 + 下方样本组真实文件，SHA-256、合法来源、大小、内部容器/编码、章节/页/轨事实和预期清单。样本 ID 是预留登记槽，**不是已存在文件**。
- **P3**：P2 + 同账号三端、可控制请求与回包延迟/断网的隔离网络、已冻结保存间隔/位置误差；故障注入实现入口待补，可由受控代理人工操作，不能改业务代码制造证据。
- **P4**：P1/P2 + 大库隔离环境与阈值全部冻结，真实有效资源数据集、负载/采集步骤已复核。
- **E**：`artifacts/releases/1.0/<rc-commit>/`，仅计划证据根；每行保存到 `E/<ID>/`，实际执行后登记具体路径、时间、操作者、hash、原始结果。

参数组须按 `ID/平台/源格式/样本/场景` 展开成独立执行记录；不能一次 PASS 覆盖未跑组合。默认 NOT_RUN；已明确缺交接前提的真机、真实客户端、素材/大库条目标 BLOCKED。若共享行含 W/A/I，W 不因 I 阻塞被伪造为已执行；各子项分别记状态。

R1 用户范围调整：Web 仅 Chrome（桌面/移动视口），Firefox、WebKit/Safari 不再执行。旧四浏览器回归为历史诊断，不混入最终 Chrome 通过率；Android/iOS 原生范围独立保留。Playwright 项目为 `chrome`、`mobile-chrome`，使用实际安装的 Chrome channel。

## 2. 发布、初始化与接入

R1 / DEC-05：用户批准 1.0 不支持第三方进度同步，OPDS-04 原互通要求为 N/A。关闭验证以 `f3748d58` 执行：目录不发布 Progression 链接，旧 GET/PUT 不再同步且无进度/DML写入；OPDS/v5 五个测试文件41项 PASS，见 evidence R1-OPDS-CLOSURE。真实第三方目录/下载仍按 OPDS-01..03 执行。

命令编号 C-* 见 §7，人工操作依据 release-gate.md §6 的实际 UI/API；所列命令本轮均未运行。

| ID / Gate | 前置、平台/样本 | 具体命令或人工步骤 | 预期 | 证据位置 | 状态 / 关联 |
|---|---|---|---|---|---|
| ART-01 / RG-01 | P0；Python/Web/KMP/Android/iOS | C-01..05；发布候选完整回归，分别记录当前结果；无可用执行器的检查停为 BLOCKED | 必要检查全部通过，无 skip/弱化；原生最终证据来自真机 | E/ART-01/ | NOT_RUN；ENV-01..03 |
| ART-02 / RG-01 | P0；linux/amd64、linux/arm64 各一行 | 按 C-06 对同 RC 构建隔离产物；逐架构启动 Web/API/Worker，执行 INI-01 和每媒体首条样本 | 三组件健康、网关正常、初始化/导入/媒体链路正确；一架构不代替另一架构 | E/ART-02/；既有本地OCI导出入口 | BLOCKED；ENV-08 Docker引擎不可达；入口已补齐但无实际容器产物 |
| ART-03 / RG-01 | P1；Android 正式签名、授权测试设备 | C-07；确认正式签名/包版本后，通过现有安装方式安装至专用测试设备，不清除用户数据；冷启动登录和读听，核对 crash/ANR | 正式 Release APK 可独立安装使用；签名/版本/hash/设备可追溯 | E/ART-03/ | NOT_RUN（用户暂缓正式构建）；DEC-01；开发真机结果独立登记 |
| ART-04 / RG-01 | P1；iOS Team/证书/描述文件、设备 | C-08；Release Archive→正式 export→IPA；记录合法安装方式并按其安装，在真机冷启动、登录、读听 | IPA 签名有效、设备适用且实际运行；无 Simulator/无签名绕过 | E/ART-04/ | NOT_RUN（用户暂缓正式导出）；DEC-01；原生设备另受ENV-02阻塞 |
| ART-05 / RG-01 | P0/P1；三产物 | 比对根/Web/Python版本与运行版本、Android/iOS版本build、构建commit及hash；复核包中测试注入/凭据；与全部报告关联 | 同一 RC 版本组合，无测试 URL/账号/秘密混入；测试二进制即待交付二进制 | E/ART-05/ | NOT_RUN；ENV-01、ENV-03 |
| INI-01 / RG-02 | P1/P2；新库；正常 EPUB+MP3 | Web 打开首次设置、创建管理员→登录→新增根目录→继续导入→列表/详情→三端阅读/播放 | 无默认管理员、手改 DB；初始化至可读闭环顺畅 | E/INI-01/ | NOT_RUN（原生子项 BLOCKED）；ENV-02、ENV-03、ENV-06 |
| INI-02 / RG-02 | P0；无权/不存在路径、重复请求 | 设置重复提交；普通账号访问设置；新增坏路径，修正后重新提交/导入 | 重复初始化和越权正确失败；路径反馈明确，修正可恢复 | E/INI-02/ | NOT_RUN；ENV-03 |
| INI-03 / RG-02 | P1；INI-01已完成 | 记录账号/书库/任务/已确认位置，受控重启当前版本服务，再登录与重开 | 新数据持久化，无再次初始化或已确认数据丢失 | E/INI-03/ | NOT_RUN；ENV-03 |
| IMP-01 / RG-02 | P2；FLAT、VOLUMES 各独立根 | 按 UI 分别建库、扫描根文件与含子目录书籍；对照预期清单记录目录和独立资源身份 | 两正式模式 Book/Node/Resource/Asset/页轨计数与层级正确 | E/organization-live/imp01-ui-1788695317426/；database-readback-complete.json | 正常两模式UI+同库持久化/拓扑子项PASS；命令超期/HTTPbody未存见证据，不计最终RC |
| IMP-02 / RG-02 | P2；中英名、空格、特殊字符、多层、图片/音频目录 | 导入后进入每层，切换排序/分页，打开图片目录与多轨音频 | 不乱码、不漏资源、不用资源数决定页面类型；正常播放/阅读 | E/IMP-02/ | NOT_RUN；ENV-06 |
| IMP-03 / RG-02 | P2；合法+损坏/DRM/无权文件混合 | 隔离根扫描；使外部元数据不可达；核对任务错误与同级合法资源 | 错误隔离可解释，基础入库/已可读内容不被拖死；源文件不变 | E/IMP-03/ | NOT_RUN；ENV-06 |
| IMP-04 / RG-02 | P2；IMP-01源保持不变 | 记录文件hash/拓扑/进度→再次手动扫描→对账 | 不重复不丢失，未变文件进度保留 | E/IMP-04/ | NOT_RUN；ENV-06 |
| IMP-05 / RG-02 | P2；仍有真实待处理任务 | 扫描活跃时受控服务重启→查看队列→继续导入/安全重扫 | 任务可恢复、有进展、不永久卡住；不要求新暂停接口 | E/IMP-05/ | NOT_RUN；ENV-03、ENV-06 |
| IMP-06 / RG-02 | P2；专用可写/只读根，测试文件 | Web 上传→文件详情；使用已有增删改入口；坏文件修正后资源重扫/继续导入；分别观察自动扫描和手动扫描对缺失项处理 | 仅授权显式写操作变动测试源；自动保留缺失、手动成功完成后按既有语义清理拓扑；失败可重试 | E/IMP-06/ | NOT_RUN；ENV-03、ENV-06 |
| CON-01 / RG-02 | P1；W/A/I × HTTP/HTTPS/自定义端口 | 逐地址添加服务器/登录，浏览与读听；HTTPS经受信任代理；非信任证书走现有显式流程；公开链接检查 | 合法配置可连接；无默认关闭TLS；冷/热启动均不依赖localhost | E/CON-01/ | NOT_RUN（原生 BLOCKED）；ENV-02、ENV-03 |
| CON-02 / RG-02 | P1；管理员、普通账号、两个服务器 | 错密码→修正；服务端使会话失效后重登；切账号/服务器再取无权资源 | 错误反馈正确、权限重验，数据与会话不串用 | E/CON-02/ | NOT_RUN（原生 BLOCKED）；ENV-02、ENV-03 |
| OPDS-01 / RG-02 | P2；客户端名称版本由负责人自测记录 | 原认证及错误凭据场景交由负责人执行 | 认证及访问控制要求保持 | DEC-08；本次用户决定 | PASS（负责人放行，用户自行测试）；无代理双客户端实测证据 |
| OPDS-02 / RG-02 | P2；两个客户端各支持的合法格式 | 原浏览、分页、搜索、封面、下载及打开场景交由负责人执行 | 原文件可读要求保持 | DEC-08；本次用户决定 | PASS（负责人放行，用户自行测试）；无代理双客户端实测证据 |
| OPDS-03 / RG-02 | P2；代理HTTP/HTTPS/端口；两账号 | 实际客户端链接、下载与Range场景交由负责人；既有协议/权限/hash自动回归保留 | 原URL、权限、文件一致及Range要求保持 | DEC-08；协议证据单独按实际运行登记 | 客户端部分PASS（负责人放行，用户自行测试）；协议最终RC回归仍必需 |
| OPDS-04 / RG-02+04 | DEC-05 关闭验证；全新测试库 | 检查目录、搜索和详情无同步链接；授权 GET/PUT 为410、未授权401；不写旧/v5进度表或其他DML | 原同步互通 N/A；关闭入口且保留目录权限及下载 | R1-OPDS-CLOSURE | 开发回归 PASS；最终 RC 重验 |

## 3. 格式与样本计划

每个源格式拆 `N` 正常、`C` 复杂、`X` 异常样本；每个 W/A/I 子项分别执行以下步骤，保存 `E/<组ID>/<W或A或I>/<N或C或X>/`。完整N/C/X样本组尚缺；已有候选与R0实测hash见§3.1。因此下表组汇总均 BLOCKED（ENV-06，原生另 ENV-02/03）；不是格式不支持。

- **R**：清空仅该测试样本的合法缓存前提由隔离测试环境准备→首次读完整原文件（检查真实下载进度和校验后才打开）→连续翻页/滚动→目录与跨章→字号/字体/主题/方向→正文中段锚点→返回/重开→前后台；冷/热缓存、取消、缺文件重建与已有下载路径分别执行，原文件 hash 不变，无派生出版物/在线章节兜底。
- **F**：首页/中页/末页→页码/目录跳转→缩放/长图/方向/快速连续翻页→返回/重开；检查现有有界 Range/按页读取与错误恢复。
- **X**：在同一隔离根打开异常样本，记录稳定 ruleId/错误类别、可读输出或安全失败、合法同级内容可用、无危险外部请求/源文件修改/崩溃。可恢复 authored active content 应 SANITIZE 后可读，不能把所有异常都预期整书拒绝；不可隔离风险/损坏/超限分别按契约归类。

| 组 ID（RG-03） | 源格式 / N与C真实样本要求（ID槽） | 平台/前置 | 步骤与预期 | X样本 | 状态/关联 |
|---|---|---|---|---|---|
| REF-EPUB | EPUB-N：真实章节；EPUB-C：嵌套目录、图文、非平凡布局 | W/A/I；P2 | R，正文/目录/锚点均正确 | EPUB-X：损坏包、active markup可恢复、具体外部实体风险 | BLOCKED；ENV-06 |
| REF-MOBI | MOBI-N/C：实际MOBI7与复杂PalmDB/图片目录 | W/A/I；P2 | R，libmobi原格式内存出版物可读 | MOBI-X：截断/DRM | BLOCKED；ENV-06 |
| REF-AZW | AZW-N/C：独立实际AZW来源与内部变体证明；不只MOBI改名 | W/A/I；P2 | R，实际变体按承诺可读 | AZW-X：DRM/损坏 | BLOCKED；ENV-06、RISK-02 |
| REF-AZW3 | AZW3-N/C：实际KF8、复杂章节图文 | W/A/I；P2 | R，目录/跨章/锚点正确 | AZW3-X：损坏/DRM | BLOCKED；ENV-06 |
| REF-PRC | PRC-N/C：实际PRC/PalmDB与复杂资源来源证明 | W/A/I；P2 | R，不能由改扩展名证明全部变体 | PRC-X：截断/DRM | BLOCKED；ENV-06、RISK-02 |
| REF-FB2 | FB2-N/C：多section、嵌套目录与内嵌图片 | W/A/I；P2 | R，文本/图像/章节正确 | FB2-X：坏XML、可恢复active/具体实体风险 | BLOCKED；ENV-06 |
| REF-TXT | TXT-N/C：中文UTF-8、BOM UTF-16LE/BE、GB18030、混合换行、长章 | W/A/I；P2 | R；逐实际编码登记，不能一份英文UTF8代替 | TXT-X：损坏/超预算，失败类别正确 | BLOCKED；ENV-06 |
| PDF | PDF-N/C：文本目录+复杂大页/扫描图像PDF | W/A/I；P2 | F；真实物理页与内容可读，有界传输 | PDF-X：截断、密码/超预算 | BLOCKED；ENV-06 |
| COM-CBZ | CBZ-N/C：真实ZIP漫画、嵌套路径/自然排序/长图 | W/A/I；P2 | F；图片顺序与页数正确 | CBZ-X：加密/损坏/超预算 | BLOCKED；ENV-06 |
| COM-ZIP | ZIP-N/C：独立ZIP源及含非图片条目 | W/A/I；P2 | F；正确筛图，顺序不漏重复 | ZIP-X：遍历/损坏/解压预算 | BLOCKED；ENV-06 |
| COM-CBR | CBR-N/C：实际RAR容器与承诺变体 | W/A/I；P2 | F；不能用ZIP改名 | CBR-X：加密/损坏 | BLOCKED；ENV-06 |
| COM-RAR | RAR-N/C：真实RAR4/RAR5分别登记适配能力 | W/A/I；P2 | F；变体失败记风险不删支持 | RAR-X：损坏/扩展预算 | BLOCKED；ENV-06 |
| COM-DIR | DIR-N/C：实际图片目录，多层/自然排序/非图片/已有图片类型 | W/A/I；P2 | F；图片文件数与Resource/Book数分开 | DIR-X：损坏图、单页失败隔离 | BLOCKED；ENV-06 |

安全样本优先复用 packages/reader-contracts/fixtures 及现有平台 corpus；这些是测试素材来源，不证明全部真实阅读样本已准备。已有候选SHA-256见§3.1，余下样本及章节/页/轨事实清单待补。引擎与源文件路由见 release-gate.md §6，异常阈值只引用机器策略，不另造规则。

### 3.1 已存在候选实样（R0只读散列，不是读取验收）

下表路径均相对 `test-data/library/`；SHA-256和字节数为本轮实际读取结果。EPUB/TXT/PDF/漫画与图片目录仅作为N或扩展名路由候选，不作为C证据；MOBI复杂AZW3与FB2复杂结构以同目录CORPUS说明为依据，尚未做本轮解析。`12-basic.prc`/`13-basic.azw`是MOBI同源扩展名变体，只能覆盖路由；完整独立AZW/PRC变体仍缺。四份漫画归档成对同hash（ZIP/CBZ与RAR/CBR），仅覆盖对应容器/扩展名路由；当前RAR为RAR5 stored，RAR4、压缩RAR和独立复杂归档均缺，仍BLOCKED。现有TXT仅281字节、PDF仅464字节，不能代替正常长篇阅读/复杂排版证据；复杂漫画的非图片条目、嵌套/自然排序和已有JPG/GIF/WebP类型样本亦待补。图片目录是 `comics/starship-pages/`（两个PNG与一个应过滤TXT），目录不伪造单文件hash。

拥有实样的Web正常子项为NOT_RUN；缺复杂/异常样本的子项以及未交接真机的子项为BLOCKED，组汇总BLOCKED不能理解为所有样本不存在。音频实样在当前 `test-data` 盘点未找到，外部合法样本是否已有须交接；大型数据集未交接。下表不证明完整corpus，也不复用历史PASS。

| 真实候选路径 | 字节数 | R0 SHA-256 |
|---|---|---|
| `epub/reader-v2.epub` | 2497 | `a643ee39426f926dbd7ca62ffcd2ec008d276cd1ac09d6af45f33548bbaa2531` |
| `mobi/01-basic-mobi6.mobi` | 10196 | `43ddc428751b26d116c2a39e12e94802fdf4a2f915bf8c965b26964e0d7b95cd` |
| `mobi/07-complex-toc.azw3` | 12101 | `02b560104675e8f2b10a3379b47f139502780200fcc350701804e457a259c15a` |
| `mobi/10-long-chapter.azw3` | 662694 | `71ad474636bbb5e39cbf1e283019aa86b2eab0b868e94172fbad4fddb2b94a77` |
| `mobi/11-upstream-huff-cdic.mobi` | 484776 | `560dda58429878a64f73381ffddfcf1a59809e7c669a5222666257df8976a68f` |
| `mobi/12-basic.prc` | 10196 | `43ddc428751b26d116c2a39e12e94802fdf4a2f915bf8c965b26964e0d7b95cd` |
| `mobi/13-basic.azw` | 10196 | `43ddc428751b26d116c2a39e12e94802fdf4a2f915bf8c965b26964e0d7b95cd` |
| `mobi/negative-upstream-drm-v1.mobi` | 86580 | `631e7afe719c04a91744c22f3021a2af1cafef541f93612a27d629ab74645494` |
| `fb2/source_test_book_fb2.fb2` | 6222 | `309f2293575c8165291e89165ed77a57095cd20727a57eb1ba227364ae79a693` |
| `fb2/reader-contract.fb2` | 1073 | `e3dd86210fb2da80aaa5393a32a5e9959a9ef2ca49e6fbcecc713c3ffc66165d` |
| `novels/starship-library.txt` | 281 | `e0c4c98d93dfb47a609c09dbe39328cf8bcb09163346d86c4fe9ec185800d14b` |
| `pdf/reading-notes.pdf` | 464 | `54ea7e1c0b7864675f5fbf9a9b9b381e99b5b8b4a21e2f26e4eef4859113616a` |
| `comics/reader-pages.cbz` | 360 | `3f17121d8056bf8c665cb563f01e8e25167f22d9c9b5858071c8247a813d5602` |
| `comics/reader-pages.zip` | 360 | `3f17121d8056bf8c665cb563f01e8e25167f22d9c9b5858071c8247a813d5602` |
| `comics/reader-pages.cbr` | 226 | `c57fc06438c75a07ada13d77480c95e452f0a157453642b1b0e937f59c7aea24` |
| `comics/reader-pages.rar` | 226 | `c57fc06438c75a07ada13d77480c95e452f0a157453642b1b0e937f59c7aea24` |
| `comics/starship-pages/page-001.png` | 69 | `427461f2fcbf52582b54a99e6ba0f08dd2bd9fa11f594ee0858db4b0bb46a36d` |
| `comics/starship-pages/page-002.png` | 69 | `427461f2fcbf52582b54a99e6ba0f08dd2bd9fa11f594ee0858db4b0bb46a36d` |

## 4. 音频矩阵

统一前置 P2；每行按 **W（浏览器/OS）、A（设备/OS）、I（设备/OS）× 单文件 AUDIO / 多轨 AUDIOBOOK_DIR × N/C/X** 展开。源扩展名、ffprobe等实际探测的容器/编码/采样率/声道/时长均入证据；同一扩展名不同编码不得合并。下表为待采集的组合，不是假探测结果。

**A步骤**：从详情播放→暂停→seek到中段→切轨/章节→连续30分钟→倍速/已有睡眠定时→退回/重开恢复；移动端加锁屏/后台/来电等系统音频中断，冷启动不得自动出声。正常与复杂（VBR、章节、长时、多轨交界）分别执行。IMPORT_ONLY 验证导入/元数据/提示且无无限缓冲；REJECT_EXPECTED 仅用于已证实损坏、DRM或契约拒绝输入，不把缺解码器与缺样本混为安全拒绝。

每行计划证据 `E/<AUD-ID>/<平台>/<容器-编码>/<结构>/<N-C-X>/`；实际运行目录见release-evidence。已存在语料与已测组合不再一概BLOCKED：Chrome MP3/AAC/WAV/FLAC短时链路有PASS；Android MP3/WAV短时PASS，AAC恢复及FLAC确认FAIL；其余已具备样本/设备的必测子项NOT_RUN，缺实样或原生iOS条件的子项BLOCKED。上述均不代表整行多轨/长时/异常组合通过。平台能力尚未获明确已有承诺的组合在执行前冻结，不能先失败后决定预期。

| ID | 源文件扩展名（各自独立样本） | 待验证的容器 + 编码组合 | 预期分类与平台边界 |
|---|---|---|---|
| AUD-01 | m4b / m4a / m4r | MPEG-4 + AAC；MPEG-4 + ALAC另行 | 拟用于三端核心播放验收，最终PLAYBACK_REQUIRED平台/版本待DEC-02按既有承诺冻结；ALAC按已承诺平台冻结，不以扩展名推断 |
| AUD-02 | mp3 | MPEG audio + MP3 CBR/VBR | 拟三端核心播放样本；具体平台/版本的PLAYBACK_REQUIRED范围待DEC-02冻结 |
| AUD-03 | mp2 | MPEG audio + MPEG layer II | 常用源保留；W/A/I具体解码承诺待冻结，不能直接 IMPORT_ONLY |
| AUD-04 | aac | ADTS + AAC（LC/已有HE变体分别记录） | 常用源；按浏览器/原生实有承诺冻结 PLAYBACK_REQUIRED |
| AUD-05 | flac | FLAC + FLAC | 常用源；W/A/I能力和OS版本待冻结 |
| AUD-06 | wav / wave | RIFF/WAVE + PCM；其他内部编码分行 | PCM拟用于三端核心播放验收，PLAYBACK_REQUIRED范围待DEC-02冻结；其他编码单独冻结 |
| AUD-07 | rf64 / w64 | RF64 / Wave64 + PCM | 各独立容器，常用源；平台组合待冻结 |
| AUD-08 | ogg / oga / opus | Ogg + Vorbis；Ogg + Opus | 两编码×各源独立登记；W/A/I按既有能力冻结 |
| AUD-09 | weba | WebM + Opus / Vorbis | 常用源；各浏览器/原生单列，能力待冻结 |
| AUD-10 | ac3 / eac3 | raw AC-3 / E-AC-3 | 兼容导入基线 IMPORT_ONLY；已有平台明确可播时该平台 PLAYBACK_REQUIRED |
| AUD-11 | aif / aifc / aiff | AIFF / AIFF-C + PCM/实际压缩编码 | 兼容导入基线 IMPORT_ONLY；不得覆盖已有平台可播承诺 |
| AUD-12 | amr | AMR + AMR-NB/WB | 兼容导入基线 IMPORT_ONLY；有承诺平台 PLAYBACK_REQUIRED |
| AUD-13 | ape | Monkey's Audio + APE | IMPORT_ONLY基线；真实样本缺失，生成器无编码器不是拒绝 |
| AUD-14 | caf | CAF + PCM/ALAC/实际编码 | IMPORT_ONLY基线；已有原生可播能力须冻结后验证 |
| AUD-15 | dts / dff / dsf | raw DTS；DSDIFF/DSF + DSD | IMPORT_ONLY基线；分别实样探测，不能只测dts代表DSD |
| AUD-16 | mka | Matroska audio + 实际FLAC/AAC/Opus等 | IMPORT_ONLY基线；逐编码/平台保留已有可播范围 |
| AUD-17 | wma / wv | ASF + WMA；WavPack + WavPack | IMPORT_ONLY基线；两源独立验收 |
| AUD-18 | 其余当前注册源 | adx、aptx、aptxhd、au、g722、g726、gsm、lbc、mlp、mpc、oma、qcp、ra、shn、snd、sph、spx、tak、thd、tta、voc、xma 的实际容器/编码分别探测 | IMPORT_ONLY基线，已有可播承诺优先；每个扩展名一组，不能漏掉枚举外接收源；无样本 BLOCKED |
| AUD-X | 每个已登记容器的异常输入 | DRM/通用视频容器/截断/损坏元数据/超契约预算；可隔离元数据风险另测 | 按已有契约 REJECT_EXPECTED 或可恢复处理；媒体不支持与安全拒绝分开 |

上述 PLAYBACK_REQUIRED“目标”不代表源码已经逐平台证明解码兼容；DEC-02 冻结时必须对照公开既有承诺，不可下调其范围。M4B/M4A/MP3旧存储枚举即使归一为AUDIO，原源格式仍逐行测试。

## 5. 进度同步与竞态

前置 P3；每个 REF-*/PDF/COM-*/可播 AUD-* 逐格式保存/重开并跑六方向：**W→A、A→W、W→I、I→W、A→I、I→A**。分别生成 `SYNC/<方向>/<源格式>/<样本>` 记录，步骤为来源端到唯一内容锚点→等明确确认→目标端新进入同资源→核对真实位置→主动回读再反向记录。预期：可重排同语义文字锚点（不比统一页码）；PDF物理页；漫画图片/页；音频轨ID+时间（误差按门禁建议冻结）。证据 `E/SYNC/<方向>/...`。W→A、A→W的现有样本方向为NOT_RUN，可用设备与新库已授权；涉及iOS的四方向仍BLOCKED（ENV-02），缺特定样本仅阻塞相应组合。不能用同端重开或一条三端循环覆盖六方向。

以下异常组每类实际引擎至少一套，不能用单个EPUB或只比百分比替代；执行前先列样本与引擎对应关系。

POS-02新增AUDIO-07：反复短缓冲导致周期捕获一直延后，真实Android运行时的受控端口场景已FAIL；独立候选 `0159f691` 原例与整类回归PASS，实际设备持久化仍待验证。该结果只覆盖capture owner，不替代AUDIO-06的FLAC确认期限现场或本节真实跨端/异常组合。

POS-08新增AUDIO-08（原RISK-06）：真实Android引擎+SQLite单次IO门控已复现A暂停2507ms写入B、A仍0，原候选不放行。`9df3d412` prepared/active绑定修复已有完整host/lint PASS，`567909e4` 另使stop取消local preparation；两者仍待真实竞态及必要相邻GREEN，不计为完成POS-08全部账号/服务器/资源组合。

| ID / RG-04 | 前置/平台/样本 | 操作步骤 | 预期 | 证据 | 状态/关联 |
|---|---|---|---|---|---|
| POS-01 | P3；W/A/I、全部承诺格式 | 各格式记录唯一文字/物理页/图片/轨时间→保存→退出重开；目标端换字体屏幕 | 精确语义恢复；展示百分比不反推Locator | E/POS-01/ | NOT_RUN（原生/缺样本子项BLOCKED）；ENV-02/03/06 |
| POS-02 | P3；各引擎代表样本 | 连续读听，量测捕获/本地持久化/发送/确认；不足5秒即返回/暂停/切后台 | 最后捕获位置按冻结间隔可靠保存，确认延迟单列 | E/POS-02/ | NOT_RUN（原生/缺样本子项BLOCKED）；DEC-04 |
| POS-03 | P3；各引擎 | 分别在本地持久化前、后、网络确认后强杀；App重启/系统回收/浏览器刷新 | 至少最后已持久化位置恢复；已确认零丢失，未持久化损失不超冻结间隔 | artifacts/releases/1.0/7e207c38/process-recovery/ | Chrome桌面/移动视口MP3已确认暂停后强杀并重登录恢复PASS（0/205.804ms）；未确认/其他引擎及Android子项NOT_RUN；iOS BLOCKED |
| POS-04 | P3；已合法打开/可本地读取资源 | 断网读到B→观察pending→重启客户端→重连→重试并另端重开 | pending持久保留并最终确认；不扩展离线登录契约 | artifacts/releases/1.0/02d6ea2d/epub-offline-and-adjacent/ 与 epub-offline-mobile/ | Chrome桌面/移动视口EPUB页面重建及重连子项PASS（965/959ms）；进程强杀、其他格式及另端交接NOT_RUN；原生iOS BLOCKED |
| POS-05 | P3；同账号同资源两端 | 写mutation M让服务提交但丢回包→另一端新写N→重试M；另测同M不同payload | 重放M不再覆盖N，不递增revision；不同payload受既有冲突处理 | E/POS-05/ | NOT_RUN（原生/缺样本子项BLOCKED）；ENV-03 |
| POS-06 | P3；各端读/听writer | 阻留旧M响应→本端生成新pending N→释放M响应→重开/重试N | 旧ACK仅清对应M，N保留；不能回滚本地较新位置 | E/POS-06/ | NOT_RUN（原生/缺样本子项BLOCKED）；ENV-03 |
| POS-07 | P3；双端并发、离线首次提交 | A/B分别写并控制事务完成顺序；再让离线未提交C在N后首次到达；主动回读 | 按服务端最后事务提交生效；C可成为新当前位置，区别成功mutation重放；明确记录用户可见回退，不自创最大百分比算法 | E/POS-07/ | NOT_RUN（原生/缺样本子项BLOCKED）；DEC-03 |
| POS-08 | P3；两账号/服务器/资源 | 在途保存时切账号/服务器/资源，释放旧请求；尝试无权资源和同mutation跨namespace | 无串写、越权、错误清pending；业务身份以资源为准 | E/POS-08/ | NOT_RUN（原生/缺样本子项BLOCKED）；ENV-03 |
| POS-09 | P3；有章/页入口的各格式 | 从目录显式目标A进入→读到B保存→旋转/重建/重进 | 显式入口只应用一次，回到后来B | E/POS-09/ | NOT_RUN（原生/缺样本子项BLOCKED）；ENV-06 |
| POS-10 | P3；各引擎 | 确认位置→服务受控重启→重开；另保持目标端正在阅读，远端写入 | 已确认位置保留；活动会话不被强行跳转 | E/POS-10/ | NOT_RUN（原生/缺样本子项BLOCKED）；ENV-03 |
| POS-11 | P3；各格式 | 标记已读/取消已读→主动回读→检查首页/详情/目录/Reader | 已读状态独立；不制造恢复位置；展示与实际语义一致 | E/POS-11/ | NOT_RUN（原生/缺样本子项BLOCKED）；ENV-06 |

以上NOT_RUN异常组若执行到缺设备/样本的具体子项则为BLOCKED；Android 9e896bbc已有授权，可用子项直接执行，不再等待旧ENV-03交接。原生iOS缺口仍单列。辅助自动测试 C-09 单独记录，不替代真机和竞态网络证据。

## 6. 大库扫描并发

DEC-06当前执行覆盖：本轮仅要求已完成的安静本机1万导入/重扫预检，PASS证据为 `local-load/measurement-20260906-065525/`。下方原完整压力步骤保留给既有脚本按需运行，均不再阻塞本轮，也不视为已实测。原阈值已由负责人接受；不再等待重新冻结。100k样本完成、300k部分准备已停止，无活动压力/生成任务。

P4的扩展验证冻结表必须填写：CPU/架构、RAM、磁盘/文件系统/挂载、数据库位置、OS、容器CPU/内存预算、系统余量、网络带宽/延迟；扫描并发/元数据策略；三端版本和至少三活动会话；总字节/大小分布/媒体比例/目录深度/坏文件比例；冷/热基线；采样方法/窗口/样本量/阈值/批准人时间。N100/8GB只是建议目标，无设备事实。所有阈值已按DEC-04接受，仍**不是实测值**；当前本机实际参数见已完成的10k证据。下表仅为DEC-06保留的可选扩展脚本目标，旧BLOCKED表示执行其完整范围时的条件缺口，不再阻塞本轮。

| ID / RG-05 | 前置/真实样本 | 具体人工步骤（自动负载/采集脚本待补） | 预期 | 证据 | 状态/关联 |
|---|---|---|---|---|---|
| LOAD-00 | P4；每类代表样本、目标机 | 冻结上表，扫描前对各端点/媒体取冷热空闲基线；确认隔离根容量和采集可用 | 配置可复现、阈值预先批准；缺机器不可以高配结果外推 | E/LOAD-00/ | BLOCKED；ENV-06、DEC-04 |
| LOAD-10K | P4；1万有效书籍/可读资源 | 从源文件真实扫描；扫描解析入库忙碌≥30分钟时W/A/I并发浏览搜索、阅读、播放、保存；轮换平台媒体 | 全部前台目标达标，扫描可慢但可持续；不是队列空转 | E/LOAD-10K/ | BLOCKED；ENV-02/03/06 |
| LOAD-100K | P4；10万有效书籍/资源 | 同上≥30分钟；保留已有可读库和增长库，抽查新入库何时可读 | 同上；计数/媒体比例无偷换 | E/LOAD-100K/ | BLOCKED；ENV-02/03/06 |
| LOAD-300K | P4；30万有效书籍/资源 | 同上扫描持续活跃≥2小时，三端会话持续并轮换；读写/退出重进/重连 | 不OOM/崩溃/拖死前台/丢确认进度；留全周期证据 | E/LOAD-300K/ | BLOCKED；ENV-02/03/06 |
| LOAD-FULL | P4；同30万源 | 全量扫描至少完成一轮；按源清单核对文件、目录Node、Book、ReadableResource、Asset、总字节、页轨 | 数量语义正确，不用30万图片/目录替代书籍；无静默漏有效资源；无固定扫描完成时限 | E/LOAD-FULL/ | BLOCKED；ENV-06 |
| LOAD-RESCAN | P4；源hash保持不变 | 全量完成后相同源再次扫描，比较上述计数/结构/抽样原文与确认进度 | 不重复、不丢数据、原文件未改 | E/LOAD-RESCAN/ | BLOCKED；ENV-06 |
| LOAD-RECOVER | P4；同压力环境 | 扫描活跃时一次受控服务重启→恢复/安全重扫；三端重连浏览读听/保存 | 恢复有进展；已确认进度保留，不损坏库/源 | E/LOAD-RECOVER/ | BLOCKED；ENV-03、ENV-06 |
| LOAD-EVIDENCE | P4；同数据集/配置 | 分端点保存原始延迟/错误/超时；分媒体录屏与音频中断记录；建议5秒采集CPU/RSS/总工作集/cache/swap/I/O/队列/DB锁等待；输出p95、成功率 | 列表详情/搜索/确认分别p95；正常打开/翻页与大文件分段；音频连续；OOM/锁/内存无失控；至少建议每核心端点1000样本，不足不声称高成功率 | E/LOAD-EVIDENCE/ | BLOCKED；ENV-06、DEC-04 |

禁止预填DB/空文件/错误格式跳过代替扫描；不得在真实库生成或删除样本。现有小样本脚本不能充作30万负载入口。监测只需足够原始数据，不新增生产监控平台或日志策略。

## 7. 已存在命令入口（计划，未执行）

命令须在已准备且授权的隔离环境运行；缺工具记录BLOCKED，本轮不安装。下列目录是工作目录，命令分别执行，不提供发布/推送命令。C-06..09 的补充信息随源码核对登记在 release-gate.md §6。

| 编号 | 工作目录 | 已存在命令/入口与边界 |
|---|---|---|
| C-01 | apps/api-python | `uv run --extra dev --locked pytest -q`（发布完整回归）；另按AGENTS现有要求执行 `uv run --extra dev --locked ruff format --check .`、`uv run --extra dev --locked ruff check .`、`uv run --extra dev --locked mypy app`、`uv run --extra dev --locked pytest --cov=app --cov-report=term-missing`，实际执行命令应同一locked环境，不能因PATH缺失省略 |
| C-02 | apps/web | `pnpm lint`、`pnpm typecheck`、`pnpm test`、`pnpm i18n:check`、`pnpm test:e2e`；R1 仅 Chrome 桌面/移动视口 |
| C-03 | packages/reader-contracts | `python3 generate-reader-safety-policy.py --check`；`python3 check-reader-safety-boundaries.py`；`python3 -m unittest discover -s tests -p 'test_*.py'` |
| C-04 | apps/mobile | 当前 .github/workflows/mobile.yml 的 `./gradlew :shared:testAndroidHostTest :androidApp:testDebugUnitTest :androidApp:lintDebug :androidApp:assembleDebug`；完整回归使用GitHub Actions workflow_dispatch输入 `run_full_android_regression=true`；CI模拟器仅补充，不替代正式APK物理设备 |
| C-05 | 仓库根 | `pnpm smoke:python-worker-import`：现有临时新库小样本Worker测试，仅辅助；`python3 apps/mobile/iosApp/verify_readium.py`：SDK静态检查，不是IPA或真机通过 |
| C-06 | 干净冻结 RC 仓库根 | `bash scripts/publish-docker-hub.sh --output-dir artifacts/releases/1.0/<rc>/oci --platform linux/amd64,linux/arm64`；复用生产 Dockerfile runner，将 `git archive` 的纯提交内容交给 Buildx，导出 OCI 与 SHA-256 JSON，使用 `ermao-local/...:<rc>`；不推送。需要可用 Docker/Buildx，当前 ENV-08 阻塞真实构建；不得省略 `--output-dir`（原默认模式会公开推送）。按架构独立导出时使用不同目录；后续隔离安装/运行验收待实际产物 |
| C-07 | apps/mobile | 已存在gradlew/gradlew.bat及Android application模块；未找到正式Release/签名入口，正式构建命令与签名注入方式待补（ENV-07），不把默认任务推断成可交付入口。安装前 `adb devices -l` 精确核实物理设备；签名与正式Release测试安装步骤待环境交接 |
| C-08 | apps/mobile/iosApp | 已发现Xcode项目/shared scheme的Release ArchiveAction，可按Xcode Product→Archive→Organizer操作；未找到仓库archive/export脚本或ExportOptions，实际导出步骤待签名/安装方案冻结（ENV-07）；不得把device debug build当IPA |
| C-09 | apps/api-python | OPDS与v5现有测试文件见门禁§6；`uv run --extra dev --locked pytest -q tests/contract/api/test_opds_http.py tests/contract/api/test_reader_v5_progress.py tests/contract/api/test_reader_v5_contract.py`；其他已核实路径见§6；协议/真实客户端/故障注入入口另行登记，不能编造脚本 |

## 8. 用户目标映射与执行记录

| 已确认目标 | 门禁与至少一组执行用例 |
|---|---|
| 后端/Web/API/Worker+正式APK+有效安装IPA同版本 | RG-01 / ART-01..05 |
| 全新安装/仅新数据且不清真实旧数据 | RG-02 / INI-01..03、P0；RG-05 / P4 |
| 初始化/书库配置/导入、第一方与真实第三方使用 | RG-02 / INI/IMP/CON/OPDS全部 |
| 全部承诺格式按平台正常读听且不降级 | RG-03 / REF/PDF/COM/AUD与N/C/X展开；DEC-02 |
| 保存重开跨端、异常断网重启不丢确认位置 | RG-04 / 六方向SYNC及POS-01..11、OPDS-04 |
| 大库可慢但不崩溃或拖死前台 | RG-05 / LOAD全组，联动RG-04确认位置 |

单条实测记录使用 release-evidence.md 的必填字段；失败绑定台账ID，样本/命令/预期变动必须先留痕再重跑。所有来源尚未运行的用例保持NOT_RUN或因明确前提缺失BLOCKED；当前无PASS/N/A记录。
