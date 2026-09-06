# 1.0 发布证据与最终签收

2026-09-07 POS-06本轮收尾：`5b967260`同一测试代码/开发APK的原online相邻在另一全新隔离库实际PASS（13.045s）：5秒3899ms/r2、10秒7900ms/r3、暂停9904ms/r4，关闭重开实际9904ms，误差0；本地/独立GET最终r7一致。证据`artifacts/releases/1.0/5b967260/pos06-online-adjacent-20260907/`的device-online、online-evidence、fixture manifest、api-observations及cleanup-verification。935项校验全部匹配（929应用源码/原件和6最终测试源码/配置/APK），7次PUT200，无4xx/5xx；正常stop/exit0、Web配置恢复、18084/3105释放、自有reverse移除、独立包强停、输入消费、原App元数据及原工作区15改动不变。独立审查、POS-06实际原用例与必要相邻齐备，本工具补口结束，不再扩展。以下“尚待相邻/进行中”是历史。

当前恢复点：SYNC-03已关闭；POS-06的Android同步owner/HTTP/SQLite晚ACK和owner/DB重建重试子项PASS。仍需Chrome及其他引擎对应缺口，POS-05真实丢ACK/重试、POS-07真实客户端迟到提交、POS-08账号/服务器切换及POS-09/10等未覆盖场景按原矩阵继续；不能把本例当作SYNC-02的Chrome启动竞态回归。ENV-11/12执行限制、iOS和容器条件及正式APK/IPA暂缓分别保留，当前没有活动fixture/子代理；安装的releasecheck开发包含标准测试宿主，仅供后续隔离验收。下一项优先复用现有入口补进度异常或其他仍可执行门禁，不因缺少入口自动记外部BLOCKED；必要最小辅助须继续按DEC-07登记。尚未冻结RC，五组最终放行与正式发布均未完成。

2026-09-07 POS-06 Android同步owner/真实HTTP/SQLite子项实际PASS（12.965s，尚待原online相邻收尾）：从真实播放器确认的M3933ms/r2、N9939ms/r4完整报告建立新mutation；M实际提交r5并扣留返回，N已持久化；释放旧ACK后第二次push进入但尚未发出，独立连接核对N/local/pending及confirmedRevision=0全量不变，服务器仍M/r5。取消并join第一scope、关闭并重开独立case DB后，原N mutation真实重试成为r6，5秒内本地/独立GET一致且pending清空。证据`artifacts/releases/1.0/938afd24/pos06-native-late-ack-20260907/online-evidence.log`与`device-pos06-with-host.log`，实际API/Web源码ffd4228a（目录名938afd24为准备点，manifest记录实际HEAD）；主设备应用生产业务源码未改。929项源码/原件hash一致，6次PUT200，无4xx/5xx；独立审查无必修项。

这次仅新增一个针对性仪器用例及必要独立数据库参数，原确认/暂停/重开owner和断言保持；主审查去掉了多余确认封装、重复位置比较，并用位置值增加而非仅capture时间证明两个真实报告不同。首编译`test-build.log`为配置/测试类型引用失败，不是业务失败：release变体不能编译依赖debug专用视觉宿主的默认套件，Kotlin alias不能直接访问嵌套Accepted。独立opt-in APK仅编译既有release-live目录，默认全量套件及入口保留；结果类型直接引用现有公开application port定义。首次设备运行在Compose规则创建Activity前失败，`device-pos06.log`保留；输入文件当时未消费（device-fixture-before-retry.txt），没有发生业务调用。随后在现有隔离init中复用版本目录已有ui-test-manifest依赖提供标准Compose宿主，保留数据换装独立开发包并同输入复验通过，没有新增业务宿主或生产诊断。

本批独立开发APK SHA-256 `32d16edc070fafc4f7935bc150ac6c63476489102c510a97de958062428c6489`，测试APK `4c90d73da79416cef141b60a2bbc1edcc954956e9fa0810ccb91d933bfeaed44`；包名releasecheck / releasecheck.test，均Debug证书，含测试宿主，不是正式交付。验签/manifest/实际安装包hash及最终测试源码hash见同目录。fixture exit0、端口释放、独立包强停、自有reverse移除、私有输入消费及原App元数据/原工作区15改动保留均已核验；私有测试证据DB保留。本例控制的是实际HTTP响应返回到同步器的交付，不是socket丢包、进程强杀、普通UI或Chrome竞态。下一项只做原online必要相邻，之后停止此工具补口。

2026-09-07 POS-06最小执行补口进行中：独立只读核实已有单测/本地SQLite和正常在线仪器不能覆盖“真实HTTP提交M后，N已持久化才处理M的ACK”。依DEC-07例外，仅在现有Android online仪器中加入该用例：复用实际引擎已捕获的完整报告、KMP coordinator、真实HTTP port和生产Android SQLite，在测试拥有的port返回边界扣留实际ACK；不是伪造响应或声称网络丢包。释放旧ACK后核对完整N仍在，重建同步owner并真实重试确认。尚未编译/执行，不计PASS。辅助入口现有硬编码仍指向原App，必须改为现有独立releasecheck包；现有隔离init选择release测试variant，以免仪器误用含本地默认值的debug源码集。这两项仅服务设备数据隔离，不增加任意包名/平台配置。停止条件为本用例及必要原在线相邻实际通过、精确清理，无通用框架扩展。

POS-11相邻补验（938afd24）：本次详情投影改动后，复用现有`test_reading_status_public_projection.py`及`test_request_mutations.py`真实API/SQLite三项通过；无位置标已读仍无Locator、取消已读保持37%完整进度/公开投影及书籍身份批量状态保护保留。证据`artifacts/releases/1.0/938afd24/pos11-status-projection-20260907/regression.log`。仅此API保护，不替代首页/Reader真实客户端各格式完整验收，未新增测试或工具。

2026-09-07 SYNC-03已关闭（当前应用源码 `ead1ba20dce37e941d952d711cee7f72aa76bf42`）：在全新隔离库、Chrome production 与现有 f8847633 Android 独立开发包中重新执行原链路。Web确认5000ms→Android首页首次Playing5015ms；Android普通暂停/滑块确认15000ms/r8后，Chrome fresh reload在播放器尚未打开（audio空src/time0/paused）时直接显示50%和“当前收听 0:15”；正常打开播放器首个实际Playing为15秒，同一resource/asset，误差0ms。reading-units完整presentation与独立v5 GET相同，实际非空Chapter 2亦保留。Android再从首页新导入封面进入真实详情，reading-units pageSize=100返回200、继续收听可用、无无关能力提示。`android-detail-adjacent.xml`实际为首页，不用它证明详情；真正相邻证据为`android-adjacent-detail-cover-entry.xml`。

证据根 `artifacts/releases/1.0/ead1ba20/sync03-complete-20260907/`：inputs、bootstrap、web-confirmed、android-first-playing、android-confirmed、server-reading-units-before-reload及原生XML为实际记录；`chrome-observations.json`明确为实际CUA AX/DOM观察的人工转录，不冒充浏览器网络导出。931项hash复核全部一致（914应用源码及17样本/原件），设备已安装APK实测SHA-256仍为`c7c1fbed6ce9795f8c8d5ed68865e1dcd6c8800925056f8a6de3530bb576654b`。API有10次重新登录前401，全部位于Android正常登录行69之前；之后无4xx/5xx，12次进度PUT为200；浏览器关闭播放器后error日志为空。正常退出测试账号、关闭自有tab、强停独立包、移除自有reverse、fixture exit0/stopped、18084/3105释放及配置恢复均核验，见cleanup-verification。首次保存空pid输出没有生成文件，随后重查pidof退出1/空输出并显式保存，不把缺文件当作进程已退出证据。原仓库15项用户改动保留。

最小修复复用Reader已有一次presentation解码及public mapper，Library详情携带同一完整投影；原HTTP presentation schema移到共享contracts由Reader/Library两处消费，原定义删除、约束不变，无新查询或逐资源GET。Web复用v5-wire唯一presentation parser及pending/本页capture owner，时钟消费实际playback，不按百分比反推。原cff3e689与中间ffcbd4aa真实失败保留。针对性API原RED 1FAIL/16PASS→17PASS；Web缺时间原RED 1FAIL/2PASS→完整Web483PASS，lint/typecheck/pretest含i18n通过；后端进度/契约/Library相邻36PASS、mypy app及Ruff通过，OpenAPI生成Reader文件byte-identical。日志位于`54362ccf/sync03-server-presentation-20260907/`和`62377271/sync03-detail-overlay-20260907/web-presentation-*.log`。独立子代理实际diff复核无必要修正；本轮真实非空章节补齐其API空章节样本限制。没有测试工具扩展，停止围绕SYNC-03继续完善工具。

当前继续POS-04～10的未覆盖异常/生命周期子项，优先现有入口；ENV-11/12的真实回归执行限制、iOS、容器及负责人暂缓正式APK/IPA分别保留。本轮仅关闭上述具体缺陷，非全格式、真实竞态全覆盖或同冻结RC放行；下方较早OPEN/PARTIAL均为历史过程。

2026-09-07 ffcbd4aa真实候选未闭环：新库M4B同一原件经Web正常5秒确认、Android首页首次5015ms、暂停/滑块15秒并GET r8后强停；Chrome reload直接50%（旧已确认overlay已修），但当前收听为书名。该页面audio元素空src/time0/paused，尚未打开播放器，不把播放器后来刷新充当详情通过。`ffcbd4aa/sync03-detail-regression-20260907/chrome-observations.json`、web/Android-confirmed.json、server-book-before-browser-reload.json、server-reading-units-after-reload.json留证；后者chapter/page字段null，无完整presentation。930项源码/原件hash一致；正常退出、自有标签关闭、独立包强停、自有reverse移除、fixture stop/exit0/端口释放，cleanup-verification.json保留。后续源码修改在该运行关闭后进行，新候选需重验，SYNC-03保持OPEN。

同缺陷后续Web原时钟显示函数针对性RED为1FAIL/2PASS，保留missing-server-position-red.log；正在复用v5-wire唯一presentation parser读取服务端详情完整投影。对应时钟/本地pending优先/API验证及原wire相邻25 PASS（server-presentation-web-focused-configured.log）；第一次从仓库根执行因Web路径别名未加载失败，改从apps/web原入口执行，不修改工具。后端投影尚待完成，不能计整链通过。

2026-09-07 SYNC-03候选ffcbd4aa：原cff3e689三格式实际详情旧5秒与GET新15秒、打开播放器纠正的转录见ordinary-audio-sync/handoff-observations.json。主追踪确认详情启动读取exact并无条件overlay；在现有books能力抽出原读取用例后针对性对照，最终正常原子exact+pending前提下原行为1FAIL/1PASS，候选完整Web481 PASS及lint/typecheck/pretest（含i18n）通过。初始第二test模拟pending存在exact缺失，不是原子写入正常状态，独立审查指出后改为正常两者俱在；保留两份原RED日志，不声称两个业务缺陷。复用getV5PendingProgressForIdentity；移除页面的重复初始读取和两个重复capture合并片段，由既有local-reader-progress owner统一merge；百分比/位置/继续资源共用该来源。审查另指出book旧响应跨ACK的静态交错风险，候选以当前server/user/book页面scope的capture引用跨book刷新保留，fresh页面不继承历史；这是代码与pure merge保护，尚未伪称真实竞态复现。证据62377271/sync03-detail-overlay-20260907下原RED、focused-green、web-*-final.log。首次完整test两次因python3入口/execFile路径环境失败，复用现有release-bin/python3.cmd并设置既有PYTHON_EXECUTABLE后原pretest完整通过，未改工具或跳过检查。真实Chrome候选原场景待执行，不关单。

POS-07新增针对性API验收e39e6de2：M r1→N r2→捕获时间更早但首次到达的C r3，C完整opaque Locator和17%展示被独立GET及ORM保存；M精确重放仍回原r1且current=C，同M改payload409不覆盖C。子代理只写现有test_reader_v5_progress.py，主审查实际131行diff与17 PASS、Ruff结果，证据62377271/pos07-late-first-submit-20260907/。没有业务修复/新测试工具；仅服务端协议子项，不等于真实客户端离线或受控事务完成顺序通过。

2026-09-07 RG-04服务端相邻验证：在62377271仅文档变更的主工作树执行既有test_reader_v5_progress.py，16 PASS；真实API/SQLite覆盖opaque报告、已成功mutation重放不覆盖后写、同mutation异payload409、bootstrap/GET一致及已读状态不创建Locator，另有应用回滚和双线程revision单调测试。日志为cff3e689/ordinary-audio-sync-20260907/v5-progress-contract-regression.log。仅服务端/应用子项，不替代真实客户端丢回包、迟到ACK、受控事务顺序或跨端离线验收；首次迟到新mutation的既有必测缺口正补针对性回归，无通用工具扩展。

2026-09-07 普通UI跨端音频（cff3e689）：沿用既有fixture与独立开发APK f8847633/c7c1fbed…，全新专用账号/库分别导入M4B/M4A/AAC三原件。Chrome暂停、滑块5秒、关闭后真实GET确认：M4B r7、M4A/AAC r5；Android冷启首页继续，系统首次Playing为5015/5015/5000ms，偏差15/15/0ms。Android正常暂停/滑块中点后GET确认M4B r17/15000、M4A r8/15000、AAC r8/15039ms，再强停独立包；Chrome正常reload和打开播放器，实际HTMLAudioElement分别15/15/15.039s、同asset、正在播放，误差均0ms。两端clientId不同，无人工PUT或伪造Locator；仅六个正常短时交接子项PASS。M4B首次反向采样在媒体加载前及播放数秒后，无法量化初始恢复，保留该观察；重新正常生成原生确认后，紧邻打开动作只读采样获得15秒，不把观察延迟算作产品失败或偷偷删除。

证据根`artifacts/releases/1.0/cff3e689/ordinary-audio-sync-20260907/`：handoff-observations.json为实际CUA只读媒体观察转录，*-confirmed.json为独立GET，*-first-playing.json及*-restored-ui.xml为真机原始输出；inputs.json、asset-source-map.json、bootstrap与installed-apk.json对应身份。M4B/M4A仍为同字节不同路径/资源，不外推独立编码兼容性。932项源码/原件hash全部一致；API无5xx，11个401均在本轮Android正常login前（旧测试DB会话及Web登录前），84行登录后无4xx/5xx，原日志保留。浏览器error为空；正常退出/自有tab关闭、独立包强停、仅移除自有reverse、fixture stop/launcher0/无cleanup error、端口释放和配置恢复已记录。首个校验命令未启UTF-8而在读取manifest时失败，配置PYTHONUTF8后原检查完成，无产品或工具改动。

前轮NR2独立证据复核支持AUDIO-11/12关闭及0/31/31ms，不外推本轮；指出部分汇总缺少直接引用，实际chapter-first-player-ui.xml、chapter-m4a-start-ui.xml、four-track-start-ui.xml存在。设备安装hash/部分清理动作仅保留当时汇总，不能声称离线重算设备原件。本轮保留reverse与PID、工作树原始输出。额外实际观察：Chrome重载详情仍展示旧Web进度，打开播放器立即更新至新原生确认且正确恢复；已交只读定位，不作为详情展示通过，后续结论另记。

2026-09-07 AUDIO-11/12真实回归已通过并关闭：新包源码f8847633、SHA-256 c7c1fbed6ce9795f8c8d5ed68865e1dcd6c8800925056f8a6de3530bb576654b，独立包com.ermao.library.releasecheck保留UID替换安装，设备base.apk SHA与产物一致；原App UID/安装元数据不变。全新真实API/Worker/production Web源码2a4c4ec4（与包源码只差发布记录），不是冻结RC。证据根`artifacts/releases/1.0/f8847633/android-normal-ui-regression-20260907/`：normal-ui-observations.json、安装/签名记录、真实UI XML和截图、系统MediaSession首次Playing、前后只读ORM均已核对。四轨AAC确认17380ms/r7，同包强停冷启→普通首页继续进入播放器，第四轨同asset恢复17380ms，误差0、点击到首次Playing1266ms。新详情无错误PDF/comic renderer文案，四轨及两个单音频的收听动作均实际可用。M4B、M4A三章节各自普通列表选择第二章10000、下一章20000、上一章10000；各自确认10000/r6后强停冷启，从首页进入仍显示第二章，首次Playing均10031ms（误差31；点击后1000/938ms）。资源→源路径/asset映射以chapter-first-orm.json为准，不能仅凭同标题或相同音频字节区分格式。仅这些短时/已确认/普通入口子项PASS，不外推长时、异常、全部音轨边界或其他平台。首次fixture遗漏opt-in在服务创建前退出；原失败fixture-launch.log/fixture-exit.txt保留，配置后使用fixture-configured-launch.log，最终fixture-configured-exit.txt=0。保留旧隔离库cookie导致新登录前10个401，正常账号登录后无4xx/5xx，26次PUT200；authentication-log-check.json区分阶段。原7fixture、实际6音频和911应用源码共932项hash无变，配置恢复、stop/shutdown及端口释放、reverse清除、凭据输入文件删除、独立App强停均核实；当前own进程AndroidRuntime未见FATAL（仅该观测范围）。Bohr独立只读AUDIO-12复核无阻塞，主已核对真实UI并关闭子代理。原85662d5d失败保持，停止这两个已闭环缺陷的工具完善。下一项先补Chrome↔Android的M4B/M4A/AAC真实双向交接：既有AndroidAudioOnlineConfirmationInstrumentedTest的restoresWebMp3ProgressAndConfirmsPlaybackForWebHandoff明确只接受audio/mpeg，不改该已闭环用例扩工具，优先复用当前独立包普通UI与Chrome CUA真实播放器。Chrome接口已核验，空白预备tab35842949已关闭，没有新fixture或交接结果；新回环测试库只使用仓库既有合成测试登录输入，不借系统剪贴板传递秘密。APP继续复用已核验f8847633/c7c1fbed包，服务端按执行时提交取证。ENV-11/12、iOS、容器和暂缓正式产物不变。

2026-09-07恢复入口：业务候选`f8847633fd436d981bc628e9e464814324d04bac`已提交推送，含AUDIO-11首页音频路由/资源标题及AUDIO-12详情提示修复。新独立开发APK已构建与验签，尚未安装：`artifacts/releases/1.0/f8847633/android-normal-ui-regression-20260907/android-normal-ui-development.apk`，SHA-256 `c7c1fbed6ce9795f8c8d5ed68865e1dcd6c8800925056f8a6de3530bb576654b`；package=com.ermao.library.releasecheck，1.0.0/1，debuggable、CN=Android Debug，绝非正式交付。该目录build.log、apk-verification.json、apk-badging.txt、apk-signature.txt保存源码/配置/签名证据。设备仍保留旧验收包（85662d5d）且强停，原com.ermao.library未变；无活动fixture/monitor/子代理，18084/3105和reverse已释放。下一项必须先使用现有scripts/python_release_live_fixture.py在新隔离目录启动实际服务，再以adb -s 9e896bbc install -r替换独立包，正常UI登录/导入四轨和章节样本，复验AUDIO-11首页冷启继续同一AAC资产及≤2秒恢复、AUDIO-12详情提示、原生M4B/M4A章节导航相邻；不得把旧库确认值直接写入新库充当通过。样本来源/hash及原失败均在85662d5d/android-normal-ui-20260907/input-and-import.json和normal-ui-observations.json，继续复用现有入口，不扩工具。正式包仍暂缓，未冻结RC。

2026-09-07独立复核收尾：gpt-5.6-sol/max只读核对AUDIO-11的准确readerType/资源身份、共享音频启动、空ID和非音频入口，提出首页titleHint应优先resourceTitle。主已据实修正并补非空/缺失/空白标题payload断言，Android完整host及lint再次通过（audio-11-title-host-lint.log，33s）；AUDIO-12主复核确认提示消费现有主动作owner，原不可读/Unsupported断言保留。子代理已关闭。74098307开发包构建成功但不是最终标题修订源码，不用于原场景回归；应从标题修订后的已提交候选重新增量构建。AUDIO-11/12真实回归仍NOT_RUN，不能关闭。

2026-09-07 AUDIO-12候选：详情能力提示直接消费已有workDetailPrimaryActionPresentation的可用性结果，消除PLAYER音频被Reader专用Unsupported误判；不可读、缺资源与真实不支持的提示保护保留。新增原场景及PDF/CBZ/EPUB相邻呈现断言，旧条件28项中1失败（audio-12-red.log），候选完整host/lint通过。未改文案、格式列表或安全策略，真实新包详情待复验，暂不关闭。

2026-09-07 AUDIO-11候选：Android继续项透传shared已有readerType，首页按真实resumeResourceId调用同一openAudio启动owner，详情/章节入口也使用该owner；不拼造ResourceContent，不修改Reader安全边界或Locator。旧行为针对性实际7项中2失败（映射和路由），修复后7项通过；原日志audio-11-red-configured.log、audio-11-green.log在85662d5d/android-normal-ui-20260907。首次命令因未配置ERMAO_ZIG未到测试，保留audio-11-red.log；随后复用既有0.14.1安装，无新增工具/系统变更。最终相邻Android host222与shared host429、lint通过，零失败/跳过（Gradle允许未受影响任务复用）；原生新包原场景尚待执行，AUDIO-11不关闭。

2026-09-07 Android普通UI原场景：独立开发包com.ermao.library.releasecheck已在9e896bbc安装并正常登录全新隔离库，原App的UID/codePath/version/安装时间前后不变。源码85662d5d、APK SHA-256 1ed92ec8f3b4aaeba831187880b9111f84e1e07405f6ebb18a22d15333be997c；不是正式APK。证据根`artifacts/releases/1.0/85662d5d/android-normal-ui-20260907/`。四轨普通详情/队列实际操作及系统只读媒体回调确认M4B→AAC自然切轨；不外推全部边界或长时。AAC显式暂停后服务端确认17182ms/rev64，仅强停独立包并冷启动，首页“继续阅读”进入电子阅读器报格式不支持，登记AUDIO-11 FAIL。关闭错误页后，从同一作品详情“继续收听”进入，真实MediaSession第四轨首次Playing位置17182ms（点击后1390ms），误差0ms；仅详情恢复对照PASS，首页恢复仍FAIL。音频详情同时两次显示无关的PDF/漫画原生渲染器缺失提示，登记AUDIO-12。`normal-ui-observations.json`关联UI XML、系统状态序列、只读ORM和失败截图，保留早期EOF/操作观察，不计作明确暂停证据。原始7fixture、额外6音频与911应用源码共932项hash全匹配；API无4xx/5xx、67次PUT200。媒体monitor正常q退出；测试包强停保留供修复回归，原应用不动，reverse与临时UI文件已清理、输入凭据文件已删除，fixture stop/exit0、端口释放、Web配置恢复。详细见prestop-verification.json与cleanup-verification.json。后续先修复实际入口阻塞，再补未执行的原生章节普通UI；未冻结RC。此前“尚未安装”是历史准备状态。

当前结论：**R2逐项验收与缺陷收敛，尚无整体放行依据**。正式安装包构建/导出由用户暂缓；尚未冻结RC。既有R1证据编号保留，不能将不同候选的局部通过合并成最终GO。

## R1 当前执行与恢复入口（2026-09-06）

2026-09-07 Android隔离UI开发包已构建验证（应用源码85662d5d + 独立init配置hash，尚未安装）：`artifacts/releases/1.0/85662d5d/android-normal-ui-20260907/`保存build-isolated-ui.log（1m27s成功）、apk-verification.json、apk-badging.txt与apk-signature.txt。包名com.ermao.library.releasecheck、入口com.ermao.library.MainActivity、开发签名CN=Android Debug、debuggable；SHA-256 `1ed92ec8f3b4aaeba831187880b9111f84e1e07405f6ebb18a22d15333be997c`。选用现有release空登录默认值，逐DEX检查不含本地Debug预填server/email；不在日志重述这些值。无应用业务源码变更，不作为正式签名APK。子代理普通UI入口只读报告已由主复核：Shell书目为合成Repository，音频UI测试只是投影，VisualFixture无网络；该子代理已结束。下一项为独立包安装、完整MainActivity实际登录与四格式/章节/多轨操作，缺口尚未计PASS。

2026-09-07 Android普通UI准备（85662d5d）：现有release-live只在Compose宿主显示RG04并直接调用真实音频runtime，不能充当Book Detail/MainShell完整入口。MainShell直接使用ErmaoLibraryApplication的应用级账号/媒体状态，ReleaseAudioContext返回包装Context，无法不改真实用户状态而直接套入。当前已授权设备9e896bbc在线，原应用宿主PID5053空闲、前台为MIUI Launcher，reverse为空；专用包com.ermao.library.releasecheck尚未安装。不得把此前“主App无进程”历史描述当作执行时事实。

本次最小辅助改动服务RG-03 AUD-01/02/04及RG-04普通UI：新增仅显式-I调用的test-support/release-live/android-ui.init.gradle，使用现有release空登录默认值源码集、独立包名/Android UID、开发签名和可调试标记，复用完整MainActivity/Application/真实网络/持久化/播放器。现有仪器不能证明普通UI，原应用存储不属于专用数据，因此现有方法不足；不新增测试框架或生产运行路径。普通Debug源码集包含本地预填账号值，独立验收选择既有release空默认值，既有文件保持。此包只用于隔离设备开发验收，绝非暂缓中的正式签名APK交付。停止条件为既有正常UI必测操作、真实位置/HTTP及专用包清理能够完成；不再增加平台/配置通用能力。AGP9.1.1本地API已核实finalizeDsl/signingConfig/debuggable接口，实际构建安装尚待执行，不能计PASS。

2026-09-07 AUDIO-10闭环（生产候选521e74ed）：同一组原失败四轨原件在全新库以正常分卷UI导入后，详情HTTP186908.147、bootstrap186908.162及播放器列表均按01-MP3/03-M4A/04-M4B/02-AAC排序，assetId、sortOrder和轨号逐项一致；点击详情第二轨实际M4A约2.125s、全局约32s/27%，原错误顺序消除。播放器列表切M4B和下一轨控制切AAC分别核对实际媒体资产。全局滑块定位最后AAC中段，真实ACK r8保存14841ms、Locator position=4与AAC资产；关闭重开实际AAC15.938585s，偏差1097.585ms≤2秒。MP3在28s由正常播放自然到EOF后，未发切轨命令即实际自动播放M4A11.041434s；只证明该边界自动接轨，不声称量化无缝或全部边界。

证据根`artifacts/releases/1.0/521e74ed/chrome-audio-10-20260907/`：chrome-observations.json、additional-library-inputs.json、final-orm.json、final-verification.json与fixture原始API/构建/源码记录。真实进度PUT22次200，无HTTP4xx/5xx、无浏览器error/warn；7生成样本及4额外原件、911应用源码均无差异，stop/launcher0、配置恢复、账号退出、自有标签关闭、18081/3102释放。运行中仅独立编辑一个契约测试，生产源码固定521e74ed，未冒充冻结RC。

子代理新增单个真实SQLite/ASGI API契约用例，主审查实际diff、格式整理并运行整个test_book_resource_detail_queries.py，16 PASS（contract-regression.log），覆盖两页与bootstrap同序、连续索引、轨号/MIME保留及既有授权/图片等相邻。该测试文件使用存在的字节占位文件，证明查询协议、不证明解码；子代理“实际样本”措辞据实限定，真实导入/解码证据来自Chrome。与已保留的原unit RED、候选unit/相邻32 PASS、mypy及Ruff共同闭环，AUDIO-10关闭，达到DEC-07停止条件，不再围绕此缺陷扩工具。导入排序owner与其持久化sequence_index被复用，详情二次按文件名覆盖音频顺序的行为已移除，图片路径保护保留。

当前仍R2逐项收敛：章节与普通音频、多轨短时结果是明确源码的开发子项，不合并成最终RC。下一可执行项为Android普通详情/播放器的现有四格式及章节/多轨入口、其余进度异常和移动生命周期缺口；ENV-11/12的独立浏览器验收仍待既有外部执行条件，iOS/容器条件和正式包暂缓分别保留。所有本轮子代理、fixture与仪器任务已结束，没有后台承诺或对外发布。

2026-09-07内嵌章节增量（04231cda）：两个独立M4B/M4A原件通过正常Chrome桌面导入/详情/播放器显示三章0/10/20s，章节列表跳转及上一章/下一章实际媒体时钟10/20s；M4B确认20000ms/r11第三章→重开21.133828s，偏差1133.828ms；M4A确认10000ms/r9第二章→重开10.132305s，偏差132.305ms，均≤2秒。真实bootstrap三条units与对应资产、服务端chapter index/navigationKey一致；这两个章节短时子项PASS，不外推长时/多轨/原生。证据`artifacts/releases/1.0/04231cda/chrome-audio-chapters-20260907/`中的chapter-observations.json、first-chapter-middle-orm.json、m4a-chapter-middle-orm.json、final-orm.json及原API日志。

同轮首次四轨实际验收FAIL，登记AUDIO-10：正常分卷库根下单个目录被正确识别为一个AUDIOBOOK_DIR、4个TRACK；详情顺序01-MP3/02-AAC/03-M4A/04-M4B，但bootstrap/播放器顺序01/03/04/02，详情点击第二轨实际进入全局约90s/75%。`audio-10-original-failure.json`记录真实reading-units请求186536.844与bootstrap186536.848均200、资产身份和当前时钟，final-orm.json保留sequence_index。原源MP3/M4A/M4B轨号均1，AAC轨号2；现有导入owner优先盘号/轨号再路径，子代理“文件名保证顺序”的推断已由主纠正，不能据它伪改真实预期。

原运行收尾：原7个fixture样本和额外导入6原件、911应用源码均未变，API5xx=0；仅初始化保留地址.invalid被422拒绝，随后专用.invalidx正常通过。退出账号、关闭自有Chrome标签、stop正常/launcher0，配置恢复和18081/3102释放，详见final-verification.json。Chrome原失败保留，不在运行中替换源码。

AUDIO-10候选复用导入持久化sequence_index，经既有ResourceAssetDetail.sort_order传至详情，仅音频排序优先该值；不重写disc/track规则，不改变Reader播放顺序或图片自然排序。旧单测把音频固定为自然文件名排序，与真实两端契约冲突，已改为验证导入顺序并保留原图片/轨号断言，补分页/过滤封面/单文件相邻。实际原代码2 FAIL、7 PASS→候选9 PASS，相邻audio/reader API32 PASS，mypy494通过；日志audio-10-unit-red.log、audio-10-unit-green.log、audio-10-adjacent.log、audio-10-mypy.log。真实SQLite双端一致性回归和新候选Chrome原场景仍待完成，AUDIO-10未关闭；测试仅针对该真实缺陷，不改fixture或通用工具。下一项是候选Chrome四轨顺序/切轨/恢复，之后继续原生与其余异常门禁。

2026-09-07 Chrome普通音频界面增量（源码d62438f0）：AUD-01 M4B/M4A独立原件经正常setup、书库导入、详情打开播放器、播放/暂停、键盘滑块定位15s、关闭重开，两子项PASS。M4B实际HTML音频恢复16.126938s，距已确认15s偏差1126.938ms；M4A恢复15.108089s，偏差108.089ms，均≤2000ms，包含重开自动播放到人工暂停的时间。最终只读ORM分别16127ms/r14、15108ms/r16，真实API PUT分别14/16次200，媒体206，浏览器error/warn为空，无API5xx。两个30秒样本同SHA `3ee91a25eeb4fd8c6261db8c660d2e84d0d624e8686499c35d0c06fbab6c6833`，只证明两扩展名各自真实路径，不作为不同编码/内嵌章节证据。

证据根`artifacts/releases/1.0/d62438f0/chrome-m4b-m4a-20260907/`：`chrome-observations.json`是实际CUA交互与只读媒体时钟的转录，`first-resource-middle-orm.json`、`m4a-middle-orm.json`、`final-progress-orm.json`保留服务端事实，`fixture/api.log`保留原HTTP日志，`manual-preparation.json`/原始manifest及`final-verification.json`保留输入和收尾。原7样本+M4B/M4A两样本共9个，原件和911应用源码均未变，准备后manifest未变。Chrome导出功能不支持，未伪称有本地截图；一次M4A暂停点击因已自然播到EOF无匹配，复核真实状态后继续。人工hash检查初次误将CBZ源目录当文件，按现有sourceFiles清单逐文件核验后通过，未改工具或产品。退出测试账号并关闭自有标签页，stop正常触发、launcher exit0，保留Windows子进程停止码；配置恢复、工作树干净、18081/3102释放，没有活动fixture。

本轮没有业务缺陷或工具改动；只关闭Chrome桌面普通界面短时子项，不覆盖精确5/10秒确认窗口、移动视口、后台、长时、章节、多轨、原生普通UI或最终RC。子代理仅准备现有四格式的专用输入并已关闭，主用原ffprobe和hash独立复核6个文件。`artifacts/releases/1.0/d62438f0/audio-chapters-multitrack-20260907/`中的`sample-manifest.json`、`commands.txt`及`parent-verification.json`记录来源和结果：两个M4B/M4A章节样本均30s、三章0/10/20s，音频以-c copy保留，另四轨原件复制hash一致。样本准备不是客户端PASS。下一可执行项用现有入口导入这些章节/多轨输入并验证导航、切轨和恢复；不增加通用工具/编码矩阵，不重跑已闭环项。ENV-11/12、iOS/容器及暂缓正式包仍独立保留，尚未冻结RC。

2026-09-07当前恢复点：主候选eecff919已提交推送，移动生产源码与已安装主APK对应的ac25497d无差异，只增量安装测试包。新增Android MP3后台与真实短暂音频焦点中断两子项通过，原在线恢复相邻的新增前置误用TEST-13已修正并实际回归通过。主已核验全部原始日志、原件/911应用源码每轮无差异、四个fixture shutdown无错及exit0、所有专用UUID/偏好清理、reverse为空、18084/3105释放；主工作树干净。设备测试host空闲进程5053保留、主App无进程。子代理独立审查已完成并关闭；没有活动fixture或仪器任务。尚未冻结RC，不把不同源码候选的开发结果合成最终放行。

证据根`artifacts/releases/1.0/5f75f35f/android-audio-lifecycle-20260907/`，`final-verification.json`汇总并保留各子目录原记录：

- `background/`（0b234f2d）：Activity实际PAUSED→STOPPED，全程无RESUMED；5秒确认3879ms/r2、10秒7891ms/r3，后台暂停10662ms/r4。1 PASS（13.078s），真实progress GET/PUT分别5/4次200。
- `focus/`（0b234f2d）：真实SDK AUDIOFOCUS_GAIN_TRANSIENT获准，中断前3901ms/r2，自动暂停4920ms/r3并稳定，abandon获准后自动Playing、8958ms/r4确认，最后暂停9934ms/r5。1 PASS（13.172s），GET/PUT分别6/5次200；中断至恢复未用play/pause命令伪造。
- `original-adjacent/`（0b234f2d）：保留TEST-13原FAIL，5/10秒及暂停9913/r4后，第二次open被全局音频活跃前置挡住，未执行重开断言。`original-guard-fix/`（eecff919）：该检查移至fixture首次获取播放之前，旧App会话/确认/恢复断言全保留；原用例1 PASS（13.069s），3898/r2、7905/r3、暂停9905/r4→重开9905/r7，误差0，GET/PUT各7次200。所有运行无API5xx。原close后的CLOSED_PENDING照实保留，后台/focus不据此声称Stop outbox已确认。

本次仅在既有测试类增加两个必须场景并等价抽取checkpoint/pause；fixture/provisioner零修改，无生产代码变更。编译及lint（含androidTest分析）通过，日志`build-test-apk.log`、`lint.log`、`build-lint-guard-fix.log`；初始测试APK SHA `58608971ef1eec702623020ac4789add3cca9503e074f9e97bcc4c3882b2e69d`，guard修正后及当前安装 `1fd94b216668916aedf8928d15e0ad33f0a080170aba3cca165d5104c128da27`；主APK始终 `2fb7cb3214b1c19353f082b724c55981c095533cf9bbacd901fae80df07826f6`。独立复核确认旧5/10秒、pause断言等价，guard初始放置不合理，移动未削弱原保护。原失败与必要相邻已闭环，达到DEC-07停止条件，不继续完善该项工具。

真实限制和下一项：新增两场景为MP3的隔离运行时/真实HTTP链路，不是四格式各自后台全矩阵、锁屏、真实来电、普通App完整UI或最终RC。范围仍仅M4B/MP3/AAC/M4A；继续Web M4B/M4A及Android普通详情/播放器入口、范围内内嵌章节/多轨与进度异常。独立审查并由主核对，audio_metadata章节提取、Web bootstrap章节映射/导航及Android selectChapter现已存在，章节验收不是新增功能；现有短样本单asset且units为空，不能证明该项。后续用原工具和专用样本执行，不扩大编码矩阵。ENV-11/12、iOS/容器及暂缓正式交付分别保留，不重复询问既有授权。

2026-09-07 AUD-01 M4B原生短时子项PASS：独立全新库、`.m4b`原件经现有导入/bootstrap与真实Media3运行时，5秒确认3897ms/r2、10秒7901ms/r3，暂停9912ms/r4→重开9912ms、最终r7，误差0；仪器1 PASS（13.123s）。证据`D:/www/ermao-release-android-formats/artifacts/releases/1.0/ac25497d3a4ee29383ddc97ac27c0a7230a5d078/android-m4b-20260907/`的instrumentation.log、online-evidence.log、media-probe.json、manual-preparation.json、result.json及fixture原始记录。主核对实际GET/PUT各7次200、无API5xx、909源码及8样本hash无变化、准备后manifest不变、shutdown无错/exit0、专用UUID及两个偏好文件已清理、reverse为空、18084/3105释放、工作树干净。

样本为MPEG-4 AAC-LC/22050Hz单声道30s、272503字节，SHA-256 `3ee91a25eeb4fd8c6261db8c660d2e84d0d624e8686499c35d0c06fbab6c6833`，与既有M4A原件同hash。因此仅证明M4B扩展名独立导入/播放/确认/恢复路径，不代替有章节/长时/多轨或普通界面入口。实际环境仍ac25497d development，沿用已核验main `2fb7cb32…` / test `531ae5c9…` APK，未构建安装，不是最终RC。测试输入准备复用前述7+1方式，工具零修改；手工汇总最初误用/position匹配而显示零请求，已根据原日志真实/progress路径修正为各7次，原日志和运行结果未变。

下一可执行项：RG-03音频后台/中断及RG-04 POS-01/02的Android真实链路。现有仪器仅覆盖前台播放/暂停重开，无法证明后台持续确认及真实焦点中断后持久化；只允许在既有测试类增加两个针对性用例，共用登录/隔离存储/运行时/确认/清理owner。停止条件为这两个真实场景及必要相邻通过，不扩fixture/provisioner或报告框架；焦点中断不冒充真实来电。子代理只写该测试文件，主串行整合验证，不新建分支。

2026-09-07最新恢复点：主基线c560d1a2，DEC-09按用户明确名单仅保留M4B、MP3、AAC、M4A四种有声书格式；不继续Vorbis及其他编码矩阵，既有产品能力、有效断言和历史证据保持。用户告知子代理用量恢复，已安排独立只读核验四格式缺口。下一步优先补M4B实际源文件的原生播放/确认/重开，再继续范围内后台中断及进度异常；不把已有M4A结果当作M4B通过，不扩通用工具。

Vorbis中断收尾（均非播放验收）：`D:/www/ermao-release-android-formats/artifacts/releases/1.0/ac25497d3a4ee29383ddc97ac27c0a7230a5d078/android-vorbis-20260906/`保留原600秒寿命超时，shutdown报告processesStopped=true、cleanupErrors=[]；子代理用量中断后未完成样本准备/仪器运行。`android-vorbis-20260907-recovery/`曾启动全新fixture，收到DEC-09后写入其既有stop文件，shutdown报告status=stopped、primaryError=null、cleanupErrors=[]、processesStopped=true，launcher exitCode=0；原7样本manifest保留，未追加Vorbis、未provision设备或启动仪器。主代理核实18084/3105无监听、adb reverse为空、Androidformats工作树干净。两个目录保留为中断/范围取消证据，不能登记Vorbis PASS；正式构建仍暂缓、RC未冻结。

本轮收尾恢复点`64b966aa`（业务修复d6a34cf0，均已推送）：两音频子项与清理已由主复核，链接修复另经独立只读审查通过，确认PreviewTile调用、漫画page=0可消费和PDF链接不变；READER-07仍待真实浏览器。主/Androidformats工作树清洁，自有fixture/instrumentation均结束，reverse为空、相关测试端口释放；设备原有测试包休眠进程28816保留，无主App进程。下一项继续其余已获样本的原生格式及进度异常；ENV-11/12等待已提出的外部执行条件，不重复请求授权、不绕过工具拒绝。正式产物仍暂缓，RC未冻结。

当前主基线`d6a34cf0`已推送；READER-05/06/07代码检查通过、真实浏览器回归仍待ENV-12，SYNC-02对照仍待ENV-11。此次另补RG-03 AUD-01/AUD-08及RG-04 POS-01/02的Android真实运行时子项：M4A/MPEG-4 AAC-LC与Ogg/Opus分别在独立全新数据上完成播放、5/10秒实际服务端确认、暂停及关闭重开，均PASS。M4A确认3898ms/r2、7901ms/r3，暂停9899ms/r4→实际重开9899ms；Opus确认3887ms/r2、7892ms/r3，暂停9909ms/r4→实际重开9909ms，两者恢复误差0，阈值未改变。不覆盖长时、多轨、后台中断、其他内部编码、普通界面完整入口或最终RC。

证据根`D:/www/ermao-release-android-formats/artifacts/releases/1.0/ac25497d3a4ee29383ddc97ac27c0a7230a5d078/android-m4a-opus-20260906/`：各`m4a/`与`opus/`的instrumentation.log（各1 PASS，13.136s/14.613s）、online-evidence.log、真实bootstrap、result.json和shutdown；根source-verification.json及final-handoff.json保留源码/设备/清理。主已实际核对两仪器终态、完整记录、各7次GET/PUT200、API5xx=0、当前测试PID无fatal日志、每组8个样本源/fixture不变、三个配置和两个工具未变、准备后manifest不变及服务退出。909应用文件每组无差异，2623移动文件无差异。

运行设备为已授权9e896bbc Android12/API31，复用已安装开发APK（main SHA-256 `2fb7cb3214b1c19353f082b724c55981c095533cf9bbacd901fae80df07826f6`，test `531ae5c92e2879f87d8ff23d48c4f03e6d65a8ae52c7e686457f28efff5620c9`），未构建/安装新包。实际源码/后端环境为ac25497d，移动Git tree与主同`22dbef16551bedec32b987e4f9349da837074aa1`；完整backend tree不同，主多出READER-03 HTML/MOBI/XML相关5生产文件和3测试，不能声称完整环境同主。此为明确基线的开发验收，不合并成最终RC证据。

本次样本准备未改工具：既有fixture固定7样本，原CLI仅可按唯一MIME筛选已导入资源。每次在API仍未初始化时，在专用library追加一个原M4A或Opus文件，保留manifest.generated.json并显式登记manualSampleAdditions、前后manifest hash及8文件/8样本一致，随后复用原provisioner和仪器用例。manual-preparation.json证明原7样本未改、目标MIME唯一、准备前后均未初始化。M4A源SHA `3ee91a25eeb4fd8c6261db8c660d2e84d0d624e8686499c35d0c06fbab6c6833`，Opus源SHA `e51f852204dde95bfe66e9770eacc327a25ffe08ae7b1dc226cb077850cf23f4`；ffprobe分别AAC-LC/22050Hz单声道30s、Opus/48000Hz单声道30.0065s，实际引擎时长30000/30006ms。已达到这两个短时子项的停止条件，不扩工具或重复执行，继续其他未完成格式与异常场景。

READER-07（原RISK-07）已在实际链接生成owner边界复现：`23ae8c2e`的resourceDetailItemHref把漫画展示第1页生成`?page=1`，而Reader现有入口按零基pageIndex解析；正常6页末页同样会超出索引范围。新增受控回归原代码3 PASS/1 FAIL，首次断言实际得到page=1而期望page=0，证据`artifacts/releases/1.0/23ae8c2e/comic-detail-entry/red.log`。这不是已经完成真实点击后引擎恢复，原真实6页详情展示与源码链作为相邻事实保留。

候选仅在resourceDetailItemHref的漫画页链接边界把pageNumber减一，PDF仍一基数，章节/音轨路径不变；页面预览PreviewTile与已有章节入口仍调用同一owner，无新URL协议或辅助工具。CBZ及IMAGE_DIR的第1/3/6页和PDF相邻5 PASS，完整Web478 PASS/0 skip、typecheck-final/lint/i18n通过。首次typecheck因新增测试字面量数组推断为string失败，保留typecheck.log；仅增加as const保持ResourceFormat类型后通过，不改阈值/规则。READER-07待真实详情点击首/末页及POS-09恢复，不能由链接边界GREEN关闭；ENV-12、其他格式/进度和外部条件不变。

`d6a34cf0`已提交推送上述修复；现有后端`tests/unit/modules/library/test_resource_details.py`相邻7 PASS，明确验证PDF展示页号与IMAGE_DIR自然顺序后的一基page_number，日志`comic-detail-entry/backend-page-contract.log`。该受控后端契约不是实际浏览器点击证据。

最终控制栏候选检查完成：`reader-console-regression/web-test-final.log`477 PASS/0 skip，typecheck-final/lint-final/i18n-final均退出0；独立只读审查通过四处按钮、漫画index边界、双页owner、EPUB与RTL保留。真实浏览器回归仍受ENV-12限制，READER-05/06不关闭。自有服务均已结束，无后台测试仍在运行。

ENV-12恢复使用原Playwright入口，无新脚本。可在本机PowerShell手动运行以下命令并保留实际结果；不涉及生产、发布或真实账户，3100为原配置测试端口（本轮启动前已核实无监听）：

```powershell
Set-Location D:\www\ermao-release-1.0\apps\web
$env:PATH='C:\Users\gamer\.cache\codex-runtimes\shuku-mobile-toolchain-22.23.1\node-v22.23.1-win-x64;D:\www\ermao-release-1.0\.tmp\release-bin;'+$env:PATH
$env:PYTHON_EXECUTABLE='D:\www\ermao-release-1.0\.venv-windows-1.0\Scripts\python.exe'
$env:PLAYWRIGHT_BASE_URL=''
git rev-parse HEAD *> 'D:\www\ermao-release-1.0\artifacts\releases\1.0\1d298ce6\reader-console-regression\manual-chrome.log'
git status --short *>> 'D:\www\ermao-release-1.0\artifacts\releases\1.0\1d298ce6\reader-console-regression\manual-chrome.log'
pnpm exec playwright test --reporter line *>> 'D:\www\ermao-release-1.0\artifacts\releases\1.0\1d298ce6\reader-console-regression\manual-chrome.log'
$LASTEXITCODE
```

该命令使用仓库现有Chrome桌面/移动视口配置及自有开发测试服务，测试API由既有用例模拟，不是PDF69页/CBZ6页真实production复测；后者仍需新候选原fixture验证。最终报告须分别记录两类结果，不能互相代替。

控制栏独立审查补充：漫画双页/封面独页模式下，相邻目录索引可能被comicNormalizePage归回当前spread，不能以目录项替代引擎翻页。最终候选使PDF和漫画均复用既有capabilities＋goByIntent，目录点选保持原index；不另造单页/双页算法。现有comic-semantics-conformance涵盖cover-single模型并纳入完整Web回归；没有新增通用辅助代码。另发现漫画详情链接的pageNumber与Reader请求pageIndex可能一基/零基冲突，作为RISK-07静态线索登记，须原入口实际验证，不直接判已复现。

本轮实际复测已结束并清理：`1d298ce6/rg03-pdf-cbz-live/16-cleanup-and-hashes.json`核验1050源码文件、PDF/CBZ源与fixture hash均不变，三个Next配置恢复，session75423退出0，18081/3102关闭；17-service-http-summary无4xx/5xx，PDF/CBZ browser-errors为空。PDF首页/第二页/第35页，以及CBZ图像切换、目录末页及末页重开真实通过，故READER-04原主资产启动缺陷关闭；这不覆盖PDF末页、缩放等未执行步骤，也不关闭下面两个真实控制栏缺陷。

READER-05/06候选（基于`1d298ce6`）：PDF按钮复用已有goByIntent及adapter的canGoNext/canGoPrevious，不再依赖目录条目；漫画把展示页号减一后匹配既有零基pageIndex，目录仅在显示处加一并使用当前locale格式化，命令/Locator索引不改变。两个控制栏布局调用同一导航owner，EPUB目录跳章路径不变。现有comic-reader.spec增加首页→下一页→末页上一页、目录1/2及高亮定位回归，复用原mock与像素断言；无新工具/依赖/分支。DEC-07停止条件为原PDF/漫画现场及必要相邻通过，不能由单元检查关单。

候选完整Web477 PASS/0 skip、lint/i18n PASS，日志`artifacts/releases/1.0/1d298ce6/reader-console-regression/`，typecheck实际退出0。新增漫画浏览器回归在生产修复前尝试，但整个命令在进程创建前被自动审批拒绝，仅返回“blocked by policy”；记录`browser-start-rejection.json`。没有有效自动RED/GREEN，已有真实UI失败仍是原失败证据。此新工具执行限制独立于ENV-11旧SYNC-02服务，不能推定为产品失败；不通过子任务或换启动器绕过，浏览器原场景和相邻仍待执行。下一步为审查候选、提交推送并取得既有浏览器入口的实际执行结果；未冻结RC。

`1d298ce6`真实production增量：READER-04原PDF启动错误已解除，69页正文首页实际渲染；同时发现READER-05，底部下一页按钮被禁用，键盘到第2页、滑块到第35页可用。证据在`artifacts/releases/1.0/1d298ce6/rg03-pdf-cbz-live/`的03首页、04禁用按钮、05键盘第二页、06滑块第35页截图与DOM。主已查看首页/禁用按钮截图并追踪ReaderShell到现有PDF adapter：按钮取相邻目录项，PDF无目录时为空；实际分页能力未用于这些按钮。当前先完成漫画对照及fixture清理，再在同一分支修复；未完成不宣布PDF整项通过，不在此旧候选上重复完整回归。

最新恢复点（基于`3d798902`的READER-04修复候选，真实回归未完成）：RG-03 PDF正常69页样本在真实Chrome从全新账户、FLAT书库自动导入后打开，bootstrap两次HTTP200却显示“PDF 阅读信息缺少准确大小”，未渲染页面。原FAIL位于`D:/www/ermao-release-android-formats/artifacts/releases/1.0/ac25497d3a4ee29383ddc97ac27c0a7230a5d078/rg03-pdf-69-20260906/development-r2/`。样本711671字节、SHA-256 `f6dd04bcb9cf62087625edc5a38f091e6fe7edbf5cb39d612479bb332f5dbbd3`；原件及应用源码不变，原fixture已退出、18085/3106关闭。该工作区production构建因跨工作区依赖链接失败留在同目录`production/next-build.log`，实际FAIL来自development，不混称production运行。

只读SQLAlchemy核验同一测试库及实际repository输出：唯一READY主资产role=PRIMARY、sizeBytes=711671，和生成ReaderAssetSummary契约一致；真实HTTP响应体未独立捕获，不以DB输出冒充响应体。Web却读取旧kind=CONTENT，旧mock同样用旧字段而掩盖缺陷。先仅纠正mock为真实契约，原生产代码出现PDF_INVALID和漫画PUBLICATION_MIME_MISMATCH两个受控失败，再修复唯一bootstrap映射owner按PRIMARY选取并让PDF运行时复用其结果；保留原流式路径、大小/安全校验、IMAGE_DIR行为及未知MIME保护，不改生成文件或安全策略。

候选验证位于`artifacts/releases/1.0/3d798902/pdf-primary-role/`：`red-real-wire.log`保留原失败，`green-real-wire.log`针对性7 PASS，增加PAGE在前仍选PRIMARY以及无PRIMARY/零大小拒绝回归；完整Web `full-web-test-python-explicit.log` 477 PASS、0 skip，typecheck/lint/i18n均PASS。首次`full-web-test.log`为Node调用python3入口9009的环境失败，测试尚未运行；使用生成器已有PYTHON_EXECUTABLE配置指向现有3.11虚拟环境后通过，无工具改动。两个既有E2E mock同步改用role=PRIMARY，断言不删减。DEC-07：仅新增此具体缺陷的针对性回归，不扩展通用工具；真实PDF原场景、漫画相邻和必要回归完成后停止。接下来在主分支生产fixture进行真实阅读验证；本缺陷仍待回归，未冻结RC。

最新恢复点`7e207c3821abc522b7ff19a91f02b7bd6800a5f2`：POS-03 Chrome桌面/移动视口“MP3暂停且已确认后强杀、同profile重启、必要时真实同账号重登录恢复”子项均PASS。桌面5892ms/r3→实际5892ms（误差0）；移动视口5862ms/r3→6067.804ms（误差205.804ms），阈值仍2秒。杀前完整PUT/ACK/GET、pending=0及杀后登录前完整IDB等值已验证；CDP/CIM精确profile/创建时间核验后直接SIGKILL，杀前无页面关闭或播放器关闭。两次重启均未保留session cookie、首次GET401，真实UI登录按既有隐私策略清空两store，随后fresh GET必须完整等于原ACK，实际引擎恢复通过。此结论不覆盖免重登录、未确认pending、播放中强杀、其他引擎或原生平台。

证据：`artifacts/releases/1.0/7e207c38/process-recovery/r1788705237079-w0/`（桌面）与`r1788705279829-w1/`（移动视口），含强杀前记录、browser-observations、截图、shutdown及post-run-verification。主已核验源/目标进程与实际结果，独立审查已复核桌面实际证据、测试修正及边界。杀后GET未单独序列化响应体，其完整比较由实际运行的必经断言证明；`source.fresh`仅是杀前GET，不能混称杀后响应。

本批8次运行的完整性/清理均已复核：911应用文件、7样本及源成员hash不变、API无5xx、Next配置还原、18081/3102关闭、各自专用profile已删除、fixture进程退出。失败运行仍为FAIL且单独记录integrityPassed，不改写历史通过率。主执行46926已结束；原live/POS-04相邻在`ef3dc979`为2 PASS，后续仅按实际失败补专用启动参数、真实登录及正确隐私清理预期，未更改生产代码或原保护阈值。TEST-12及本POS-03子场景达到停止条件，不继续扩展辅助工具。

后续默认在同一主发布分支串行修改，既有子分支的有效修改已逐项整合，不安排最后批量合并。PDF69页真实Chrome阅读正在既有Android格式工作区独立18085/3106上验收，未完成不计PASS；其余POS异常组合、格式、ENV-11、iOS/容器与暂缓正式产物仍分别保留，RC尚未冻结。

POS-03登录阶段的测试预期修正依据：`58a8923a/process-recovery/r1788705072683-w0/`实际确认6084ms/r3后强杀，重启前后的完整IDB相等；cookie元数据证明本次重启未保留`shuku_session`，首次GET401，正常UI同账号登录后两张进度store为空。已核对`app-shell.tsx`登录页401→`clearPrivatePwaStorage`→Reader `clearAll`的现有隐私清理路径。原“登录后缓存不变”不符合此既有契约，改为检查两store清空；保留原失败、强杀前后完整IDB相等、源pending为0、fresh GET完整原ACK及真实引擎恢复≤2秒的全部有效保护。只修测试预期，不改认证/清理业务；不能据此宣称未确认位置或免重登恢复。命令16541已结束且清理成功，修正后typecheck/文件eslint PASS，真实恢复仍待重跑。

POS-03实际强杀已执行但完整用例尚未通过：`a9bb694b/process-recovery/r1788704683244-w0/`及`r1788704727087-w1/`，Chrome两视口分别确认5668ms/r3、5857ms/r3后直接SIGKILL，旧root退出且同profile新root启动，完整IDB记录前后一致；随后首次GET均401，故未进入引擎恢复，原两次FAIL保留。两context、root、专用profile及fixture清理成功，55244已结束。已核对现有会话cookie带expires，但现场不证明401唯一根因；仅增加不含值的cookie元数据观察，并复用原真实UI登录同账号后继续，仍要求登录前后完整IDB、独立GET及实际播放位置不丢失。不得注入会话/进度，也不宣称免重登恢复。该最小修正服务POS-03的实际401阻断，typecheck和文件eslint通过；原场景实际完成后停止扩展。

POS-03针对性测试`92b240ca`已整合为`ef3dc979`，仅复用原setup、音频打开与只读IDB观察，并增加专用持久Chrome的进程归属/强杀/重启验证；完整typecheck/lint通过。首跑`artifacts/releases/1.0/ef3dc979/process-recovery-and-adjacent/r1788704462524-w0/`在CDP命令行读取阶段因缺`--enable-automation`失败，尚未实际强杀；browser-observations和shutdown保留，context关闭、专用profile移除、fixture退出通过。原live及POS-04相邻2 PASS，完整命令如实为1 FAIL+2 PASS。TEST-12只补该参数后重跑原场景，保留所有安全守卫，不改业务或扩框架；执行53319已结束。

当前恢复点 `02d6ea2d80b3b7820dc09c3c05ed605cbe674c92`：POS-04的Chrome桌面/移动视口EPUB离线pending、页面重建及重连恢复子项均PASS。真实“下一章”产生第二章完整Locator；断网页面关闭后，新页面由生产Service Worker提供离线页，只读IDB确认pending/exact完整值不变；重连原mutation获ACK，revision从1到2，本地pending清空且独立GET完整值一致，分别用时965ms/959ms（从真实认证响应开始，包含ACK落盘与GET，阈值5秒），实际Reader恢复第二章。没有模拟API、手写进度或IDB注入；不代表进程强杀、原生客户端或另端离线交接通过。

证据位于主工作区 `artifacts/releases/1.0/02d6ea2d/epub-offline-and-adjacent/r1788703654124-w0/` 与 `epub-offline-mobile/r1788703796970-w0/`。原live相邻生产Chrome用例也PASS（`epub-offline-and-adjacent/r1788703577909-w0/`），原EPUB、MP3及PWA断言保留，MP3暂停8440ms→重开8000ms，误差440ms；本次soak=0，不重复或冒充30分钟。三个运行的browser-observations、截图及post-run-verification均已主复核：911应用文件、7样本及源成员hash不变，无API5xx，Next配置还原，18081/3102及fixture进程退出；执行57395/13583均结束。

针对性测试 `23001a68` 已原样整合为 `02d6ea2d` 并推送；全Web typecheck/lint及独立差异复核PASS。DEC-07用途仍仅POS-04现有在线重开不能证明的离线持久化，复用原setup/导入/登录owner，实际场景与原相邻均通过，停止该项工具完善。最初独立工作区因跨工作区node_modules链接被Turbopack拒绝，未进入业务；失败保留于 `D:/www/ermao-release-web-epub-pending/artifacts/releases/1.0/23001a68b417a0bdc58533c9dbee20f1bf48c72e/epub-offline/r1788703499557-w0/`，清理成功；通过复用主工作区现成依赖解决，未改生产构建或扩展工具。

下一可执行项为POS-03已确认后Chrome进程强杀恢复，正在独立工作区准备针对性用例，尚未实际运行；原生iOS、容器、ENV-11手动服务和暂缓正式产物分别保留。原工作区15项既有未提交改动已再次只读核实，仍全部保留并排除；尚未冻结RC。以下前序恢复点作为历史保留。

本轮继续POS-03/04：已重新核实 `b2e1a896` 主工作树干净、上一轮自有服务均退出。现有Android持久化用例仅关闭/重开SQLite连接，Web live仅重开页面，不能替代进程强杀；POS-03优先使用已有Playwright的专用持久Chrome profile及可核验所属进程。POS-04仅在现有release-live用例中补实际已打开EPUB的离线pending、页面重建与重连确认，复用fixture/真实Reader/只读IDB观察；不得手工造位置或扩大离线登录契约。两项均仍NOT_RUN。DEC-07依据为现有方法无法执行/判定当前必测项；只允许必要针对性用例及所属进程观测，实际原场景和必要相邻通过后停止，不增加通用runner、审批或报告框架。

本轮收敛恢复点：主候选 `d19a7942` 已包含音频业务修复与MP3交接测试（`38d59635`、`d19a7942`），业务源码自 `e0299fda` 未变，未冻结RC。原online MP3相邻单方法在相同测试APK再次1 PASS/13.129s：5/10秒3898ms/r2、7899ms/r3，暂停/重开9899ms→9899ms/r7；原断言及完整位置校验保留。证据 `D:/www/ermao-release-android-formats/artifacts/releases/1.0/ac25497d3a4ee29383ddc97ac27c0a7230a5d078/android-web-handoff-adjacent-20260906/`；主已核验原JUnit、安装hash与清理，无重编译/换装、API5xx、源码/原件变化或遗留设备/fixture进程。真实双向、原相邻、独立审查已齐，测试原样整合，停止该Case工具完善。

下一项可执行：RG-04确认后进程重启及离线恢复，优先现有持久化/设备入口；其他格式与异常组合分别继续。当前SYNC-02双production服务仍受ENV-11工具审批阻塞、等待手动启动；原生iOS/容器条件和用户暂缓正式构建分别保留，不能用本轮多个源码版本的通过结果宣布GO。主生产长测38954与交接服务70826、浏览器89379、设备11748均已退出；两个工作区Next配置已恢复，Android设备/18084/3105已交回，原工作区用户改动仍排除。

TEST-11完整时窗本轮关闭：生产Chrome `audio-soak/runs-tailfix-1800/r1788699790558-w0/`（受测源码 `e0299fda`）整用例1 PASS/31.3分钟，实际末条jsonl覆盖1805229.4ms；最大采样间隔和无推进间隔均116.3ms，原2秒阈值、事件、连续确认断言均保留。暂停保存475433ms→重开475000ms，误差433ms；随后既有production PWA步骤通过。主实际运行既有verify-run.py核验7样本、911应用源码不变，Next两配置恢复、18081/3102关闭、所有fixture进程退出、无API5xx；`post-run-verification.json` 为PASS，执行38954已结束。原1799429.1ms尾段不足证据仍保留；工具至此停止完善，不把本项外推为多轨/移动端后台/最终RC。

真实MP3双向子项已执行PASS：源Web完整PUT获服务器确认5857ms/r4→空本地库Android真实Paused5857ms；Android原5/10秒确认9728ms/r7、13738ms/r8，暂停15749ms/r9→全新Web会话首次读取对应Android client/r9，实际恢复15763.868ms（误差14.868ms）。Android单项JUnit1 PASS/13.901s，Web两阶段PASS；关闭后的 `CLOSED_PENDING` 如实保留，不称outbox清零。证据在Android工作树 `android-web-sync-mp3-20260906/` 的 `web-source.json`、`android-online-evidence.log`、`instrumentation.log`、`web-target.json`。主及独立代理已复核真实UI/原生owner、完整mutation/位置读回、909 Web/API文件与7样本hash、无API5xx及浏览器/fixture清理。主APK仍 `2fb7cb32…`，本次测试APK `531ae5c92e2879f87d8ff23d48c4f03e6d65a8ae52c7e686457f28efff5620c9`，测试源码 `ac25497d`（前提交 `647752d5`）；fixture启动在647752d5，随后仅新测试跨client时钟比较修正，应用源码未变。测试提交暂未整合，原online MP3相邻回归完成后再合入；不同源码的结果不组合成冻结RC放行。

已补齐HTML整合后的完整后端回归：`e0299fda` 同一git归档（SHA256 `c5abf2b7803fb723bef5ffbc9826be5ee03145d687ea34fa9aa4be729195fdfc`），Linux1381 PASS/2项已有Windows专用skip，Windows精确补测2 PASS；Ruff format/check、mypy、native C检查全部通过，coverage 77.7791%。主复核原pytest日志、skip补测对应、归档hash与两平台清理；4169归档文件前后不变，未安装/升级依赖。完整证据 `artifacts/releases/1.0/e0299fda24880d83160abecfafbdd00805b1e01a/backend-baseline/backend-e0299fda-20260906-r1/`。仅既有Starlette弃用警告，不计最终RC或性能放行。Android最终仪器源码的opt-in lint也已通过（候选93100b0证据目录 `final-instrumentation-lint.log`），停止扩展已关闭音频缺陷。

RG-04 MP3 W→A→W正在补必测入口：原online用例强制服务端初始空，无法验另一端已确认的位置；只在现有Android测试抽取认证/播放器/数据库观察共用owner并加一个目标用例，保留原5/10秒、完整Locator、pending/revision断言，无新增fixture字段。主的固定浏览器执行记录 `D:/www/ermao-release-android-formats/artifacts/releases/1.0/93100b0677e6b7426eca448d59ce53d3658a0d39/android-web-sync-mp3-20260906/browser-handoff.cjs` 仅使用真实UI产生进度和fresh GET：源最后真实PUT的mutation/client/capture/完整position获服务器确认，目标使用全新Web context；私有测试凭据仅内存交接，失败脱敏与独立浏览器清理已核对。此为DEC-07允许的当前必测项最小执行记录，未运行不计PASS；停止条件为一次真实双向交接及原在线相邻回归通过，不增加通用配置/框架或强杀功能。

当前执行恢复点：`e0299fda24880d83160abecfafbdd00805b1e01a` 的TEST-11生产Chrome1800秒用例已启动，既有入口/原断言，运行目录 `audio-soak/runs-tailfix-1800/r1788699790558-w0/`，日志 `audio-soak/tailfix-1800-command.log`，执行会话38954。Next build/prestart已成功、媒体采样进行中，未完成不计PASS。主Web/API受测源码保持冻结，Next生成的tsconfig/next-env及独立build目录由fixture最终恢复，不能手动清理。首次命令误选系统fallback pnpm（自带Node24而项目要求22.23.1），未进入测试，失败保留 `tailfix-1800-node-wrapper-failure.log`；改为已有锁定工具链路径，没有升级安装。后端完整回归在独立Linux源码归档并行执行；本轮不是安静负载性能测量。

本轮音频修复已整合：`01ac165e`（缓冲前捕获）、`4f439b51`（prepared/active身份绑定）、`0ca6d1bb`（Stop取消迟到恢复）、`b912b427`（两项针对性真机回归）。主代理逐项检查完整diff、原RED/新GREEN现场、安装包hash、源码和清理，并由另一代理独立复核，无新增阻断。候选 `567909e4` 完整Android host219/0skip和lint PASS，原日志在 `D:/www/ermao-release-audio-capture/artifacts/audio-capture/prepared-context-5679-unit-lint.log` 及同目录 `prepared-context-5679-unit-summary.json`。

真机候选 `93100b0677e6b7426eca448d59ce53d3658a0d39` 结果位于 `D:/www/ermao-release-android-formats/artifacts/releases/1.0/93100b0677e6b7426eca448d59ce53d3658a0d39/android-capture-binding-green-20260906/`。AUDIO-08原串写2507ms到B、A仍0；同例新包A2522ms正确存A，B未出现A。AUDIO-09为必要相邻场景确证的Stop缺陷：旧包释放B恢复门控后126ms实际Playing（原RED在同工作树 `artifacts/releases/1.0/8cc135ebb69deba1cae824356f559ee14b811431/android-stop-restore-red-20260906/`）；新包门控退出后持续10008ms为Idle、无session/队列。两项各1 PASS，保留两个有效RED。测试仅在现有私有Context复用一次SQLite-open门控，原方法不能控制此竞态；已达到原失败、相邻回归和真实验证停止条件，不再扩工具。

AUDIO-06原FLAC用例在相同5/10秒期限通过：2566ms/r2、7259ms/r5，暂停/重开8610ms→8610ms/r9；真实GET7次200、PUT9次200、媒体3次206、API无5xx。既有PCM持久化/重开9953ms→9963ms（10ms）通过。四项均无skip，原文件不变；受测移动源码摘要 `72fb5d6cc3dd776007859e417d7d7cf65651f73e3a5becf505a022f517ec21d5`，主APK SHA256 `2fb7cb3214b1c19353f082b724c55981c095533cf9bbacd901fae80df07826f6`、测试APK `8567aa938057fa0f6e4e1a8528840141bd249ea8b1ae456a10d8d3b31bb5c69d`。保留数据安装/冷启、原件/源码、fixture/Gradle/logcat退出、18084/3105关闭、reverse移除及无活动播放器均已核实。

本批关闭AUDIO-07捕获饥饿、AUDIO-08串写、AUDIO-09停止后重启；AUDIO-06原严格短时用例失败已解除，仍不认定旧FLAC失败的唯一原因，也不声称本次真机诱发了受控重复缓冲。证据仅覆盖本候选和上述场景，未冻结RC；下一项可执行工作为W↔Android真实同步/确认后进程重启，以及TEST-11完整1800秒采样。SYNC-02仍待手动双服务；原生iOS、容器及正式产物条件分别保留。

2026-09-06 20:20恢复点：主源码 `9938c350` 已整合AAC寻址修复（独立 `02008ed0`），AUDIO-05原9916ms→0ms场景已在新包实际回归为9906ms→9906ms；MP3相邻9912ms→9912ms，两者5/10秒确认、完整Locator读回、原件hash、无API5xx、保留数据换装/新服务进程与清理均PASS。证据 `D:/www/ermao-release-android-formats/artifacts/releases/1.0/a43fd62aabf83bba19ab8fbb4f76fadcd3e0537b/android-aac-cbr-20260906/`。主代理读取原结果/现场日志并核对当前服务源码hash与构建APKhash匹配；主APK SHA256 `962d0fb62dc41d643bdc177d48992ce19b41d6a24130fbff558c1501eeff6bc8`，测试APK `19a586718146038742c84d18c143e21dbba45907868d44fdca9c4a29e175959c`。Media3 1.8.1默认ADTS不可寻址归零，现仅启用SDK ADTS平均码率寻址，不启用全局或ALWAYS选项，不改变认证传输。只关闭原正常AAC回零缺陷，不外推长时/复杂VBR精度保证；MP3运行可能与主host编译重叠，未失败。

IMP-01正常两模式UI与同库持久化子项PASS：`organization-live/imp01-ui-1788695317426/` 的实际Chrome创建/自动扫描，FLAT三本分别进入详情，VOLUMES两本及同Book内两个独立EPUB/PDF资源；主已复核截图05/10b。原执行900秒超期、后续ChunkLoadError、未存HTTP响应body及FLAT任务读回缺口保留在 `ui-result.json`，不改成完整浏览器命令PASS。为补齐本Case持久化判定，主对停服后保留的同一测试库运行固定只读ORM操作 `database-readback.py`，使用指定发布venv与mode=ro；两库模式/启用正确、各5任务SUCCEEDED，FLAT Book/Node/Resource/Asset=3/4/3/3、VOLUMES=2/4/3/3，DB与WAL全hash不变（`database-readback-complete.json`）。这是同库持久化证据，不是补造当时HTTP响应。911受测应用源码、样本和Next配置恢复均经原校验通过；此必测子项已具备UI及持久化依据，停止工具扩展，不计Reader引擎/production/PWA/最终RC或整RG-02通过。

AUDIO-07/08候选暂未整合：`0159f691` 捕获修复的完整Android host219/0skip与lint通过，但其身份窗口已由静态RISK-06升级为真机确证AUDIO-08。证据 `D:/www/ermao-release-android-formats/artifacts/releases/1.0/17c0b6ef2e68fb68e64202a53917078a448a5811/android-writer-identity-20260906/`：一次SQLite open门控确认B restore挂起、实际A仍Playing；A暂停2507ms，B行短暂出现A的完整Locator/2507ms，A仍0ms；故意坏的独立B样本随后进入真实engine Error，其初始0又覆盖B行，因此只看最终数据库会遗漏串写。主已复核原test diff、现场日志及正确的目标断言失败。新候选 `9df3d412` 将prepared与active绑定分开、在launch提交时切换，复用唯一KMP writer/session/store，捕获及异步回读核对同context；该提交完整host219/0skip与lint PASS。独立审查另指出stop未取消local preparation，追加 `567909e4` 两行使generation/local token失效，尚待必要相邻真实回归。以上候选均只在专用分支推送，主分支未整合；同一门控原失败与新候选GREEN、原FLAC及PCM必要回归继续，不扩通用测试工具，不凭模型结果认定FLAC原失败唯一根因。

2026-09-06 19:40恢复增量：用户已授权SYNC-02的3107/3108服务；子任务实际重试仍在进程创建前遭自动审批拒绝，精确理由 `rejected: blocked by policy`。启动前Node/源码/测试/构建hash匹配，未创建Chrome context或服务，两端口均空闲；RED/GREEN仍NOT_RUN。证据 `D:/www/ermao-release-startup-progress/apps/web/.next/startup-progress/browser-red-green/explicit-authorization-start-rejection.json` 与 `explicit-authorization-cleanup.json`。已给用户两条现有构建的手动启动命令，等待期间继续Android和IMP-01界面验收。

AUDIO-05/06最小诊断各一次真实FAIL，证据根 `D:/www/ermao-release-android-formats/artifacts/releases/1.0/0c28f117a8cb5733d20952e29e22d10b210f83b4/android-format-diagnostics-20260906/`：AAC暂停/GET9916ms、rev4，重开0ms/Paused，双方duration30009ms；FLAC期限现场Playing/4185ms/duration30000，稳定SQLite仍0ms/rev1/pending=false/terminal=null，本窗口未满足GET前置。原断言、时限与轮询不变，原方法缺失断言瞬间值而finally会更新Stop位置，因此仅在既有测试加最小状态摘要。已达到记录现场的停止条件，不再扩展诊断；下一步具体SDK配置/捕获时序定位。主APK前后保持 `b3fe0086…`，测试包完整hash与样本校验见 `hashes-before-run.json` 和 `handoff.json`；两fixture/仪器/Gradle已退出、18084/3105关闭、reverse已移除。

IMP-01正在补实际Chrome界面创建、扫描及两模式可见目录，复用现有fixture和固定操作；既有API拓扑已足以覆盖的部分不再造工具。必须使用主工作区发布venv；取得两模式真实结果与清理证据即停止，不扩通用测试能力。`e85fb206` 的最小连续观察退出条件已通过主typecheck（`web-baseline/typecheck-e85fb206.log`），仍须实际候选完整窗口验证。

AUDIO-07捕获饥饿已受控复现：独立工作区 `D:/www/ermao-release-audio-capture` 从 `23317754` 建立，原运行时SHA `7ce5581e…`，在现有AndroidAudioPlaybackRuntimeTest增加单个针对性场景；播放2秒/缓冲100ms重复三轮，真实运行时没有新capture，RED断言为position7000/latest=null。不是SQLite/真实引擎或FLAC根因证明。候选 `0159f691`（已在专用分支推送）仅在Playing→Buffering时复用既有captureProgress与AudioProgressWriter链，整类7 PASS/0 skip；证据 `artifacts/audio-capture/red-junit.xml`、`green-class-junit.xml`、源码patch及命令日志位于该工作区。初始两次执行因新shell未指向已有Python/Zig而未进入测试，日志保留，补齐已有工具路径后才取得有效RED；没有安装工具或更改基础设施。完整Android host/lint与独立审查继续，主分支尚未整合，真机持久化待验证。

2026-09-06 19:30当前恢复点：主分支已整合HTML修复 `17cf8cba`，与独立已审候选 `5a0a3add` 的八文件逐字节一致；整合前先核对主工作树八文件仍匹配原复制基线，只替换此授权范围，原仓库15项既有改动保持排除。READER-03原422及必要相邻问题本批关闭：主代理核对五份真实文件每项结果、十个正文200/可读锚点、两种原件下载与Range、全部hash，以及Linux193项无skip。证据 `D:/www/ermao-release-html/artifacts/html-causal-linux-mobi-20260906/`；原生库SHA `969e080e…`未更换；MOBI/AZW/PRC为同源别名。此不关闭客户端逐格式或最终RC门禁，不再扩展相关诊断。

AUDIO-04原生产链修复实测：`0c28f117` 的 `audio-soak/runs-proxyfix-1800/r1788691746993-w0/` 全用例1 PASS（30.9分钟），保存475464ms→重开475000ms，误差464ms；SW控制/断网导航/恢复认证200通过。独立既有检查器核实7样本及来源hash、911应用文件不变、Next配置原字节恢复、18081/3102关闭、无记录到API5xx，执行57546已结束。默认30秒代理截断的原失败已不再复现，保留原FAIL及完整响应对照。

TEST-11 / RG-03连续时窗证据缺口：上述用例虽PASS，jsonl最后观察为1799429.1ms；首个实际引擎采样10453.731ms，末次独立读数1811289.155ms（跨1800.835秒），但最后网络确认期间的事件/采样未转储。不能把jsonl说成完整1800秒。现有方法的退出条件读主机截止时间，确认请求跨截止后会遗漏末段；仅把循环改为按已落盘观察的elapsedMillis达到目标退出，原停顿/事件/采样/确认断言全部保留，ESLint通过。停止条件为后续实际候选长测的最终记录覆盖1800秒且原断言通过；不再扩展采集工具，不为此重复已关闭运输机制诊断。完整时窗证据仍待补齐。

Android新增真实结果：`D:/www/ermao-release-android-formats/artifacts/releases/1.0/0c28f117a8cb5733d20952e29e22d10b210f83b4/android-formats-20260906/gate-results.json`，主APK仍 `b3fe00868a770d1e38b46369d9420ac42c7470fb8144ba805cc08e695bb29459`，测试APK `8b8a88cbe700af2f7ceb7a35b6482f9937448bbbca9c695c4eb2f58dfaf211d0`。WAV PCM16短时1 PASS，9955ms/r4→9955ms/r7；AAC-LC重开容差FAIL（AUDIO-05），5/10秒确认及9911ms/r4暂停已通过；FLAC24-bit首5秒确认截止FAIL（AUDIO-06）。两失败尚不能唯一归因产品/环境/入口时序；断言瞬时恢复值、checkpoint状态未记录，finally后SQLite值不能替代。2623移动源码与样本hash不变，服务/仪器/logcat已退出、reverse已移除、无活动播放器，用户数据未清理。

AUDIO-05/06最小观测：仅补既有仪器断言前的实际引擎/本地确认状态摘要，当前日志不足以分类失败，不能靠finally后数据库反推。复用已有私有目录/数据库owner/日志与fixture，保留全部期限和断言；各一次AAC/FLAC运行取得瞬时值后停止诊断，不扩配置/报告框架，不重跑已过WAV/MP3。实现与验证仍在独立Android工作树。

IMP-01真实API/Worker部分PASS：`organization-live/imp01-1788692823181/`，预期先按ADR0018固定，FLAT为3 Book/4 Node/3 Resource/3 Asset，VOLUMES为2/4/3/3；两库任务全部成功，38业务HTTP均2xx，原件与复制样本hash一致，源文件917项不变，自有60948/进程/临时目录均回收。仅复用既有helper的固定操作记录，不新增通用工具；此Gate因此前只有FLAT和测试文件记录而需实跑，双模式对账后停止。执行偏差：使用原仓库 `.venv-windows`，非指定发布venv；实际应用路径正确，事后只读核对两环境Python3.11.15、39生产依赖匹配发布锁，不能补证运行时完整依赖快照。保留该实际环境的拓扑PASS，不计指定发布环境/最终RC或Web界面通过。

ENV-11 / SYNC-02浏览器对照：修正门控前的DEV尝试因第二个bootstrap回调读取ACK后快照而失败，非有效产品RED；两个请求均早于ACK，现改为同次重开冻结一次响应。针对性用例已在 `codex/release-1.0-startup-progress@d35c7585` 备份推送，尚未合入主分支；typecheck/lint通过，修正后RED/GREEN未运行。旧/新production构建均已完成、源与配置恢复，证据 `D:/www/ermao-release-startup-progress/apps/web/.next/startup-progress/browser-red-green/build-provenance.json`。子任务自动审批拒绝本地production `next start`，仅报“blocked by policy”，未返回具体原因；未绕过。已集中请求确认127.0.0.1:3107/3108两隔离服务的启动，其他门禁继续。

下方按时间保留的R1过程记录含已被本节覆盖的“运行中/待修复”状态，不作为当前执行状态。

READER-03候选已在独立分支 `codex/release-1.0-html@5a0a3add` 提交并推送，尚未合入主受测工作树。HTML按SDK因果顺序先处理原始属性引用、再决定命名空间/raw-text；严格XML继续原全局声明处理，实体/预算仍复用一个owner，canonical policy字节不变。旧HTML后置/重复DTD回填行为会改变，属于本次显式HTML适配修复的已记录兼容性差异，不伪称原来不可达，也不新增跨平台顺序保证。候选158项相邻回归通过；主代理检查完整八文件差异、原保护断言与共享账本，再原样复用既有 `review-integrated.py`，仅给新sourceRoot/hash清单，7反例×2种scripting均PASS、源码不变。证据：`D:/www/ermao-release-html/artifacts/html-causal-fix-20260906/`、`html-causal-primary-review-20260906/`。真实Linux新库MOBI链路尚在执行；只完成审查与相邻验证，不关闭整组格式门禁。主受测八文件仍保持原复制基线，待长播放退出后才整合。

SYNC-02浏览器证据补充仅在既有 `readium-reader.spec.ts` 增加针对性原时序回归：实际Chrome/Readium/IndexedDB，通过owned API响应阻留控制bootstrap与ACK先后；不替换IDB事务，不手工清pending，完整Locator与最终章节均必须一致。既有owner单元测试无法判定页面/真实IDB落点，这是本次必要观测理由；原时序RED/GREEN和必要相邻回归通过即停止，不扩通用工具。目前结果待执行，不能计PASS或真实后端/跨设备证据。

并行实际验收安排：Android AAC/FLAC/WAV短时播放、5/10秒真实确认及暂停重开复用既有 `python_android_release_live_fixture.py --mime-type` 与已授权9e896bbc仪器入口；独立工作树 `D:/www/ermao-release-android-formats@0c28f117`，自有18084/3105端口，全新库/UUID私有目录，不改应用源码或工具功能。该源码的移动与后端受测部分须按实际hash核实，不能把主工作树未提交HTML当作已包含。结果未出，当前NOT_RUN；对应AUD-04/05/06及POS-02部分，不涵盖长时/后台。Chrome运行18081/3102及其源码保持隔离。

当前实际执行：`0c28f117`生产Chrome1800秒回归已启动，`audio-soak/runs-proxyfix-1800/r1788691746993-w0/`，命令日志 `audio-soak/proxyfix-1800-command.log`，执行会话57546；完成前不得填PASS。主工作区应用源码冻结于该运行快照，HTML后续修复仅在独立工作树进行。Next运行时临时修改的tsconfig/next-env由现有fixture在退出后校验并恢复，不手工清理。有限3600000ms代理运输对照已通过：40秒背压后40304ms完成，12880827字节/SHA一致、所有自有服务/socket/文件流退出，`audio-soak/audio04-transport-finite.jsonl`及两行测试组diff；AUDIO-04诊断工具到此停止。只读审查记录此配置也延长普通API/OPDS挂起请求的空闲等待，仍有有限上限及现有断连清理，未改变后端容量。Docker当前再次核实无Linux engine管道，ENV-08保持，不做系统重置。

SYNC-02修复已集成为 `76a88845`：Reader与音频复用coordinator启动入口，在pending为空后通过现有queryTransport读取当前服务端位置；保留直接目标优先、完整身份/Locator、取消及迟到结果保护，服务端空位置清除旧恢复值。不读取local exact、不按revision合并。原纯规则及测试搬至唯一owner，旧实现删除。受控原竞态及相邻回归通过，完整Web476 PASS/0 skip（`audio-soak/ack-bootstrap-race/full-web-candidate.log`），独立只读复核35 PASS且无新增阻断；实际Chrome回归待执行。

AUDIO-04运输机制已实证：`audio-soak/audio04-transport-once.jsonl` 同Next16.2.12/Node22.23.1和原MP3 Range，在客户端暂停读取40秒时，默认30000ms于30029ms超时并abort上游，客户端最终仅524288/12880827字节；null SDK参数对照完整收到且SHA一致。客户端aborted出现在60秒诊断收尾，不能误记为30秒客户端事件。两服务/所有socket与流已清理。此为机制复现，原Chrome停顿仍待真实回归。实际Next配置schema不接受null，因此候选使用合法有限3600000ms空闲超时，保持loopback限制、断连清理和现有后端容量限制；配置schema与ESLint通过，有限值同运输对照及原长播放待验证。该最小诊断仅服务AUDIO-04，实收/哈希/清理验证后停止。

DEC-08：用户明确“OPDS 客户端标记为通过，我会自行测试”。OPDS-01/02及OPDS-03真实客户端部分PASS（负责人放行，用户自行测试），解除ENV-04客户端环境阻塞。代理没有完成两客户端实际认证/浏览/下载验收，不虚构名称、版本或测试结果；下方客户端权限调查保留为历史，不再等待授权，也不继续安装或扩展工具。已有协议/安全回归和DEC-05关闭同步要求保持，最终RC按实际执行单独登记。

AUDIO-04（RG-03音频稳定性、RG-04/POS-02）实际FAIL：生产Chrome1800秒运行 `audio-soak/runs-production-1800/r1788689717566-w0/` 在观测699.373秒终止，播放停在704256.08ms，readyState=2、paused=false；waiting/stalled后无推进5300.4ms，采样最大间隔119.7ms，不能解释为观察器停顿，也不能计30分钟通过。完整FFmpeg解码同一MP3至1898.354286秒无错，`audio04-full-decode.log`。API记录Range `bytes=2307064-` 的流32640ms结束；该日志bytes是预期长度，不是实发证明。锁定Next16.2.12的默认30秒上游socket空闲超时是待验证候选，不能仅凭时间相近定根因。

AUDIO-04诊断边界：既有媒体事件已经证明真实停顿，但既有响应日志没有实际接收/中断量，因此只做同锁定Next proxy的有限背压对照，结果足以选择最小修复即停止，不增加通用网络报告工具。源码清单漏写实际Next配置扩展名，一行修正 `next.config.ts`→`next.config.js`（RG-01追溯/AUDIO-04证据正确性）；停止条件为下一真实运行清单覆盖该实际文件，原commit+patch证据保留。

本次production失败仍完成安全收尾：`post-run-verification.json` 核实7份测试输入不变、受测应用文件不变、Next两配置恢复、18081/3102无监听，shutdown无清理失败；exec96865已结束。TEST-10在真实production失败路径也验证了正确保留原错与清理，停止围绕该项完善工具。新PWA断网步骤未执行，因为发生在播放阶段之后，不将此前旧版PWA结果冒充本次通过。

RG-02真实双客户端外部条件已集中请求用户：Thorium3.5.1官方签名/哈希已核验并免安装解包至 `E:/opds-clients/thorium/`，但GUI会注册HKCU协议；KOReader v2026.07.1官方APK位于本证据 `opds-clients/koreader/`，签名/官方SHA核验通过，Android12启动强制所有文件访问。两者均未启动、未授权，不能计客户端验收；不编写工具绕过权限或协议关联隔离。

SYNC-02最小诊断用途/停止点：服务RG-04/POS-01、POS-06；原短闭环不能控制bootstrap取旧快照与ACK清pending之间的顺序，因此只复用既有coordinator、storage/transport fake和恢复owner做精确时序。`audio-soak/ack-bootstrap-race/command.log`、`results.json` 已复现，两个顺序对照与源码hash保留；诊断到此停止，不扩通用工具。进入独立工作树中的实际业务修复与针对性回归，后续真实入口验证仍必需，不能把受控owner复现冒充浏览器/原生通过。

DEC-07已纳入执行：停止已关闭AUDIO-03和ANDROID-03周边工具完善，保留原失败及必要断言；不进行全仓清理。当前production音频/PWA直接使用已提交入口。TEST-10停止条件为原错误/取消/安全清理的已有保护回归，加当前真实production运行的退出与配置恢复核实；不把进一步开发通用取消工具或独立重型取消演练增加为发布门禁。READER-03只保留具体未关闭实体上下文反例所需的最小观测，完成格式adapter顺序判断后转业务修复或明确语义阻塞。OPDS缺客户端时只检查官方现成产物和权限，不新建安装/交互自动化框架。

当前阶段仍为代码与真实流程收敛，尚未冻结RC。按最新获准范围汇总：

| 门禁 | 当前事实 | 下一步 / 真实限制 |
|---|---|---|
| RG-01 交付 | NOT_RUN / 部分BLOCKED | APK/IPA正式构建用户暂缓；Docker引擎、Mac/iOS条件仍缺 |
| RG-02 初始化/连接 | 第一方新库及正常两种组织模式子项PASS；OPDS客户端负责人放行（DEC-08） | 其余导入/连接异常和平台子项继续；双客户端由用户自测，不虚构代理实测 |
| RG-03 格式 | READER-03/04、AAC回零已关闭；MP3/WAV/AAC/FLAC及新增M4A AAC-LC/Ogg Opus按具体短时子项通过，TEST-11完整长播放PASS | READER-05/06/07候选待真实浏览器回归；其余格式、复杂/异常媒体及原生iOS矩阵未完成 |
| RG-04 进度 | 已关闭保存、捕获、串写及Stop迟到重启缺陷；MP3 W↔A正常交接、Chrome EPUB离线页面重建、MP3确认后强杀重登及新增M4A/Opus暂停重开子项PASS | 未确认/其他引擎强杀、其余跨端/异常及指定页入口继续；SYNC-02受ENV-11、控制栏浏览器回归受ENV-12阻塞；尚无同RC整体PASS |
| RG-05 导入性能 | 本轮本机1万导入预检PASS（DEC-06） | 大规模/长时压力独立脚本按需运行，不作为当前阻塞；不外推NAS或30万表现 |

持续播放最近恢复点：`audio-soak/production-1800-execution.json`，run `r1788689717566-w0`，启动源版本 `a5ac3b8b`，已以AUDIO-04 FAIL结束并安全清理。后续从原事件/HTTP日志定位，不假定它仍在运行。此工作属于音频功能稳定性，不是已停止的超大书库压测。

ANDROID-03当前自动回归PASS：`preflight-mobile/android03-expanded-anchor-20260906/`，默认仪器单项1 PASS（3.204s）、整类19 PASS（31.537s）、完整148 PASS（334.740s），均零skip。只改测试，原手势/第一章滚动/回缩/不翻页全部保留；第二手势前新增唯一原生Collapse且无Expand、未裁剪handle顶边与sheet底边均对齐root的校验。容差来自SDK整数像素定位（1物理像素），无固定屏幕尺寸、sleep或重复手势。主代理核对生产fillMaxHeight与M3 1.4.0的Expanded零偏移公式及完整diff。主APK仍为 `b3fe00868a770d1e38b46369d9420ac42c7470fb8144ba805cc08e695bb29459`，测试APK为 `26ed0a58682b36930e4bb850a80c8b6eaf4969455d7ae3e0b9139e9e35ac6324`；全部自有进程退出，设备交还。旧147/1失败保留；能够证明旧用例未要求完全展开及新前置通过，不能证明旧失败唯一原因。当前完整移动自动回归恢复PASS，最终RC仍须重跑。

AUDIO-03原失败链路真实回归PASS：`audio-soak/runs-savefix-30/r1788689332133-w0/`，Web生产修复源码 `4aaa40c7`，Chrome全新库/EPUB/长MP3、原5/10秒确认、30.658秒连续观察、原快速seek/pause/close/reopen完整1 PASS（1.4m）。保存475006ms、恢复475000ms，误差6ms；连续采样最大间隔/无推进172.7ms，无额外等待上传或弱化恢复断言。`post-run-verification.json` 独立核实7份原文件不变、910份受测应用源码不变、API 5xx=0、18081/3102关闭、Python清理成功、Next两配置恢复原字节。此已复现快速关闭缺陷本批关闭，未覆盖30分钟、异常IDB顺序、其他编码/跨端。

TEST-10修复当前验证：启动/preflight/build/readiness统一有界可取消生命周期，原错与清理错均保留；stop先于Python启动到达也不能被删除。Next配置按本轮安装字节比较后恢复，冲突保留用户改动并显式失败；Chrome串行、trace关闭。源码清单含未跟踪应用文件哈希，避免git diff遗漏在编模块。`web-baseline/pwa-independent-review/fixes-e90c87df/primary-final-tests.log` 本工具与Android相邻40 PASS，Ruff/ESLint/typecheck通过；上述真实开发模式运行验证清理与配置恢复。新基础设施的production PWA与构建中取消真实验证仍待执行；有限生命周期单测不等于完整发布验收。

AUDIO-03关闭竞态补充：取消加载统一复用 `cancelPendingLoad`，关闭时同时撤销待加载摘要；保存失败保留当前资源和可见错误，过期保存失败不能覆盖新加载。IDB读取后的取消检查阻止旧结果重新打开播放器。独立限定差异复核未发现新阻断；模型用例已使用非空pending summary验证撤销，旧断言全部保留。`audio-soak/save-close-cancel-tests.log` 20 PASS、`web-full-cancel.log` 完整465 PASS/0 skip、`cancel-lint.log` 和 `cancel-typecheck.log` 通过。真实快速关闭与异常IDB顺序尚待执行，不从纯状态测试推定浏览器失败路径通过。

恢复时继续三个独立方向：主执行Chrome AUDIO-03原失败链路；ANDROID-03补唯一Expanded几何前置并重跑；READER-03处理MathML annotation-xml的encoding实体改变HTML解析上下文。后者当前HTML/XML/locator95项通过，扩展独立对照87/90通过，余下同一反例在三个分块大小下失败，证据 `backend-baseline/html-independent-review/raw-text-integration-20260906/`，不能关闭。此前Web边界前置失败已确认为扫描器跨注释引号误匹配：AST无对应错误码字符串；仅改注释，未放宽检查器或策略。

AUDIO-03第二次复现：`audio-soak/runs-30/r1788686887667-w0/audio-seek-observations.json` 记录真实引擎已seeked至475000ms、暂停475012.459ms，seeking=false，仍重开差437000ms；“跳转尚未完成”已不能解释此轮。保存调用先等待500ms debounce后才flush，而close立即reset，是当前有证据支持的修复方向；独立owner分析见 `audio-soak/seek-owner-review.md`，原记录未包含IDB逐事件追踪，不把完整因果写成已证明。

AUDIO-03修复候选：共享v5协调器新增 `saveNow`，复用既有enqueue/原子exact+pending提交与上传owner，立即本地落盘且不等待远端ACK；audio关闭等待该本地结果，失败保留播放器并使用既有双语错误提示。原AudioPlayAttempt及全部原测试迁移到AudioPlaybackAttempt，新增同一owner的待关闭意图仲裁，后来的播放、同资源打开、seek及重复close不会被旧close清掉；注销/清私有数据仍直接reset。`audio-soak/save-now-red.log` 新增2 FAIL→相关正反例通过，`save-close-intent-tests.log` 15 PASS；最终增量完整 `web-full-close-intent.log` **465 PASS / 0 skip**，lint/typecheck及2106消息i18n通过。第一次全Web前置曾被在编HTML错误码边界拦截，后来修正后完整前置通过；中间unit-only运行的Python入口环境失败也保留，未跳过有效测试。**真实Chrome原失败链路待复测，AUDIO-03不关闭。**

最新功能验证：新增 Chrome 可选持续音频观察入口复用既有真实 E2E，默认短用例不变；工具20项、ESLint/typecheck通过。`audio-soak/runs-30/r1788686654444-w0/` 使用实际1898.4秒MP3，新增30.77秒连续观察通过（采样最大间隔/无推进均167.2ms），但随后跳转、暂停、关闭重开误差438000ms，完整用例 FAIL（AUDIO-03）。最后位置PUT仍37479ms，不能把UI滑块值当引擎跳转成功；正在补媒体事件/实际位置诊断。原 `audio-soak/run-30.log` 为主执行命令把章核变量名写错导致的启动失败，后续已改正确 `ERMAO_CHAPTER_CORE_LIBRARY`，没有修改产品路径或关闭原断言。正式30分钟播放尚未执行。

DEC-06 取消终态已核实：300k生成PID147712与监督130612/启动器148052等均退出，17:22:58按用户调整停止，非资源守卫触发；`local-load/prepare-300k-supervision-20260906-085353/cancellation-final.json` 与 `process-exit-check.json` 保留记录。部分目录含122342文件，日志仅确证至少122250已验证，无完整manifest，不计完成也不删除；100k完整样本保持可用。后续无大规模准备/测量任务。

DEC-06（用户最新决定）：超大书库验证以独立脚本按需运行，不再持续占用本次 AI 收敛；本轮导入性能接受 `local-load/measurement-20260906-065525/` 的安静 1 万级结果：19685 请求零失败、列表/详情/搜索/保存 p95 达标、确认进度零丢失、原文件与关联/重扫完整性通过。RG-05 本轮范围 PASS，未证明 10万/30万、长时或低功耗 NAS。已通知所属代理停止仍运行的 300k 准备并保留部分文件和日志，终态另补；不再启动100k/300k测量。全版本 RC 仍未冻结，其他门禁继续。

独立运行入口沿用 `scripts/python_release_load_precheck.py`，不新增管理框架。以下命令在隔离发布工作区根运行，使用已有 Python 环境和 psutil 安装；不需要 AI 驱动，不访问生产数据或对外发布：

```powershell
$env:PYTHONPATH = '.tmp/release-tools'
$env:PRECHECK_EVIDENCE_ROOT = 'D:/www/ermao-perf-precheck-manual'
# 先生成并验证；输出打印唯一 corpus 目录。
.venv-windows-1.0/Scripts/python.exe scripts/python_release_load_precheck.py --prepare-only --total-files 100000
# 将上一步实际路径填入；也可使用下文已完成100k corpus路径。
.venv-windows-1.0/Scripts/python.exe scripts/python_release_load_precheck.py --measure-window --total-files 100000 --prepared-corpus-root '<已验证 corpus 目录>' --idle-window-seconds 135 --active-window-seconds 180 --scan-timeout-seconds 10800 --overall-timeout-seconds 14400
```

支持 `--total-files 10000|100000|300000`，初始可读库20%，真实 EPUB/PDF/CBZ 比例4:3:3。测量自动启动和回收专用 API/Worker，保留源码摘要、逐请求/扫描/资源记录、进度读回及原文hash/关联完整性；12GiB服务工作集、768MiB剩余RAM、20GiB磁盘余量守卫保持。不要与其他构建/数据生成并发测量。增加 `--active-window-seconds` 只延长请求窗口，不能保证扫描始终活跃；工具不会自动证明浏览器/原生真实读听、重型媒体或完整持续压力场景，结果中的限制必须保留。此处命令是后续独立预检入口，不是尚未执行项目的通过证据。

移动全量本轮最终结果：`preflight-mobile/mobile-full-227e09f1-20260906/` 中 shared429、Android unit218全PASS且零skip，lint零问题；默认真机仪器148项 **147 PASS / 1 FAIL / 0 skipped，346.265s**。`09-instrumentation-summary.json` 精确记录第一章节点在第二次目录滚动手势后未消失；不得把adb退出0当套件通过，也不得用已通过的在线MP3独立1项覆盖该失败。普通test APK未包括opt-in在线入口，源码/APK比对及冷启证据由同目录文件记录；正在针对同包复现ANDROID-03。Docker于17:07只读复查仍无Linux engine pipe，`preflight-containers/docker-recheck-1707.log`，未执行重置或生产操作。

Chrome PWA 实际增量：`web-baseline/pwa-both-browser-transport.log` **2 PASS / 1.4m**；`release-live-pwa/r1788685159444-w0/`（desktop）、`r1788685202566-w1/`（mobile viewport）各以全新 production Web build/API/Worker 完成现有初始化、导入、EPUB恢复、MP3实际5/10秒保存与重开链路，且 Service Worker 已控制页面、shell缓存含offline/login、SW的shell/static/API/cover缓存不含认证响应或Reader/Asset原文。断网访问未缓存路径实际返回离线页，联网后auth/me为200；`service-worker-observations.json`、截图11和`post-run-verification.json`保留证据，7份原文件hash不变、API 5xx=0、服务均退出。运行使用 `RELEASE_LIVE_WEB_RUNTIME=production`、`PLAYWRIGHT_BASE_URL=http://release-live.localhost:3102`、`RELEASE_LIVE_API_PORT=18081`；仅浏览器自身解析此隔离loopback域名，无系统hosts/TLS修改。

PWA入口复用 `scripts/python_release_live_fixture.py` 与原真实E2E，生产模式显式构建并启用SW，默认开发模式不变；工具17项、Ruff、两TS文件ESLint及Web typecheck通过。原 `pwa-desktop-live.log` 与 `pwa-both-live.log` 的DNS失败保留并将测试会话值脱敏；失败来自Node请求客户端不能解析浏览器可解析的loopback域名，所有验证请求及logout现复用浏览器同源/no-store请求owner。`next start` 对standalone配置的警告保留：这里证明production模式PWA功能，**不证明standalone容器部署、系统PWA安装、版本更新切换或离线写入恢复**，上述门禁子项仍待执行。

100k 数据准备完成（不是性能通过）：`local-load/corpus-100k-20260906-083050/library/` 含40000 EPUB、30000 PDF、30000 CBZ，142061309 bytes、100000唯一hash。全部按既有CLI执行大小/hash、ZIP CRC/必要成员和pypdf reopen，`strict=False`恢复警告保留，不称严格格式合规或客户端阅读通过。manifest SHA-256由主复核为 `3289b16e5f3af6eafcf75156573e88844996dfc45807778d0eb4d86593fa5c19`。`local-load/prepare-100k-supervision-20260906-083049/summary.json`、`validation-boundaries.json`、`process-exit-check.json` 记录16:30:49–16:47:30、退出0、498次采样无资源触线、源码前后不变；最低可用RAM8.89GiB/磁盘52.64GiB，过程树采样RSS峰值191.42MiB。

下一项规模准备已从同一工具启动300k：`local-load/prepare-300k-supervision-20260906-085353/execution.json` 与 `resources.jsonl` 是恢复入口，监督PID130612；不能凭记录文件假定仍运行，恢复必须核查进程/持有句柄。未启动100k/300k性能测量；安静测量窗口须与数据生成、构建和其他功能运行分离。移动完整回归正在 `preflight-mobile/mobile-full-227e09f1-20260906/` 执行：已实得shared429/Android unit218全通过且零skip、lint零问题，仪器套件尚待最终结果。

当前增量：`dc8381f7` native options 与 `227e09f1` 共享 AUDIO bootstrap 修复已推送。Android 第四次全新库真实 MP3 在线用例 **PASS，1 test / 13.106s**：`android-live/android-1788684078319/`。5秒确认3897ms/revision2，10秒确认7906ms/revision3，暂停9930ms/revision4，关闭留下 Stop pending，重开恢复9930ms并确认到revision7。`instrumentation.log`、`online-evidence.log`、`apk-hashes.json`、`mobile-tested.patch` 与 `post-run-verification.json` 关联源码/开发包/结果；7份源文件hash不变、API 5xx=0、一次性凭据已消费、测试服务和reverse已退出。仅覆盖短时单轨 MP3、真实 Media3/HTTP/SQLite/ACK/重开，不替代后台/30分钟/逐编码/跨设备/正式 APK。

第三次运行 `android-live/android-1788683629933/` 保留 FAIL：已通过bootstrap与Range媒体请求，服务端与设备均确认revision2，但新测试按 Locator 字符串顺序比较，拒绝后端按键排序后的等价 JSON；620ms 的捕获→接收延迟与 Stop 后pending留在 `position-diagnostic.json`。测试改用完整 JSON 对象相等及完整typed presentation相等，身份、捕获时间、revision、pending及5秒时限不变，未更改产品序列化；第四次通过验证了修正。共享真实捕获的 AUDIO 响应先RED后GREEN，20项含负例的host检查通过，`preflight-mobile/bootstrap-format-20260906/` 保留原始响应hash与仅替换随机身份的映射；主增量构建/复验见 `50-bootstrap-format-device-build.log`、`51-online-json-value-observation-build.log`。

MOBI noscript/tail 修复后主49项针对性回归通过：`backend-baseline/mobi-noscript-tail-primary.log`，XML/HTML正文尾随文本均保留。raw-text实体语义缺口仍待SDK范围适配原型，不关闭READER-03。100k样本正在已有监督进程中生成，恢复入口为 `local-load/prepare-100k-supervision-20260906-083049/execution.json`；约半数的中间进度不是准备完成或性能通过。

最新恢复点：已推送 `d1fc48a9`；下文旧检查点仅保留历史效力。当前继续 Android bootstrap 格式映射与 MOBI HTML 修复；100k 真实紧凑文件准备独立执行。没有冻结 RC、正式产物或整体 GO。

- Android 独立真实 HTTP 用例两次 FAIL：`android-live/android-1788681827033/`、`android-live/android-1788682483508/` 的 `instrumentation.log`。实际新库 setup/import/login 和初始空进度读取通过，bootstrap HTTP 200 后本地拒绝，第二次稳定错误码 `READER_BOOTSTRAP_INVALID`；媒体请求尚未发生。各目录 `post-run-verification.json` 核实 7 份原文件 hash 不变、私有一次性凭据已消费、fixture 已退出；18080 reverse 已移除，18080/3101 无监听。APK hash、源码差异及日志留在各自目录，不把 adb 的退出码 0 当 JUnit PASS。
- `9e3a31a8` 的 Android fixture 入口复用现有真实 setup/导入 owner，13 项工具及 17 项相邻回归通过。独立测试源码位于 `apps/mobile/test-support/release-live/androidTest/`，通过 Gradle 属性显式启用；`preflight-mobile/48-online-confirmation-build.log` 和 `49-online-diagnostic-test-build.log` 记录开发构建，属于上述失败链路的测试准备。新增保存已严格校验 bootstrap 原始响应后工具再验 13 PASS。
- `d1fc48a9` 共享 ACK 修复通过 32 项针对性 host 测试；`c5157d71` 负载工具主复核 88 PASS，日志 `contracts/load-scale-primary.log`。二者均已推送专用分支，前者不是实际 Android 服务端确认通过，后者不是 100k/300k 负载验收。
- MOBI 新建 native options 修复候选：`corpus-format-library-20260906/backend-preflight/mobi-options-integrated-20260906/REPORT.md`，新 `.so` SHA-256 `969e080eb7f29188a6dad18c3bdf81a1aa8b3ac613afadc24136db6e50fa81fb`，5 文件目录及 10 个首末正文请求通过、原文件/hash/Range 通过，Linux publications 114 PASS。但后续独立审查 `backend-baseline/html-independent-review/REVIEW.md` 确认 noscript 可重新形成活动属性、删除节点丢 tail、raw-text 实体改写三个缺口，候选仍需修复；SDK DOM 证据不冒充 Chrome 执行，浏览器安全策略拒绝的访问未绕行。

`a533b89b`之后独立审查拒绝首版HTML修复候选：SVG/style文字重新解析产生onerror属性，以及SVG的xlink:href/href/xml:lang序列化失真；`corpus-format-library-20260906/backend-preflight/mobi-html-regression-20260906/REPORT.md`和`independent-review.json`保留精确输入/证据。主新增仅适配html5lib1.1 namespace与raw-text语义的token处理，保留唯一安全过滤owner和正常HTML CSS，37项针对性回归及Chrome4条实际DOM重新解析通过，mypy493通过；仍待独立复核，不将先前3条通过视为安全性完备。早期Chrome结果另存`backend-baseline/mobi-html-browser/results-initial.json`，当前`results.json`为4条。

同轮旧.so上真实五文件目录/首末正文/原文hash/Range通过、Linux publication109项通过；为消除旧二进制来源限制，从49份冻结native源码隔离重建.so（SHA256 `969e080eb7f29188a6dad18c3bdf81a1aa8b3ac613afadc24136db6e50fa81fb`，输入摘要`b50edf6ec7d6dfbb6d8695e45c8d6a7289725fca9a2e50ed79bfa3f229359d92`）。新.so却在MOBI族open阶段复现invalid_argument：Python传null options，与当前C要求有限options不一致，登记NATIVE-01修复。两次新库的API/Worker均已停止；重建不是正式产物，不回用旧库制造通过。

本轮在`e8d4209e`之后继续修复，未冻结RC。READER-03已由Linux实际样本复现：`corpus-format-library-20260906/backend-preflight/mobi-linux-7c6c991c/REPORT.md`、`body-failure-requests.json`记录MOBI/AZW/PRC目录16项成功，但共用的`part00000.html`正文422，cause为`ElementTree.ParseError: unbound prefix`。AZW3正文首末200，派生FB2目录18项及首末正文200；实际FORM/AIFC在独立Windows新库导入/单轨/原文Range通过，Linux缺ffprobe的失败保留。均未据此声明全部客户端阅读/播放通过。

修复增量临时证据：`backend-baseline/mobi-html-red.log`保留生产路径先失败；共享markup owner显式选择HTML解析/序列化并复用生成策略准备、预算和过滤，XML/SVG不作HTML失败回退。主34项针对性测试通过（`mobi-html-green-final.log`），mypy492通过，Ruff通过；`mobi-html-browser/results.json`记录Chrome152实际重解析3项、脚本/事件执行和网络请求均0；安全报告64与既有Chrome66/Android66校验通过（`contracts/safety-mobi-html.log`）。新预算测试第一次写错异常类别，按既有`PublicationParserLimitError`修正，保留`mobi-html-test-taxonomy-failure.log`，未改生产错误合同或预算。误用缺native配置的Windows广泛publication回归31 FAIL/77 PASS原始记录在`mobi-html-publications.log`；章核缺失与Windows符号链接条件由正确Linux环境另验，不跳过测试。

恢复顺序：先完成MOBI实际文件回归及可追溯native重建、移动端正常ACK完整链复现/修复，再执行Android在线读听与确认验证。大库工具在原入口补10万/30万规模参数、精确计数和采样覆盖；完整规模/时长尚未实测。此前`7c6c991c`完整后端报告保留为历史基准，本轮后端业务改动后的受影响结果须重新验证，不能拼接成同一RC通过。

### 最新检查点：`61d36d02`（未冻结 RC；后端源码`7c6c991c`）

真实Chrome音频扩展验收：`61d36d02`复用同一完整新库/EPUB/音频流程，按服务端MIME选择而非标题；AAC、WAV、FLAC桌面/移动视口共 **6 PASS**，分别`web-baseline/chrome-live-{aac,wav,flac}.log`和`chrome-live-{aac,wav,flac}-results/`。实际运行`release-live/`下AAC为`r1788679009311-w0`、`r1788679092759-w1`；WAV为`r1788679154307-w0`、`r1788679211032-w1`；FLAC为`r1788679268535-w0`、`r1788679327873-w1`。主核对实际MIME、每5/10秒更新服务端位置、重开误差（均≤200ms）、API 5xx为0及全部shutdown-complete；ESLint/typecheck通过。连同之前MP3两视口，四组合获得真实短时播放/连续保存/重开证据，不扩为全部音频、30分钟、多轨或原生平台PASS。

`32175712`修复语料生成器的AIFC别名问题：显式pcm_s16le输出并检查FORM/AIFC头；2项正负测试及真实ffprobe校验通过（`contracts/aifc-generator-tests.log`、`aifc-generator-real-probe.log`）。新样本在`corpus-supplement-20260906/`；旧AIFF别名字节保留。仓库已有带章节FB2样本实际存在未绑定l:前缀，原文件与复制件保留；派生`sectioned-namespaced.fb2`仅补xmlns:l，XML解析确认18 section，精确变更/输入输出hash及验证边界见`provenance.json`。不声明已做完整FB2 XSD验证；Linux真实新库验收进行中。

安静10k实测已完成：`local-load/measurement-20260906-065525/`，独立监督日志`local-load/supervisor-20260906-065525/`。2026-09-06 14:55–15:07（UTC+8），测试前停止本任务Next3100、所有并行功能回归及代理服务，未操作原开发3000/8000。SOURCE digest `cbdb032d03ea946adf38e225838013f97b7a0f92d48c4deea5954bf386ee86d8`保持不变。**19685次请求，0失败，预设性能阈值违规0项**；真实导入10000 Books/Resources/Assets、10103 SourceNodes、10000唯一文件hash，共14196456 bytes。增长扫描列表/搜索/详情/进度保存p95分别63.226/64.074/18.765/60.405ms；重扫活跃阶段分别89.028/83.038/20.642/34.953ms。全流程API+Worker进程树RSS最大306278400 bytes，清理错误0，主复核4个任务PID均退出。

扫描后全部10000原文件hash匹配，book/resource/asset/path关联和身份保留检查通过；增长/空闲/重扫分别读回500/1346/1798资源的最新已确认位置、丢失0，另3个未被负载覆盖的重扫哨兵保持一致。原失败仍保留，此次`complete.json`、`summary.json`、`rescan-integrity.json`和`integrity/`为修复后的独立证据。边界：135/180秒固定负载窗口，增长实际扫描208.078秒，采样活跃201.947秒中约180秒有负载（89.1%）；重扫活跃45.008秒中约44.995秒有负载（99.97%），其余请求明确归scan_idle。短窗口、紧凑三格式、四HTTP端点不代替30分钟/2小时、10万/30万、真实三端读听并发或NAS结论；RG-05未整体PASS。

当前后端完整回归已由主代理读取原始日志核对：Linux **1284 PASS、2项既有Windows平台skip，coverage77%，321.91s**；Windows补测该两项均PASS。`backend-baseline/linux-7c6c991c/{linux,windows}/`保留pytest原始日志、XML、coverage、实际环境及源码hash；Linux689文件Ruff format/check与mypy492均PASS。从`7c6c991c`直接git archive得到SHA256 `436cab9d3d34f951ef1034004a698fa44563eb1c6e467ac5de8425f9df4f2875`，运行后归档源码未改变。合计1286个适用后端用例覆盖，不将平台skip改成无条件跳过。后续提交仅工具/文档/Web取证入口，后端源码保持该版本；最终RC仍需冻结验证。

59份语料实际后端报告在`corpus-format-library-20260906/backend-preflight/REPORT.md`：60任务全部成功、53资源bootstrap、59原始asset下载hash和Range、51单文件publication下载全部通过；另外两目录共8成员按asset验证。59文件只有48个独立hash、43音频文件覆盖24个codec，客户端引擎执行数为0。MOBI/AZW/PRC/AZW3目录缺Windows libmobi，FB2没有section、AIFC实际AIFF的样本限制保留，G726需格式提示的裸流探测记录双结果。源码摘要与`7c6c991c`的Git对象逐文件匹配；不能按后缀数量宣布所有格式播放通过。

`8ec43a27`为现有Web安全报告入口增加显式`--browser chrome`及真实Chrome channel选择，没有改策略/期望；Backend64、Chrome66报告与已有Android66报告跨消费者校验PASS（`contracts/backend-safety.json`、`web-chrome-safety.json`、`safety-three-consumers.log`）；不覆盖iOS。脚本ESLint/typecheck通过。`b93e1025`共同取证等待修改的38项Reader Chrome回归PASS，`web-baseline/chrome-opening-ready.log`、`chrome-opening-ready-results/`。

`27bad491`补齐已有负载工具的扫描前后source SHA与book/resource/asset/path身份关联校验，复用既有散列、ORM关联及公共范围规则；主独立36项正反工具测试PASS（`contracts/load-integrity-primary.log`），Ruff/diff检查PASS。完整性观测在负载窗口之外，失败先保存证据再进入非零退出，135/180默认窗口与门禁阈值未改。实际安静10k重测是下一项，不凭工具测试计LOAD通过。

`7c6c991c`已统一默认封面与缩略图/漫画缓存的原子发布owner，删除旧重复发布实现。主独立7项正负/并发回归、五文件Ruff及diff检查PASS（`backend-baseline/default-cover-primary.log`）。严格真实Chrome桌面/移动视口 **2 PASS，2.2m**，`web-baseline/chrome-live-default-cover.log`、`chrome-live-default-cover-results/`；实际运行目录`release-live/r1788676774434-w0/`、`r1788676846298-w1/`，记录源码、样本hash、API/Worker/浏览器和已完成清理。两项均使用实际`audio/mpeg`资源，API无5xx；第5/10秒服务端位置分别为3673/7927ms和3926/8187ms，最新位置重开为8000ms，均满足已冻结误差。七类导入不等于七类客户端播放。截图复核发现EPUB在ready后的退场动画尚未结束即取证；`b93e1025`仅加强共同等待条件为开屏层完全移除，重新采集画面，未据此推定产品卡死。

当前后端位置HTTP探针再次PASS（`position-http/7c6c991c/position-report.json`、`backend-baseline/position-http-7c6c991c.log`），仍仅证明合成opaque Locator的真实协议/存储，不替代引擎恢复。完整Web lint/typecheck PASS（`web-baseline/lint-7c6c991c.log`、`typecheck-7c6c991c.log`）；双语2106消息校验PASS（`i18n-7c6c991c-correct-entry.log`）。首次从根目录调用不存在的i18n脚本为执行入口错误，原日志保留；改用现有`pnpm --filter @shuku/web i18n:check`，未修改校验器。

`b93e1025`重新实测两视口 **2 PASS，1.9m**（`web-baseline/chrome-live-ready.log`、`chrome-live-ready-results/`）；运行目录`release-live/r1788677017469-w0/`、`r1788677072813-w1/`。主代理复核移动视口`07-epub-reopened-chapter2.png`已显示无遮挡的第二章，另核对音频恢复界面；原安全fixture自带红字绿底与被阻止的远程像素，未改写读物或以截图替代安全副作用测试。两运行均记录shutdown-complete，生成的Next配置差异核对后仅恢复该两文件。

最新完整回归：Chrome桌面/移动视口126 PASS、0 skip（`web-baseline/chrome-full-audio.log`、`chrome-full-audio-results/`）；Web生产构建PASS（`web-baseline/production-build-audio.log`，输出归档`web-baseline/production-build-c13a7034/`）。该批包含音频时序及播放Promise修复，普通E2E使用既有HTTP fixtures，真实后端严格MP3两视口仍另行验收。

Android新增实际持久化测试已提交`d6b11360`：真实Media3→共享进度运行时→生产SQLite owner，在第5/10秒从独立连接读到更新的Locator；暂停9980ms、关闭运行时后重开9988ms，误差8ms。原始测试/数据库/PCM/hash在`preflight-mobile/rg04-audio-durability-20260906/`，其README保留提交前HEAD，最终源码归属以上述提交为准。随后同一Android源码及测试包完整真机回归 **148 PASS，344.921s**（`preflight-mobile/46-audio-timing-full-device.log`）；共享层416、Android单元218、lint全部PASS（`45-audio-timing-full-host.log`、`47-audio-timing-host-counts.json`）。设备`9e896bbc`，开发包hash沿用该durability目录记录，不是正式签名产物。该测试覆盖离线上报队列及同进程运行时关闭/重开，不宣告在线确认、进程死亡、全部编码或30分钟通过。

| 增量 | 已执行证据 | 判定边界 |
|---|---|---|
| `c6b3e802` 音频共享4秒捕获周期 | `preflight-mobile/rg04-audio-autosave-fix-20260906/`：KMP23、Android6；`web-baseline/audio-timing-full-unit.log`：Web459 PASS/0skip | 捕获单测不代替实际落盘；真实Chrome连续5/10秒服务端位置见下行 |
| Chrome真实后端链路 | WAV两视口旧脚本通过，目录中 `release-live/r1788674923465-w0/`、`r1788675072817-w0/`；第5/10秒可读回新位置。随后按MIME精确选择MP3、禁止任何API 5xx：`web-baseline/chrome-live-mp3.log` 两项FAIL，`release-live/r1788675527007-w0/`、`r1788675587866-w1/` | MP3播放/暂停/定位/重开与5/10秒读回断言通过，但默认封面500使整例FAIL。旧报告scope称MP3不准确，实际WAV，不用旧scope计格式覆盖。旧脚本漏断言的EPUB目录503已定位到缺Windows native章核；现已编译并显式接入，最新两轮不再503 |
| `8a4ed3fb`/`80a65f77` 缩略图缓存竞争 | `backend-baseline/cover-cache-primary.log`：5 PASS，包括双并发、WinError5/32、永久失败、非Windows errno5、原文件不变/有效图片/临时清理 | 此cache owner回归通过；另一路 `services/default_cover.py` 原子发布仍复现500，MEDIA-02继续修复，不混作已关闭 |
| `c04818f3` 独立阅读状态投影 | `backend-baseline/reading-status-batched-regression.log`：219 PASS；`reading-status-bootstrap-regression.log`：26 PASS；mypy491通过。`reading-status-bootstrap-red.log`保留打开接口遗漏的原始失败 | Reader/Library复用同一批量状态查询和domain规则，原3查询预算保留。手动已读不伪造100%位置；原百分比仍是实际阅读位置 |
| `68c02047` 维护检查线程边界 | `backend-baseline/maintenance-pool-20260906/REPORT.md`：RED/GREEN、39 PASS；主独立11 PASS在`maintenance-pool-primary.log` | 修复已复现的事件循环阻塞放大点；不宣告原池耗尽/全部并发已解除 |
| `c13a7034` 最近阅读聚合 | `backend-baseline/recent-read-query-20260906/diagnosis.md`：10k库副本0/1000/1817进度的VM工作量比较与语义对照；主`recent-read-query-primary.log`：10 PASS | 既有唯一Reader聚合增加按书分组，无索引/阈值变更；受控复杂度回归不等于完整负载PASS |
| `d9c96db1` 10k实际预检 | 工具15 PASS：`contracts/load-observer-primary-reviewed.log`；实际失败目录是`artifacts/releases/1.0/local-load/measurement-20260906-053850/`（不在本节E根），`failure-summary.json`记录10000 Books/Resources/Assets、重扫结束后进度读回超时 | 与13:41–13:46 Chrome运行重叠，性能数受干扰；保留FAIL，原文件/关联完整性收尾未验。修复后须安静窗口重测，不据此通过RG-05 |
| `efaeadd7` 位置HTTP探针 | 工具4 PASS：`contracts/position-probe-tools-primary.log`；真实探针历史`artifacts/releases/1.0/position-http/20260906T053626495Z/position-report.json`，脚本SHA与最终提交一致 | 真实API/Worker、两账号、回包放弃/幂等重放/迟到写/并发/重启快照；合成opaque Locator仅证明存取，报告明确PARTIAL/NOT_COVERED，不替代真实引擎恢复和客户端outbox |

Windows C章核由同一`chapters.c`以Zig C99 warning-as-error编译共享DLL，`chapter-core/windows-shared-build.log`；SHA256 `36ccc43c4c5c15f327728442b259f1673c6815bfe3642137d26916a1141a8740`。测试环境通过`ERMAO_CHAPTER_CORE_LIBRARY`接入`.tmp/chapter-core-windows/ermao_chapters.dll`，不是正式后端交付物。

下一项可执行工作：用现有Linux native库完成MOBI族目录实测，补全有章节FB2和真正AIFC样本，继续实际客户端格式/位置异常链路及更大规模时长验证。Windows没有现成MOBI DLL，检查证据在`corpus-format-library-20260906/backend-preflight/mobi-environment-20260906/inspection.json`；不因一个宿主能力缺失停下其余项。已完成代理产出由主审后分项commit/push；当前未公开发布。

### 之前增量（保留追溯，以以上最新状态为准）

最新增量：`bc94df7d` 将两个 Dockerfile 的 Python 安装统一到现有 lock，复用 `scripts/install-python-runtime.sh`；5项命令边界测试和 WSL 实际39个锁定运行依赖安装/导入通过，见 `preflight-containers/result.md`、`05-locked-runtime-import-verification.log`、`07-final-static-tests.log`。锁漂移在创建环境前失败；Docker 引擎、双架构镜像运行仍 BLOCKED。

真实 Chrome 新库链路当前尚 FAIL：`release-live/r1788672824257-w0/` 与 `r1788673266527-w0/` 记录七种真实文件导入、EPUB第二章保存和重开。首轮播放后立即暂停触发未完成 `play()` Promise 的过期错误，已由 `c14b3033` 修复；3项异步顺序单测、ESLint和TypeScript检查通过，`web-baseline/audio-play-attempt-tests.log`、`audio-live-typecheck.log`。第二轮通过该步骤，在重开按钮尚未加载时错误选择资源卡的测试分支超时，日志 `web-baseline/chrome-live-audio-fix.log`；测试已改为等待可用入口，待重跑。不得将局部经过路径登记成完整用例 PASS。

新确证缺陷：独立 reading-status 与列表/详情投影不一致，见 `preflight-mobile/reading-status-public-projection-20260906/`；音频5秒内没有自动捕获位置，见 `preflight-mobile/rg04-audio-autosave-repro-20260906/`。正在复用 Reader 状态规则和跨端时序常量修复，旧 Android147项通过只代表之前检查点。真实 API 的 Windows 封面并发500亦已保留 `release-live/r1788672824257-w0/api.log`，正在定位唯一缓存实现。下一项可执行工作为上述修复、Chrome真实闭环、本机10k测量和位置HTTP探针；后端源码在负载测量窗口内保持不变。

- 初始全套Chrome使用 `854712bb` 的 Web/C/WASM 源码；后续音频修复使相关旧结果不再代表当前源码，必须重新回归。当前已推送检查点以上方最新登记为准。
- 用户批准 DEC-05：1.0 暂不支持第三方进度同步；OPDS 目录、搜索、下载保留。`f3748d58` 删除同步实现和声明，授权 GET/PUT 返回 410，未授权仍 401；阴性测试验证旧表、v5 表及所有 DML 均无写入。
- 起点：`develop@197e81a808ba32595a8a6ffeda62422b3a7d3473`，初始 `git status --short` 无输出。后续复核发现原工作区出现 OPDS/shared 等未提交变化，归属正在核查；这些变化全部保留，不清理、不提交，不作为隔离发布分支的已验收内容。
- 隔离工作区：`D:/www/ermao-release-1.0`；分支 `codex/release-1.0-convergence`。正式 RC 未冻结，无 tag/公开发布。用户追加授权及时 commit/push；已检查三个工作流，push 仅匹配 develop/prod 或版本 tag，专用分支不触发发布。只推专用分支，不创建 PR/触发工作流。
- 实际证据根：`artifacts/releases/1.0/197e81a808ba32595a8a6ffeda62422b3a7d3473/`。这是开发基线证据，后续修复须另记源码差异/提交；不能直接用于冻结 RC 放行。
- 环境：Windows；复用已安装 Node 22.23.1、pnpm 9.12.2、Python 3.11.15/uv 0.12.7，依赖在隔离工作区安装。Python 不在 PATH 的问题通过本任务 PATH 和 `PYTHON_EXECUTABLE` 解决，无系统配置变更。
- Android `adb devices -l`：`9e896bbc` / M2102K1AC / device，用户明确允许真机测试；只做保留数据验证。没有可用 Mac/Xcode/iOS 签名运行环境登记。
- 用户已接受现有阈值/ADR 0028 语义；本轮低功耗 NAS 暂缓，以本机预检为准。正式安装包构建/导出暂缓，交付物未准备与未发布分别记录。

| ID / 关联 | 实际执行 | 结果 / 证据（相对本节证据根） | 效力 |
|---|---|---|---|
| R1-ANDROID-FULL / ART-01 | `80c5d5b9` Android/C 源码，Debug/test 两包保留数据安装；授权真机完整 instrumentation；测试后冷启动 | PASS：147 tests，0 failures，304.092s；`preflight-mobile/40-integrated-device-build.log`、`41-integrated-install.log`、`42-integrated-full-device.log`。两包 SHA-256：`43-integrated-debug-hashes.txt`；冷启动408ms，versionName1.0.0/versionCode1：`44-integrated-cold-launch.log` | 该批自动真机回归完成，包括实际音频引擎和修复后的漫画目录；Debug 只用于本轮代码验证，不计正式 APK 交付，也不替代真实服务端多端/逐格式/长时门禁 |
| R1-PYTHON-OPDS-FINAL / ART-01 | `f3748d58` 后端源码快照，Linux 完整无选择过滤 pytest-cov、ruff format/check、mypy；Windows 对应平台专项 | Linux 1250 PASS / 2 原有 Windows pipe skipped，coverage 77%；`backend-baseline/linux-f3748d58/evidence/pytest-full-coverage-no-filter.log`、`pytest-selection-summary.txt`。Windows 同后端树两项分别1 PASS / 0 skip：`backend-baseline/windows-pipe-tests-f3748d58-20260906/summary.txt` | 两个系统共同覆盖全部1252项；早期 `-k` 排除运行保留为历史诊断，不作为最终全量依据。后端运行门禁仍需真实客户端、性能及冻结 RC |
| R1-ANDROID-HOST / ART-01 | `80c5d5b9` 从唯一章节 C/JNI/CMake owner 构建 Windows host DLL，再跑完整 JVM tests；集成 lint | 216 tests / 0 failed/error/skipped；`preflight-mobile/39-host-jni-integrated-unit.log`、`32-android-unit-final-xml-exact-summary.log`。`38-lint-integrated.log` BUILD SUCCESSFUL | 缺失 DLL 的 FB2 6项失败解除；单个标准 MediaSessionService ExportedService lint 有说明的局部抑制保留现有绑定语义，无新权限。旧视觉夹具唯一引用的废弃双语资源已删除，不改检查规则 |
| R1-ANDROID-VISUAL / RG-03 | `51a7b3e8` 真实管理宿主/公开详情契约夹具；授权机7项+ReaderControls 1项 | 全部 PASS；`preflight-mobile/visual-fixture-codex-review-20260906/` 中 `visual-fixture-am-instrument-after-reading-status-owner.log`、`reader-controls-am-instrument-after-comic.log`，25张 `reader-controls-after-comic/` 截图 | 主代理已查看 comic-contents：按钮1/2、第二页摘要一致；epub-contents 有正文和目录，早期控制截图空白不作为已复现缺陷。测试仍保留双语/大字号可达、路径长按、书架入口保护。真实后端 reading-status 投影另列静态风险，未凭 fixture 关闭 |
| R1-ANDROID-AUDIO-ENGINE / AUD-* | `d666bfa1` 真机 MediaController→MediaSessionService→Media3，12秒静音 PCM 原文件；暂停启动、播放/暂停、7秒定位、1.5倍速、两轨切换、退后台实际时钟、原文件hash | PASS 1 test；`preflight-mobile/35-real-audio-readiness-build.log`、`36-real-audio-test-install.log`、`37-real-audio-readiness-device.log` | 初轮 `34-real-audio-device.log` 在切轨 Loading 阶段提前 play，现等引擎 Paused 确认后再操作；未延长超时或弱化断言。仅真实引擎短时 PCM，不代表服务端下载/v5恢复、全部编码或30分钟播放。只有专用临时WAV被删除，保留设备数据 |
| R1-CORPUS-59 / RG-03 | 复用现有公开格式素材生成器、Gutenberg/LibriVox原始素材、固定 FFmpeg/ffprobe | 59份正常样本及探测/原始来源hash：`corpus-format-library-20260906/corpus-manifest.json`、`audio-format-inventory.json`、`source-provenance.json` | 准备完成不等于播放通过；RAR/CBR及10个缺编码器格式仍缺样本，AZW/PRC同源扩展名变体限制保留，不伪装独立格式内部变体 |
| R1-LOAD-OBSERVER / RG-05 | `scripts/python_release_load_precheck.py` 复用既有 smoke 生命周期和真实 API/Worker | 采集保护4项 PASS：实际子进程内存计入、失败请求不丢弃、进度确认后真实 HTTP 读回正反例、样本路径越界拒绝；`contracts/load-observer-tests.log`。psutil 7.2.2 仅安装到 `.tmp/release-tools` | 实际负载待运行。`D:/www/ermao-perf-precheck-20260906/corpus-10k-20260906-124641/` 中10000份有效 EPUB/PDF/CBZ 共约14 MB，只覆盖紧凑混合索引预检。运行设 `PYTHONPATH=.tmp/release-tools`、`PRECHECK_EVIDENCE_ROOT=<本节证据根>/local-load`，参数 `--measure-window --prepared-corpus-root <上述目录>`；135/180秒默认窗口不冒充30分钟门禁或10万/30万 |
| R1-WEB-STATIC / ART-01 | `pnpm lint`、`pnpm typecheck`、`pnpm i18n:check` | PASS；`web-baseline/lint.log`、`typecheck.log`、`i18n-runtime-fixed.log` | 基线 Web 静态检查；i18n 首次 PATH 失败日志另保留 |
| R1-WEB-UNIT / ART-01 | `pnpm --filter @shuku/web test`，含前置 WASM/安全生成/边界/设置/双语校验 | PASS：456 tests，0 failed/skipped；`web-baseline/unit-runtime-fixed.log` | 自动测试，不代表完整格式/真机通过 |
| R1-WEB-E2E-HIST / ART-01 | 原四浏览器 `pnpm test:e2e --workers=2` | 155 PASS / 97 FAIL；`web-baseline/e2e.log`、`test-results/` | 用户已收敛为 Chrome，仅保留诊断历史；63 个 Firefox 启动失败为环境问题，其余逐项分类 |
| R1-CHROME-READER / RG-03/04 | `pnpm exec playwright test e2e/readium-reader.spec.ts e2e/comic-reader.spec.ts --workers=2`；Chrome 152.0.7977.76 桌面和移动视口 | PASS：42 tests，0 skipped；`web-baseline/chrome-reader-retest.log`、`chrome-reader-retest/results/`；目标文件 ESLint 与 Web typecheck PASS | 修正过时 Locator 字段/移动点击与布局假设；增加缓存重开仍仅下载一次。保留真实段落恢复、显示百分比不控制恢复等断言；HTTP fixtures 不替代真实服务器或最终 RC |
| R1-WEB-BUILD / ART-01 | `NEXT_DIST_DIR=.next-codex pnpm build` | PASS；`web-baseline/production-build.log` | Web 生产构建，不是双架构部署验收 |
| R1-CHROME-FULL / ART-01 | Chrome 桌面及移动视口完整 Playwright，`--workers=1` | PASS：126 tests，0 skipped，3.2m；`web-baseline/chrome-full-r2.log`、`chrome-full-r2-results/` | 前轮 124 PASS / 2 FAIL 的 trace 均停在 `browserContext.newPage`，尚未加载应用；单 worker 全量重跑通过，没有改断言/超时/重试掩盖失败。仍非真实后端逐格式验收 |
| R1-PYTHON-LINUX / ART-01 | WSL Ubuntu 24.04、独立环境及 GCC native core，完整 pytest coverage | PASS：1253 passed，2 Windows-only skipped，coverage 78%；`backend-baseline/linux-614b5fed/evidence/pytest-full-linux-coverage.log` | `614b5fed` 快照；与 Windows 结果互补，OPDS 后续修复使相关旧证据失效，最终完整回归待执行 |
| R1-CHAPTER-CORE / RG-03 | Zig C99 warning-as-error 编译共享章节核及 native 测试；生成 WASM manifest 校验；Chrome TXT 用例双视口 | PASS；`chapter-core/native-test.log`，全量 Chrome 见上 | `854712bb` 接受“第 1 章”的数词周围空格/tab，保留原文、偏移及非标题负例；修改唯一 C owner 并重新生成 WASM，无平台另写推断规则 |
| R1-PYTHON-WINDOWS / ART-01 | 完整 pytest + coverage，ruff format/check、mypy | 1219 PASS / 36 FAIL，1255 collected，coverage 77%；`backend-baseline/` | 6 个 Windows 能力/路径问题、30 个缺 native core 的失败；Linux 隔离重验进行中，不将缺工具直接计产品失败 |
| R1-PYTHON-SMOKE / RG-02/03 | 新临时数据根，经 setup/鉴权 API 创建书库→真实 Worker 扫描；EPUB/PDF/CBZ v5 bootstrap、完整原文件 hash、精确 Range、漫画页 revision；独立 ContinueImport worker | PASS；`runtime-smoke/sample-after-review.log`、`worker-after-review.log`、`sample-hashes-after-review.txt`；过程工具测试 4 PASS | `76707cce` 修正旧 v4 smoke/PIPE 阻塞；复用同一有界进程宿主，不新增服务端正文路径。仅三媒体后端链路，不替代客户端阅读或所有格式 |
| R1-MOBILE-BASELINE / ART-01 | shared host、Android unit/lint、授权真机完整 instrumentation | shared 414 中 3 FAIL；Android unit 216 中 8 FAIL；lint 46 errors；仪器 145 中 19 FAIL；`preflight-mobile/07-failure-summary.txt` 及原始日志 | 失败正在分类修复；Debug 冷启动成功不替代正式 APK 或完整门禁 |
| R1-CONTRACT / ART-01 | Reader schema unit、生成/边界；iOS verify_readium.py | schema 33 PASS（修复 nullable type union 验证器）；静态生成/边界及 iOS 静态检查 PASS | `6cfbf7bb`；静态 iOS 检查不替代适配器或设备执行 |
| R1-DOCKER / ART-02 | `docker version/info/buildx ls`，启动现有 Docker Desktop 后复查 | BLOCKED：引擎未启动；宿主日志显示 Inference manager 本地 socket 无法访问 | 环境故障；未重置/删除 Docker 数据 |
| R1-ANDROID-SAFETY / RG-03 | 真机生成报告后 `verify-reader-safety-conformance.py --require-consumer ANDROID` | PASS：66 cases，0 omissions；`preflight-mobile/android-conformance.json`；SDK31 / PDFium `875172eae557a308d0c5b2be43822814c8a885bb` | `ae1275cd` 测试修正；不代替 Web/backend/iOS 独立报告 |
| R1-ANDROID-READER / RG-03 | `ReaderEpubInstrumentedTest`、`ReaderControlsVisualInstrumentedTest` 真机执行 | PASS：7 tests；`preflight-mobile/17-reader-panels-rebuild.log`、`18-reader-panels-device.log`；单项滚动诊断 `16-epub-scroll-device.log` | `0066f2c2` 加后续两测试修改；滚动保留 Double 偏好、真实布局无横向溢出、视口前后翻与原生 swipe 保留；面板关闭验证 workspace 消失，标准底部控制台保持。仅测试修正，不改 Reader 产品行为 |
| R1-ANDROID-FIXTURES / RG-03/ART-01 | 增量 assembleDebug/assembleDebugAndroidTest，保留数据安装；设备 `9e896bbc`，7 个类/选定方法 | PASS：32 tests；`preflight-mobile/12-test-fixture-rebuild.log`、`13-test-fixture-artifacts.txt`（APK SHA-256）、`14-test-fixture-device.log`；首轮 20 中 2 FAIL 另存 `10-test-fixture-device.log` | `7847cdd2` 加后续测试修正及并行未提交源码的开发快照；正式 RC 全量须重跑。instrumentation 尾部 `INSTRUMENTATION_CODE=-1` 为 runner 结束码，本次 `OK (32 tests)`；不能单凭 adb exit 或该码判定失败/通过 |
| R1-OPDS-CLOSURE / OPDS-04 | 主代理独立执行 OPDS HTTP/protocol 与 v5 progress/contract 五个文件 | PASS：41 tests，0 skipped；`opds-investigation/closure-primary-regression.log` | `f3748d58` 后端源码；目录/搜索/详情不发布同步链接，原 GET/PUT 不写任一进度 owner。原 44 项中的已退出范围同步正例被关闭行为正负例取代；真实第三方客户端目录验收仍待执行 |
| R1-ANDROID-COMIC-TOC / RG-03 | 千页目录首/末页、摘要、真实导航回调与全部目录交互；授权真机 | PASS：19 tests；`preflight-mobile/30-comic-toc-contract-build.log`、`31-comic-toc-contract-device.log` | `805be838` 修复一基显示页码及 LazyRow 可达性。最初新测错误沿用 EPUB 异步目录夹具，日志 22/25/27/29 保留，不计为长漫画已复现证据；页码原缺陷以真实 comic-contents.png 为据；最终夹具复用漫画同步目录契约 |
| R1-NATIVE-CROSS-HOST / RG-03 | Linux 同一 C patch + GCC `.so`、Python TXT/章节71项；Windows平台专属pipe2项 | PASS：71 + 2；`backend-baseline/linux-614b5fed/native-854712bb/`、`backend-baseline/windows-pipe-tests-20260906/` | Linux 原完整套件两个 Windows-only skip 已在真实 win32 各自 PASS；非无条件跳过 |
| R1-LOCAL-OCI-CLI / ART-02 | 现有镜像入口新增 `--output-dir`，5项命令边界测试 + 原12项发布校验 | PASS：17 tests，0 skipped；`contracts/local-oci-release-final.log`；Bash语法检查通过 | Docker/Git/验证命令使用临时 stub；证明本地模式不 push、不使用 prod tag、仅归档冻结提交、拒绝脏源码/检查后变动/覆盖、失败不写成功manifest。不是 Docker 构建成功，真实引擎仍 ENV-08 |

Android 测试修正依据：CRC 使用 fixture 的实际损坏 bytes，禁止传入写死的完好原文；音频 MIME 一致性案例按既有 v2 manifest 的 ALLOW 输出（未改规则/期望）；漫画双页偏好按共享设置持久化，增加同用户跨服务器隔离；章节按钮提供显式引擎 TOC identity；书库目录挂载实际 Shell 所需管理宿主并校验仅下载回调；Compose 1.11.3 的 `stringResource` 实际读取 `LocalResources`，双语 fixture 补全该上下文；菜单按现有 224dp 平台几何校验，以 `positionOnScreen` 验证 60px 移动且保持 2px 容差；应用浅色外壳按 design-contracts README 校验两个系统模式的 canonical canvas，Reader 自身日夜主题测试保留。均未修改产品视觉或降低验收阈值。

当前可执行工作：关闭已退范围的 OPDS 同步入口并验证无副作用；完成 KMP/Android 剩余回归，修复漫画目录真实页码/长目录可达性缺陷；执行隔离新数据本机压力预检与位置链路验收。后端最终代码全量及冻结 RC 完整验证仍待执行；正式产物暂缓。

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
| RG-01 | PARTIAL；正式产物NOT_RUN | 现有后端/Web构建与Android开发包有验证；最终同RC后端/APK/IPA交付尚未执行 | ENV-02 iOS、ENV-08容器；ENV-07正式包由负责人暂缓，不能用开发包代替 |
| RG-02 | PARTIAL | 新库API/Worker、两组织模式正常导入及部分第一方实际连接有开发证据；OPDS客户端为DEC-08负责人PASS | 未覆盖的初始化/导入异常/网络/权限与iOS子项继续；DEC-05已移除第三方进度同步，原ENV-04不再阻塞 |
| RG-03 | PARTIAL；有未闭环FAIL | 逐格式开发验收推进中；AUDIO-10/11/12关闭，四音频格式普通短时、章节/多轨部分场景通过 | READER-05/06/07真实回归受ENV-12限制；其余格式/异常/生命周期及iOS仍有缺口；音频仅DEC-09四格式 |
| RG-04 | PARTIAL；有未闭环FAIL | 四音频格式正常Chrome↔Android有开发证据；SYNC-03关闭；POS-03/04/07及其他子项部分通过 | SYNC-02真实时序回归受ENV-11限制；POS异常组合、其他格式及iOS方向继续；不再要求OPDS进度互通 |
| RG-05 | 本机预检PASS；最终RC NOT_RUN | DEC-06既有安静10K导入/前台可用性/重扫完整性预检通过，原始测量保留 | 100K/300K和低功耗NAS按负责人决定暂缓，不继续AI压测；不外推本机结果到NAS或未冻结RC |

以上汇总按2026-09-07 fbe61f89时点的开发证据更新，替换R0整组NOT_RUN概述；每个具体子项仍以矩阵和原始结果为准。五组最终同RC完整验收均尚未完成，不能把PARTIAL、负责人暂缓或环境阻塞转成整体PASS。下方原始最终签收占位表保持未签收。

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
