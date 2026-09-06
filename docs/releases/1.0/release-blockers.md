# 1.0 发布阻塞项

R1 日期：2026-09-06。正在自主执行代码回归和确认缺陷；下方 R0 事实保留为历史线索，当前状态以下表覆盖。环境/决策解除后用例回到 NOT_RUN，不能直接改 PASS。

## R1 状态覆盖与外部条件

当前阶段R2（既有R1编号保留）：READER-03原问题关闭；AUDIO-05原AAC回零经新包真实恢复9906ms→9906ms及MP3相邻回归关闭，已整合 `9938c350`，长时/复杂VBR不外推。IMP-01正常两模式UI+同测试库只读持久化/拓扑子项PASS，原900秒退出和未存HTTPbody仍保留。AUDIO-06 FLAC仍FAIL；AUDIO-07受控捕获修复因新增跨资源writer风险RISK-06暂不整合，独立候选 `9df3d412` 待实际竞态与持久化验证。AUDIO-04原生产链PASS但TEST-11完整1800秒采样末段仍待补齐；尚未冻结RC。

新增AUDIO-05（AAC-LC，RG-03/AUD-04+RG-04/POS-01）：真实5/10秒确认及9911ms暂停通过，重开容差FAIL，瞬时恢复值未知。新增AUDIO-06（FLAC24-bit，RG-03/AUD-05+RG-04/POS-02）：首5秒确认期限FAIL，瞬时状态未知。均为尚待分类的必测失败，不能仅用finally后DB推断根因；只补既有断言前最小观测，各一次复验后转具体业务修复或真实环境结论。WAV同入口9955ms恢复PASS独立保留。

以上首次失败状态保留为历史，以首段及最新证据覆盖。RISK-06 / RG-04 POS-08：configureProgress提前替换active writer，而旧资源仍可播放；新Buffering捕获与既有Pause/Tick可能进入该身份窗口。只读路径尚非串写复现，正在用现有Android运行时与真实SQLite门控取得原场景证据；新候选不只丢弃旧书暂停保存，而是保留旧绑定直到新launch提交。未通过实际验证前不关闭此风险或放行AUDIO-07。

ENV-11：用户已明确允许3107/3108回环测试服务。按相同命令重试仍在创建进程前被自动审批拒绝，理由仅“blocked by policy”；两端口无监听，RED/GREEN仍NOT_RUN。已请求用户手动启动已备妥的两份构建，不重复索要授权、不换入口绕过。拒绝及清理记录位于启动修复工作树的 `apps/web/.next/startup-progress/browser-red-green/explicit-authorization-*.json`。此项不阻塞其他验证。

AUDIO-05/06诊断已取得断言前现场且停止扩展：AAC确认9916ms/rev4，重开0ms/Paused；FLAC截止时Playing/4185ms，但SQLite仍0ms/rev1、无pending/terminal，未满足GET前置。不是finally数据库反推；两项仍FAIL。AAC现有Media3 1.8.1默认ADTS寻址禁用与归零链相符，待最小配置修复及真实回归；FLAC继续核对首次播放/捕获时序。既有测试仅补观测，主APK不变，设备和服务清理通过。

IMP-01双模式真实API拓扑通过，但实际venv与指定入口不同，保留环境限制；已使用现有fixture推进实际Chrome界面子项，未执行完成前不计PASS。

AUDIO-07 / RG-04 POS-02：真实Android运行时+受控引擎端口复现短暂缓冲使捕获饥饿；每播放2秒缓冲100ms，三轮后position7000、初始1000，却无任何新capture。证据 `D:/www/ermao-release-audio-capture/artifacts/audio-capture/red-junit.xml`。独立候选 `0159f691` 在Playing→Buffering时复用现有captureProgress保存最后位置，原例及整类7 PASS；完整host/lint、独立审查及真机持久化待验。此为已复现的捕获缺陷，不等同已确定FLAC首5秒失败根因，不降低期限或更改生成时序契约。

下方旧的“最新/当前”表述为历史过程，以本节恢复点和release-evidence最新记录覆盖。

当前修复进展：SYNC-02 `76a88845` 已通过原时序/相邻回归和独立审查，真实Chrome待验证。AUDIO-04已用实际Next代理背压复现默认超时截断，null参数对照完整传输但不符合Next配置schema；采用有限3600000ms候选，schema/lint通过，实际有限值运输及长播放待验证。未降低播放停顿2秒阈值；不能以运输探针取代原30分钟播放。

DEC-08当前覆盖：负责人明确将OPDS客户端项标为通过并自行测试。OPDS-01/02及OPDS-03客户端部分PASS（负责人放行，用户自行测试），ENV-04不再阻塞本轮；代理没有完成双客户端实测。下方旧的待提供环境/权限描述仅作历史，客户端安装与准备停止。协议安全及最终RC回归保持。

AUDIO-04新真实阻塞：生产Chrome长播放在约12分钟出现waiting/stalled，位置停止推进5300ms，原阈值2000ms；完整30分钟FAIL，后续PWA步骤未到达。采样连续、无pause/seek，原文件完整解码通过。Next默认30秒socket超时与后端Range流32640ms结束相容，当前只作具体运输对照，不静态关单。TEST-10已在此失败中正确留错、回收服务并恢复配置，该工具修复闭环结束。另RG-02已核验两官方客户端产物，但Thorium协议注册与KOReader所有文件权限超出隔离边界，待用户提供/授权合适环境，不绕过。

SYNC-02（RG-04/POS-01、POS-06，应用owner链已复现）：启动bootstrap先读取旧位置，随后新位置ACK原子清pending，启动再读pending为空并选择旧bootstrap位置。`audio-soak/ack-bootstrap-race/results.json` 中真实coordinator和现有owned fake ports/恢复owner复现4%→已确认25%→重开选择4%；完整Locator保留，百分比这里只作诊断摘要。尚非Chrome/真实IDB/媒体引擎复现。修复在独立工作树 `D:/www/ermao-release-startup-progress` 进行，避免影响当前production连续播放源码；复用同一启动owner在pending为空后读当前服务端，不变更最后事务语义。原AUDIO-03快速关闭已关闭，两个问题分开登记。

DEC-07覆盖工具收敛规则：AUDIO-03/ANDROID-03已关闭场景不再扩展工具；TEST-10已有保护回归及真实开发模式清理通过，当前production流程验证后即结束该工具修复，不以未来通用能力或重型取消演练另加阻塞。HTML具体未关闭问题只做决定修复所需最小观测；OPDS真实客户端、iOS/签名/容器条件缺失仍按对应项处理，不以无关工具开发替代。

ANDROID-03 / RUN-01当前默认仪器全量148 PASS/0 skip（334.740s），在原断言之外补充完全展开的可观察前置后，单项及整类亦通过。主APK及生产源码未变，只替换测试APK；依据与hash在 `preflight-mobile/android03-expanded-anchor-20260906/`。本轮自动失败已解除，保留历史147/1及未证实唯一原因的限制；不把一次重跑解释为“环境偶发”，也不覆盖最终RC/真实逐格式缺口。

AUDIO-03本批已关闭：`4aaa40c7`真实Chrome原链路1 PASS，保存475006ms→重开475000ms（6ms）；7原文件/910应用源码不变、API无5xx、服务退出及配置恢复均独立核实。原两次FAIL继续留证，不覆盖长时/多编码/异常存储/跨端。TEST-10工具40 PASS且真实开发模式清理通过；production运行与构建中取消实际验证仍待执行。

最新AUDIO-03补充候选完整Web465 PASS：关闭取消在途加载及其UI，旧IDB结果和旧保存失败不得覆盖后来的资源；非空pending摘要撤销有模型断言，真实浏览器回归仍未执行。READER-03独立扩展对照仍有MathML encoding实体上下文反例（三种分块均失败），不以95项相邻测试通过关闭；下一步由唯一XML实体owner配合SDK解析上下文验证。

AUDIO-03修复候选待真实回归：第二次观察已证实engine seeked/pause位于475秒，恢复仍差437秒；候选改为立即原子本地保存后关闭，并让新播放/同资源打开抢占旧close。完整Web465 PASS零skip，错误仍未关闭。PWA独立审查确认原断言全部保留、有限SW场景有效；另列TEST-10：启动原错被清理异常覆盖、启动/停止期限不协调、失败trace可能保留测试凭证、Next改写共享配置。测试基础设施修复中，不把这四点当作生产PWA缺陷。

AUDIO-03（待分类的真实用例FAIL）：`audio-soak/runs-30/r1788686654444-w0/` 长MP3新增短观测后，跳转/暂停/关闭重开位置误差438000ms（要求≤2000ms），最后PUT为37479ms。持续观察本身已通过；不能确定是产品异步跳转/保存问题还是测试入口问题，原失败保留并补实际引擎事件诊断，不放宽断言。正式30分钟尚未运行。

ANDROID-03聚焦复现：同包单项1 PASS、整类19 PASS、截图单项1 PASS，均零skip；原全套1 FAIL保留。当前SDK确认手势height已裁剪、断言会waitForIdle，不能以这两点误判原因。第一swipe仅检查top变小，尚不能证明稳定Expanded；下一步仅补测试逐步几何/原生语义诊断，保留滚动、回缩及不翻页原断言。

300k取消已完成：122342部分文件保留、无完整manifest；自有生成/监督进程均退出，见DEC-06取消终态，不再列为运行中或等待大规模结果。

DEC-06 已获用户明确决定：本轮导入性能以已有 1 万规模实测为依据，大规模/完整时长测试交由独立脚本按需执行。LOAD-01 已关闭的事实保持；100k/300k 压测、完整时长和三端混合压力不再阻塞本轮代码收敛，不伪填这些未执行场景 PASS。300k 样本准备已请求安全停止，必须以所属进程实际终态为准；100k 完成样本与300k部分输出保留，不删除。iOS 的其他功能与正式交付阻塞不受此决定影响。

ANDROID-03 / RUN-01 当前自动真机结论：`227e09f1` 移动生产源码完整148项运行 **147 PASS / 1 FAIL / 0 skipped**（346.265s），失败为 `ReaderScreenContentsInstrumentedTest.nativeSheetExpandsBeforeScrollingAndCollapsesAtListStartWithoutTurningPages:326`：第二次手势后仍存在第一章节点。`preflight-mobile/mobile-full-227e09f1-20260906/09-instrumentation-summary.json` 和原始stdout留证；当前尚未确定产品缺陷、手势/动画测试问题或用例间状态影响。授权同包单项/同class重现，不改超时/断言，不用重跑一次PASS关闭不稳定性。shared429/Android unit218/lint通过不覆盖此失败。

TEST-09：生产PWA测试中Node API客户端无法解析 `release-live.localhost`，浏览器能正常建库且SW注册通过；已将既有验证/注销请求统一到浏览器同源/no-store入口，不改系统DNS或产品网络边界。Chrome两个视口真实回归通过，原DNS失败保留且测试会话值脱敏；此测试环境缺口关闭。PWA实际安装/版本更新与离线位置异常恢复仍未完成，不以已有shell/断网导航通过代替。

ENV-06规模数据子项进展：100k真实紧凑文件已准备并逐文件校验，工具/数据缺失不再阻塞该规模的索引预检；完整测量尚未开始。300k准备进行中，不能计PASS；真实大文件/媒体混合负载、缺格式样本与客户端覆盖仍有缺口。复用既有工具，不增加支持格式或改阈值。

最新结果覆盖：ANDROID-02由 `227e09f1` 修复，真实 `AUDIO` 响应经唯一 `fromWireValue` 映射并保留精确类别/形态校验，20项host回归及第四次真机真实MP3闭环通过。SYNC-01在此链路确认5/10秒实际ACK落盘、暂停及重开后outbox收敛，本批两项缺陷关闭，跨端/长时范围仍未完成。新增TEST-08：第三次真实运行被Locator对象键序字符串比较误报；只修测试为完整JSON值比较，第四次PASS，原FAIL与诊断保留。NATIVE-01已在 `dc8381f7` 独立提交；READER-03仍有raw-text实体语义缺口，不能整体关闭。

最新覆盖：`d1fc48a9` 已修复 SYNC-01 的正常 ACK 重复解包，32 项 host 回归 PASS，实际在线闭环仍待完成。新增 ANDROID-02：两次全新库真机运行 bootstrap 200 后失败，第二次报 `READER_BOOTSTRAP_INVALID`，尚无媒体请求，证据 `android-live/android-1788681827033/` 与 `android-live/android-1788682483508/`；正在以真实 `audio/AUDIO` 响应复现共享格式映射，不能归因于解码器。NATIVE-01 新库真实 options 回归已通过，READER-03 仍因第二轮 HTML 独立审查的 noscript、正文 tail 与 raw-text 三项问题继续修复。`c5157d71` 仅完成负载工具 88 项验证，100k/300k 运行仍 NOT_RUN。

最新RUN-01增量：`7c6c991c`后端完整Linux1284 PASS+Windows平台2项补测PASS、coverage77%、Ruff689/mypy492通过；Android当前完整148/共享416/单元218/lint通过，旧失败数量仅保留历史。安静10k短时实测已完成；新MOBI/移动端位置修复后须更新受影响证据，整套门禁未放行。

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
| READER-02（原 RISK-05） | 新库真实HTTP已复现：FINISHED无进度时详情仍未完成；显式UNREAD后37%进度使管理列表误显READING；进一步复现bootstrap摘要同类遗漏 | `c04818f3`修复；219相邻回归与26项bootstrap/v5回归PASS，491mypy通过。保留3查询预算，Locator/百分比不变，详见最新证据；最终完整RC仍需回归 |
| AUDIO-01 | 真实Chrome快速播放/暂停后，迟到的play Promise拒绝覆盖当前正常暂停状态；`release-live/r1788672824257-w0/` | `c14b3033` 已修复并推送，3项顺序测试PASS；第二次真实运行经过该步骤，完整闭环仍待回归 |
| AUDIO-02 | KMP/Android注入5秒播放没有自动捕获，Web原间隔15秒；`preflight-mobile/rg04-audio-autosave-repro-20260906/` | `c6b3e802`修复；Web459 PASS、Chrome实际5/10秒读回断言通过；`d6b11360`真机生产SQLite落盘及重开误差8ms通过，完整148/共享416/Android218/lint PASS。在线确认/后台/长时/iOS仍未覆盖，不整体关闭RG-04 |
| MEDIA-01 | Windows真实Chrome请求缩略封面出现500；cache/covers临时文件替换报WinError32/5 | `8a4ed3fb`修复与5项独立回归PASS；最新实际失败位于另一default-cover owner，另列MEDIA-02 |
| MEDIA-02 | MP3两视口因默认封面500失败，`release-live/r1788675527007-w0/api.log:104` 指`services/default_cover.py`的原子替换，非缩略缓存 | `7c6c991c`修复并推送；两个入口复用唯一原子发布owner，7项回归PASS，`chrome-live-default-cover.log`严格两视口2 PASS且无API 5xx，此缺陷本批关闭；最终RC需重验 |
| LOAD-01 | 实际10k预检列表/命中搜索随progress增长变慢，随后pool耗尽及进度读回超时；原始目录见最新证据 | `c13a7034`/`68c02047`修复后，`c7f5d5eb`安静10k实测19685请求全部成功、p95均达标、进度零丢失及原文/身份校验PASS，`local-load/measurement-20260906-065525/`；本批已复现缺陷关闭。完整时长/大规模/三端并发仍未覆盖，RG-05不整体放行 |
| ENV-09 | 真实Chrome EPUB详情reading-units 503；测试Windows缺canonical native章核 | 同C源码已隔离编译DLL并加载，最新MP3两视口无该503；测试入口新增native预检，不将环境缺失改为产品格式拒绝 |
| ENV-10 | 59语料中MOBI/AZW/PRC/AZW3的目录返回PUBLICATION_UNSUPPORTED；本机探针未配置ERMAO_MOBI_CORE_LIBRARY | Windows runtime子项BLOCKED，正在检查现有DLL/构建入口；其导入/原文下载成功不能替代目录通过，不能据此判读物损坏 |
| SAMPLE-01 | 59语料中FB2为0 section，AIFC实际AIFF且与AIF/AIFF同hash；仓库另一个FB2的l:前缀未绑定 | `32175712`修复AIFC生成/验证，2测试+真实probe PASS；另保存仅补命名空间的18 section FB2派生样本及精确hash/差异，XML解析PASS。原文件/旧失败保留，新后端/客户端验收分开登记，不改支持范围 |
| TEST-07 | 真实Chrome重开音频时，脚本用即时count误判尚未加载按钮并等待不存在的资源卡；`web-baseline/chrome-live-audio-fix.log` | 已修改为等待可用入口，待重跑；保留完整音频恢复误差≤2秒断言 |
| READER-03 | Linux实际MOBI/AZW/PRC的公开publication子资源返回422；目录各16项、原文hash/Range通过。native读取完成后HTML的未绑定前缀触发ElementTree XML解析失败 | 原二进制上五份真实文件目录/首末正文/原文hash/Range回归通过，Linux publication109项通过。修复候选独立审查另发现SVG/style序列化可重建事件属性、xlink/xml属性namespace丢失，已阻止采纳；补SDK namespace/token适配后主37项与Chrome4项通过，仍待独立复核。该路径失败不等于生产Web原文件阅读失败；三扩展名共用一个hash |
| NATIVE-01 | 从冻结当前native源码新建.so成功，但Python传null options，当前C入口要求有限有效options，四份MOBI族在open阶段invalid_argument；ABI1加载检查本身通过 | 新构建与真实失败在`mobi-html-regression-20260906/`；正在按头文件ABI、默认options及生成容量预算修复Python绑定。不得回换旧.so冒充当前源码通过 |
| SYNC-01 | 共享Ktor位置PUT成功链疑似重复解包：ApiClient输出data，mapper仍要求ok/data，可能拒绝正常ACK | 正在用完整ApiClient/port链复现并修复；尚不以静态风险或服务端存在位置证明客户端已确认，后续须Android真实HTTP与持久化联验 |

RUN-01 最新拆分：`f3748d58` 后端 Linux 完整1250 PASS + 原有平台2 skip，Windows 两项补测均 PASS；Android host216 PASS、集成 lint PASS。`80c5d5b9` Android/C 同源码集成真机147项全部 PASS，证据见 R1-ANDROID-FULL，此批原自动回归失败已解除，最终 RC 全套仍待冻结重跑。ANDROID-01 截图已由主代理复核确认页码修正。真实音频短时引擎测试 PASS，长时/逐编码/实际服务端恢复仍待执行。

| ID | 当前事实与证据 | 当前处理 |
|---|---|---|
| ENV-01 | 起点 develop `197e81a8` 干净，已创建隔离发布分支；原工作区后续15项改动归属无法确认，全部保留并排除 | 最终 RC 冻结仍 NOT_RUN，不将原工作区后续改动视为已纳入验收 |
| ENV-02 | Windows 可用，未登记 Mac/Xcode/配对 iOS 设备 | iOS 编译/适配器/真机 BLOCKED；继续其他平台 |
| ENV-03 | Android `9e896bbc` 在线，用户授权测试；可创建本机专用数据目录 | Android 开发验证、本机新库不再因旧交接缺失停工；正式签名/最终部署条件另记 |
| ENV-07 / DEC-01 | 用户明确暂缓正式安装包构建/导出 | ART-03/04 正式交付 NOT_RUN（用户暂缓），不构建替代物、不填 PASS |
| DEC-03 | 用户接受 ADR 0028 最后事务提交生效及首次迟到离线写的语义 | 语义决策已完成；仍需真实回归，不凭决策计 PASS |
| DEC-04 | 用户接受门禁现有建议阈值；低功耗 NAS 暂缓、本轮本机预检即可 | 阈值冻结；记录本机配置/实际范围，不外推 NAS 结果 |
| ENV-08 | Docker Desktop 已尝试启动但引擎仍不可达；宿主日志确认 Inference manager socket 访问错误 | ART-02 容器路径 BLOCKED；不执行 factory reset 或系统级修复，继续宿主隔离 API/Worker/Web |

ART-02 的本地构建入口现已补充：既有镜像脚本 `--output-dir` 导出 OCI 与版本/hash manifest，命令边界回归17项 PASS；此项仅解除“必须 push 才能构建”的工程缺口。Docker 引擎与双架构实际运行验收仍未解除。

ENV-06 局部进展：10000份紧凑有效 EPUB/PDF/CBZ 已实际导入/重扫；负载采集15项保护测试PASS。实际测量FAIL（LOAD-01），原文件/关联完整性收尾未验。约14 MB紧凑库不代表大文件或10万/30万表现。原工作区后续15项未提交变化归属无法确认，全部保留并排除于本分支验收。

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
| ENV-04 / DEC-08 | RG-02 / OPDS-01..03客户端部分 | 用户接管客户端测试并明确放行；代理未完成双客户端实测 | 已解除本轮阻塞；PASS（负责人放行，用户自行测试），停止客户端准备；协议回归独立保留 |
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
