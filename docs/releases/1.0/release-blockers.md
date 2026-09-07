# 1.0 发布阻塞项

当前覆盖：IMPORT-01已CLOSED，真实409及无重复写入见release-evidence首节，停止扩验。RISK-08经真机真实ViewModel受控边界复现为SYNC-05，候选原场景回归中；无普通UI/持久位置损坏外推。后续按DEC-10最小充分验证，外部阻塞及最终RC要求不变。

2026-09-07 IMPORT-01（RG-02 / INI-02，P2，真实FAIL，候选待原HTTP回归）：全新专用库实际重复POST /api/libraries返回500，原handler欲返回409/rootPath，但ImportErrorBody.details仅允许files，typed_route校验抛错。原api-completion.log和针对性RED（1 failed/1 passed）留存；候选仅补明确rootPath错误详情类型，旧files及extra-forbid保持，43项API/权限相邻与mypy495通过。无重复库写入已由针对性断言验证，实际修复后原HTTP仍待验，不关单。证据fd26b7aa/rg02-fresh-api-boundaries-20260907。

2026-09-07当前覆盖：SYNC-04、AUDIO-14均CLOSED，b72b3d83新隔离库真实Chrome离线C→Android N→Chrome重连→Android冷首页/详情原场景已通过，普通恢复5015ms/969ms相邻和新增Chrome定向E2E亦PASS，详见release-evidence首节。下文两项OPEN及“下一项原回归”为历史状态。本轮无新增确证产品缺陷、无测试工具扩展；停止已关闭两项的完善。

下一可执行项RISK-08仍为静态风险：独立审查明确Home取消异常被内层吞掉、Detail持久查询后缺generation守卫，但尚无受控调度复现，不能以冷启动PASS关闭，也不能直接宣称持久位置损坏。已有服务/设备/浏览器清理完成，原用户15项改动保留。ENV-11/12、iOS/容器与正式包暂缓继续分项保留；未冻结RC、未整体GO。

RISK-08 / RG-04待验证：SYNC-04独立审查指出Home/Detail持久查询后的generation/取消与失败边界未覆盖，属于静态风险，尚非已复现产品FAIL；需针对旧查询返回和查询取消做适当验证，不能由冷启动PASS直接关闭。AUDIO-14完整Web静态/单元检查已通过，实际新E2E与普通UI待验，两项显示缺陷仍未关单。

SYNC-04候选已有主diff审查、host/lint及真实隔离SQLite两项PASS，普通新包原首页场景尚NOT_RUN，仍OPEN；不以自动结果关单。AUDIO-14正在稳定reading-units请求标识，独立原流程回归待执行。当前无测试服务，设备仪器已结束并强停；最新可恢复候选及接入边界见release-evidence首节。

2026-09-07新增确证显示缺陷：SYNC-04（RG-04/POS-01/07，P1）Android冷启动首页以已确认旧本地位置显示57%，而完整服务端C/r9及首页API均约16%；普通播放器恢复5015ms正确但不抵销首页失败。AUDIO-14（RG-03/AUD-X，P2）Chrome音轨列表离线错误后重连仍0轨/原始Failed to fetch，在线API1轨、reload恢复。原证据在9e017394/pos07-real-late-first-submit-20260907，详见release-evidence；两项OPEN，立即最小修复及原场景/必要相邻回归，不扩通用工具。POS-07真实首次C晚于N提交的协议与实际恢复窄组合通过；无整体GO或新范围决定。

当前下一项：POS-07真实客户端首次迟到C在N后提交，已有工具与Chrome/Android环境可执行，尚NOT_RUN；d58d0792的POS-05窄组合已经主与独立复核闭环，不重复扩展其测试工具。此恢复点覆盖下文历史“下一项POS-05”；外部阻塞和正式包暂缓保持。

2026-09-07 POS-05实际客户端证据缺口部分补齐：afe19dca Chrome普通MP3提交M/r4后丢实际ACK，Android普通播放提交N/r7，Chrome原body自动重试返回原receipt和当前完整N；GET确认不覆盖N、不递增revision，异payload409相邻通过，未发现新产品缺陷。仅此组合PASS，IDB清pending和5秒期限不由人工响应控制外推；其他引擎/原生方向及最终RC仍待验。服务、设备转发和浏览器已收尾，原件/源码/开发APK与用户15项改动核验通过，详见release-evidence首节；现有环境阻塞和正式包暂缓不变，仍R2。

2026-09-07 STATUS-01 CLOSED：f778eecf补齐资源已读字段投影并移除百分比对已读状态的覆盖；新隔离开发包真实M4B67%标已读→冷重开→取消均与API独立状态一致，完整位置不变，随后首页冷恢复20247→20247ms/923ms。原失败、必要针对性/完整Android及后端相邻、主与独立审查、实际新包和清理证据齐备，详见release-evidence首条；停止本缺陷工具完善。下一可执行项POS-05等异常缺口，既有环境阻塞/正式产物暂缓不变；未冻结RC、未整体GO。

2026-09-07 POS-04待分类观察已收尾：主与独立复核支持latest-only新capture覆盖，未发现retry自行改ID证据；实际持久/冷恢复/最终确认分别有效，原pending精确重放与r12/r13具体触发归因不作已通过声明。无需以该观察另立产品缺陷或继续扩工具。STATUS-01仍在修复，其余必测缺口和外部条件保持。

2026-09-07 STATUS-01 / RG-04 POS-11真实FAIL：Android普通M4B详情67%点击标已读，独立GET的book.completed/resourceCompleted均false→true，整个v5快照逐字段不变；详情仍“在读”，强停冷启重进仍“在读”。已定位原生详情进度投影以百分比重算completed及资源状态展示同类逻辑；不能用后端状态正确抵销UI失败。最小修复与针对性回归进行中，尚未关闭。原证据`180bb697/pos11-native-reading-status-20260907`已清理服务/设备；其余外部阻塞、正式包暂缓及未冻结RC保持。

2026-09-07 POS-10 API/Worker重启后Android M4B普通恢复15000→15000/988ms子项PASS；POS-04原生离线20226ms完整pending持久、冷恢复20247ms和最终r14一致已观察，但原pending mutation未上送、被新capture mutation替代的语义尚在分类，不能直接标原mutation重试PASS或已复现产品FAIL。原始DB/GET/receipt证据完整，服务和设备已收尾，独立只读追踪进行中。详情参数化ReadingUnit入口现为隐藏产品面，不因测试开启；仅播放器公开章节行为沿原矩阵验收。尚未冻结RC，现有外部阻塞/正式产物暂缓不变。

2026-09-07 AUDIO-13 CLOSED：582c81fc最小配置生命周期修复已在新独立开发包真实通过M4B播放中旋转、暂停旋转及普通注销停止相邻。原失败、自动检查、独立owner/安全边界审查和新包原场景证据齐备，详见release-evidence首条。不是放宽账号退出停止规则；无工具扩展。POS-09其余显式启动/引擎子项、POS-10服务重启等仍待验证，ENV-11/12、iOS/容器、正式包暂缓不变；未冻结RC/未整体GO。

2026-09-07 AUDIO-13（RG-03移动音频生命周期/RG-04 POS-09，真实FAIL，候选待回归）：Android普通M4B正在Playing15092ms时旋转，实际横屏返回首页，MediaSession变state0/position0；不是仅凭代码推断。MainShell配置重建销毁无条件停止Application持有的音频会话。候选仅跳过isChangingConfigurations期间的stop，账号/namespace和普通退出原停止行为保留，复用现有LocalActivity。旧包32d16edc原失败与完整服务证据位于58cff471/pos09-native-explicit-entry-20260907；新包真实旋转及注销相邻尚待验收，不关闭。播放器内部章节A10000→真实B14978/r7→冷启首页首次15000/959ms已通过，但不是已证明的携带chapterId显式启动重建。

2026-09-07 POS-10 MP3活动会话双端子项已补齐：Chrome实际重连收到15034ms远端更新仍停5054.691ms；Android原任务回前台收到34ms更新仍停15034ms；两端只有显式跳转才采用远端位置。证据与清理见release-evidence首条。未发现本场景产品缺陷，未扩工具；不关闭整个POS-10，服务重启/其他引擎及POS-09等可执行缺口仍待验收。当前无活动fixture，原用户工作树保留；未冻结RC、未整体GO。

2026-09-07 POS-06 Android晚ACK执行缺口已补齐：实际HTTP、独立SQLite、完整N/pending保留及owner/DB重建原mutation重试PASS，必要原online相邻9904→9904ms PASS；测试接入的编译/缺Compose宿主失败已分类、原日志保留并实际解除，未发现新业务缺陷。独立审查、源码/样本/安装包hash、配置/服务/设备清理见release-evidence。本次最小工具补口停止；不能把“现有工具没有入口”直接当外部阻塞，也不外推该用例到Chrome、socket丢包、其他引擎或SYNC-02。仍按矩阵推进未测异常，既有ENV-11/12、iOS/容器和正式产物暂缓保留，无整体GO。

2026-09-07 最新覆盖：SYNC-03已关闭。ead1ba20新库真实Chrome↔Android原场景：Web5000→Android5015ms、Android15000/r8→Chrome重载详情直接50%/0:15（尚未打开播放器），实际播放器恢复15000ms；完整服务端presentation含非空章节一致，原生正常详情相邻通过。原失败、针对性RED/GREEN、完整Web及后端相邻、独立审查、931项hash和服务/设备清理见release-evidence。停止该缺陷的工具完善。剩余可执行项为POS-04～10异常/生命周期缺口；ENV-11/12、iOS、容器及正式产物暂缓仍分项保留，未冻结RC、未整体GO。以下较早SYNC-03 OPEN/PARTIAL保留为历史。

2026-09-07 SYNC-03候选ffcbd4aa实际复验仍PARTIAL：新库M4B从Web5000ms交给Android确认15000ms/r8，Chrome fresh reload百分比50%正确，但当前收听退成书名。实际reading-units只有currentHref/percent，未携带完整v5 presentation，故不能关闭。该候选已停止并保留失败，继续沿现有投影owner补全服务端展示；不以百分比反算当前位置、不增加逐资源额外GET。

2026-09-07 SYNC-03（RG-04/POS-01，真实FAIL，候选待Chrome回归）：cff3e689普通交接中Chrome重载详情仍显示旧Web5秒，服务端已确认Android15秒，打开播放器后才纠正。owner为详情从getV5Progress无条件叠加已确认本地历史。ffcbd4aa复用既有pending身份读取，统一百分比/位置/继续资源投影并保留本页capture；原行为针对性RED、候选Web481及lint/typecheck/pretest通过，尚未关闭。当前独立fixture正在启动准备真实原场景；与SYNC-02启动ACK竞态无关，不改协调器。POS-07服务端首次迟到C、重放M和冲突保护已实测通过（e39e6de2）；客户端离线/受控并发顺序仍未覆盖。

2026-09-07 最新：M4B/M4A/AAC普通Chrome↔Android六个短时交接子项已通过，最大恢复偏差15ms；没有本轮业务/测试工具改动。当前新增待分类观察为Chrome详情重载后仍显旧位置，播放器打开后才刷新（正常恢复已确认正确），只读追踪进行中。证据在cff3e689/ordinary-audio-sync-20260907；fixture、浏览器测试账号和自有tab、设备播放与reverse均已收尾。前轮AUDIO-11/12关闭获独立证据复核支持。下一项为该显示现象的owner定位及其余进度异常/生命周期缺口；ENV-11/12、iOS、容器及正式产物暂缓仍独立保留，尚未冻结RC，未整体GO。

2026-09-07最新：AUDIO-11首页音频误路由、AUDIO-12详情错误能力提示均已关闭，原失败、必要自动回归、独立审查和f8847633新包真机普通原场景齐备。AAC首页强停恢复17380→17380ms；M4B/M4A三章导航及各自确认后强停恢复10000→10031ms通过。原样本/源码、安装包hash、原App不变与服务清理已核验，见release-evidence和f8847633/android-normal-ui-regression-20260907。无活动fixture/子代理/设备验收进程，新独立测试包保留；本批不再扩工具。下一可执行缺口为其余第一方跨端与异常组合，ENV-11/12工具拒绝、iOS、容器及暂缓正式产物分别保留；未冻结RC，不作整体GO。

2026-09-07最新恢复点f8847633：AUDIO-11/12最小修复、针对性原失败/自动回归及独立代码复核已完成；新独立开发APK c7c1fbed…已准备但尚未安装，原真机失败仍保留，两个缺陷保持待真实回归。没有运行中的fixture或子代理，设备旧验收包已强停保留，原App不动。下一项为新隔离库和新包普通首页/详情原场景及章节相邻，具体路径在release-evidence首段。ENV-11/12工具限制、iOS、容器与暂缓正式产物仍分项保留；没有整体GO。

AUDIO-12已完成最小呈现候选与针对性RED/自动GREEN，等待独立验收包真实详情复验；不是新增播放器能力或视觉重做。AUDIO-11/12均需保留原失败，下一候选整合后回归。

AUDIO-11候选代码及原映射/路由回归通过，真实新包首页原场景仍NOT_RUN；不能由详情恢复或host通过关单。下一步同一独立验收包增量构建并保留数据安装，验证首页音频恢复与相邻详情/章节。

2026-09-07最新恢复点：新增AUDIO-11（RG-03/04，FAIL，待修复）：真实Android普通首页在已确认四轨AAC进度17182ms/rev64、独立包冷启动后，“继续阅读”错误进入电子阅读器并报格式不支持。详情“继续收听”对照真实恢复17182ms/误差0，不能据此关闭首页入口。新增AUDIO-12（RG-03能力提示，FAIL，待分类/最小修复）：音频详情两次显示PDF/漫画原生渲染器未提供的无关提示。独立只读代理正在追踪入口owner和测试，未改业务源码。原失败UI、MediaSession与ORM见release-evidence最新记录及85662d5d/android-normal-ui-20260907。fixture与reverse已停清、源码/样本全匹配，独立测试包保留且强停，原App不动。下一项：修复首页恢复路由并真实原场景回归，继续原生章节；ENV-11/12、iOS/容器及暂缓正式包分别保留。

2026-09-07 AUDIO-10闭环：521e74ed真实Chrome原失败及切轨/同资产恢复/首轨自然接轨通过，SQLite/API详情与bootstrap分页一致性和相邻16 PASS；主核对原件/911应用源码不变、PUT22次200、无4xx/5xx、账号/服务清理。针对性契约测试与本条收尾记录一并提交，无活动fixture/子代理；下一项继续Android普通UI与剩余异常，既有环境阻塞/正式包暂缓不变。

2026-09-07 AUDIO-10新增确证：四轨详情自然文件名排序覆盖导入sequence_index，与bootstrap/播放器不一致，点击详情第二轨进入实际最后一轨的75%位置。候选仅让音频详情消费已有sort_order，图片排序不变；原单测错误期望已依据真实双端契约修正且原失败保留，代码/相邻通过，待SQLite双端及新Chrome原场景，尚未关闭。两M4B/M4A内嵌章节短时子项PASS；证据、原件/源码及清理见release-evidence。

2026-09-07增量：Chrome桌面M4B/M4A普通UI短时播放/拖动/关闭重开缺口已补齐，恢复误差1126.938ms/108.089ms，真实服务端持久化通过；本轮无新业务缺陷，未扩测试工具。9原件/911应用源码不变、账号退出和服务清理已核验。章节与四轨专用样本经子代理准备、主独立核对就绪，尚未执行客户端，不能关掉对应缺口。下一项为章节/多轨实际验收及Android普通UI；ENV-11/12、iOS、容器和正式交付暂缓保持。源码d62438f0，证据见release-evidence首节，最终RC未冻结。

R1 日期：2026-09-06。正在自主执行代码回归和确认缺陷；下方 R0 事实保留为历史线索，当前状态以下表覆盖。环境/决策解除后用例回到 NOT_RUN，不能直接改 PASS。

## R1 状态覆盖与外部条件

TEST-13本批关闭：eecff919仅将新增全局音频前置移至首次播放前，独立复核确认原断言保留，真实原用例恢复9905→9905ms PASS、编译及lint通过，原FAIL留证。MP3后台STOPPED持续确认、系统短暂焦点中断自动暂停/恢复亦有实际PASS（0b234f2d）；无本轮新增产品缺陷。所有自有fixture/仪器退出、专用数据与映射清理完成，详见release-evidence。停止相关工具扩展；普通UI、内嵌章节/多轨和其余进度仍未完成，iOS/容器/正式交付阻塞不变，不宣布音频全门禁通过。

TEST-13 / RG-03音频、RG-04 POS-01/02：新增系统音频活跃前置被放入每次openPlayer，在原MP3相邻测试已完成播放/暂停9913ms/关闭后，第二次打开触发RG04_EXISTING_SYSTEM_MUSIC_ACTIVE。此全局标志不能区分本fixture已使用的服务与外来播放，不应作为本fixture每次重开的前置；不是已复现的恢复产品缺陷，也不推定系统活跃的唯一来源。原失败保留于`5f75f35f/android-audio-lifecycle-20260907/original-adjacent/`。候选把新增隔离检查移到fixture首次获得播放前，保留每次已有App音频会话检查及所有恢复/确认断言；实际回归待执行。后台与focus原两子项已PASS，源为0b234f2d，不能混作修正后最终证据。

M4B短时原生缺口已补齐：独立.m4b入口真实播放/5、10秒确认及暂停重开PASS，误差0；没有新增产品缺陷。样本与M4A同hash，不能消除章节/复杂样本缺口。范围内后台/中断尚NOT_RUN，最小针对性测试编写中；停止条件/写范围见release-evidence。四种格式仅局部已验，尚非整组门禁PASS。

2026-09-07 DEC-09覆盖：负责人将有声书必测收敛为M4B、MP3、AAC、M4A四种格式。范围外的逐格式/逐编码缺样本或未测试不再构成本轮阻塞，保留真实历史结果；四种格式的既有必测操作、异常、进度和最终RC要求保持。Vorbis原尝试因子代理用量中断并达到fixture寿命上限，未运行仪器；恢复尝试随后按本次范围调整正常停止，也未运行仪器，不计产品失败或通过。实际清理见release-evidence最新记录。子代理用量已由用户告知恢复，重新安排只读核验；不新建分支。

最新原生增量：Android M4A/AAC-LC、Ogg/Opus真实运行时短时播放、5/10秒确认及暂停重开子项PASS，误差均0；无本轮新增产品缺陷。仅用既有fixture/仪器入口及导入前显式登记的样本准备，未扩工具；实际源/样本/配置/服务清理核验通过。证据为ac25497d环境及已核验开发APK，不替代主冻结RC、长时、多轨或普通界面全流程。READER-05/06/07浏览器回归、其他格式/异常、iOS/容器与暂缓正式产物继续分别保留。

READER-07 / RG-03 COM-*、RG-04 POS-09（RISK-07升级，应用边界已复现、真实UI待回归）：漫画详情第1页实际链接函数生成page=1而入口索引应0，6页末页对应索引应5；受控原失败留证，尚非真实点击后的错误引擎页。候选在唯一详情链接owner转换pageNumber→零基index，PDF及章节/音轨不变，针对性与完整Web/typecheck/lint/i18n通过。真实首/末页点选与恢复仍待验证，不关闭；证据见23ae8c2e/comic-detail-entry。下方原RISK-07静态记录作为历史保留。

RISK-07 / RG-03、RG-04 POS-09：独立审查指出漫画详情resource_details.pageNumber是一基数，resourceDetailItemHref原样传?page，而reader-v3-page.tsx的漫画入口按零基pageIndex解析。此为尚未实际执行的静态线索，需真实详情页逐页点选与首/末页对照；不直接登记为已复现、不全局重定义索引。与已复现READER-06控制栏分开验证。

当前覆盖：READER-04主资产识别/启动原缺陷已由`1d298ce6`真实production PDF/CBZ成功读页关闭，保留完整格式验收缺口。READER-05 PDF按钮导航、READER-06漫画零基索引与展示页号混用仍待真实回归。READER-06实际表现为第3页却标题第4页、目录0–5、末页上一页disabled，原现场在`1d298ce6/rg03-pdf-cbz-live/10..14-*`；候选仅修复控制栏索引和显示，不改Locator/保存协议。

ENV-12 / RG-03 READER-05/06：新增漫画Playwright回归命令在进程创建前被自动审批拒绝，原因仅“blocked by policy”；测试NOT_RUN，未产生自动RED/GREEN。现有真实失败保留，代码候选完整Web/typecheck/lint/i18n通过但不能据此关单。记录`artifacts/releases/1.0/1d298ce6/reader-console-regression/browser-start-rejection.json`；当前执行限制不通过换入口/子任务绕过，需现有浏览器命令的实际运行结果。ENV-11旧时序对照仍单独保留。

READER-05 / RG-03 PDF页间导航，P1，已复现：`1d298ce6`真实production Chrome的69页PDF可渲染首页，但底部“下一页”disabled；键盘可以到第2页，滑块可以到第35页。按钮错误依赖空目录的leftChapter/rightChapter而非PDF adapter分页能力；不是PDF解析失败。原证据`artifacts/releases/1.0/1d298ce6/rg03-pdf-cbz-live/03..06-*`。待复用现有分页命令修复按钮并完成无目录PDF原场景与EPUB/漫画相邻回归，不生成虚假目录，不扩展工具框架。READER-04的原启动错误已在production解除，整PDF仍FAIL。

READER-04 / RG-03 PDF、COM-CBZ，P1，待真实回归：69页正常PDF在Chrome真实全新导入后无法打开，提示缺少准确大小。只读实际库/repository及生成契约证明PRIMARY资产大小711671有效；Web仍按旧kind=CONTENT找资产。真实wire mock纠正后受控PDF和漫画双FAIL，候选改为bootstrap唯一owner选择PRIMARY、PDF引擎复用，原错误fixture同步纠正，大小/安全和流式保护不变。针对性及完整Web/typecheck/lint/i18n通过，实际PDF和漫画回归未完成，不能关闭。证据路径、原FAIL与环境限制见release-evidence最新恢复点；没有新工具/分支。

最新覆盖`7e207c38`：POS-03 Chrome两视口已确认MP3强杀并真实重登录恢复子项PASS（5892→5892ms、5862→6067.804ms），进程归属、kill前无close、kill后登录前完整IDB、服务端原ACK及实际引擎恢复均通过；真实cookie未保留/需重登及既有私有缓存清理作为限制保留。TEST-12已关闭，本子场景工具停止扩展，所有原失败继续留证。主及独立审查通过，8次运行源码/原件与清理复核通过，原相邻2 PASS。其他强杀阶段/引擎、跨端异常及格式继续；不代表整POS-03或RG-04放行。

POS-03本次401后的本地清理已实际复现，并与既有登录页401隐私清理路径一致；不是新的进度引擎失败证据。修正测试自身错误的“重登录后仍保留私有缓存”断言，改验既有清空契约，强杀前后IDB持久性及后续服务端/引擎位置要求不变。原`58a8923a` FAIL保留，仍待完整恢复结果；具体依据和停止条件见release-evidence首节。

POS-03当前实际限制：`a9bb694b`两视口已完成专用Chrome强杀并证明已确认IDB位置5668/5857ms完整保留，但首次GET401，真实播放器恢复仍未验证，不关闭该子项。保留原FAIL并通过现有同账号UI登录继续；只记录cookie是否存在等非秘密元数据，不推定401根因、不改产品认证。所有位置、mutation、revision、IDB和2秒恢复断言保留；原场景及必要相邻通过即停止工具完善。

TEST-12 / POS-03：`ef3dc979`首次实际production Chrome在setup进程归属核验失败，CDP `Browser.getBrowserCommandLine`明确要求`--enable-automation`。未登录/未强杀，不是产品恢复失败；专用context/profile与fixture已清理。当前仅给该专用Chrome增加此启动参数，保留CDP/CIM、创建时间和精确profile守卫；依据已安装Playwright 1.61.1协议声明及真实错误，不删除校验。DEC-07允许原因是当前必测项无法进入执行；停止条件为原强杀恢复实际通过及已抽取owner的必要相邻通过。原live/POS-04相邻已在`ef3dc979`分别PASS，新增原场景待重跑。

最新恢复点 `02d6ea2d`：POS-04 Chrome桌面/移动视口EPUB离线页面重建与重连子项已实际PASS（完整pending不变，ACK/本地确认/独立GET965ms及959ms，恢复第二章），原live生产相邻PASS，源码/样本/服务清理复核通过。测试仅服务该必测缺口，复用现有owner，达到停止条件；独立工作区首次生产构建被跨根依赖链接阻断的环境失败已留证，通过主工作区现成环境解决，未新增依赖/工具能力。POS-03进程强杀及其他异常/格式组合继续；ENV-11、iOS/容器及正式产物暂缓不变，未冻结RC，不作整体GO。

当前恢复点 `d19a7942`：MP3真实双向与原online相邻验证均已PASS，测试已整合，相关工具改动停止。AUDIO-07/08/09、TEST-11本批关闭；AUDIO-06原短时失败解除。下一可执行项为确认后进程重启、离线恢复以及其余实际格式组合。未冻结RC；ENV-11手动服务、原生iOS/容器及暂缓正式产物仍分别保留。下方“待相邻/暂未整合”均为前序记录。

TEST-11已关闭：当前生产Chrome原用例完整PASS，实际采样末点1805229.4ms、最大无推进/观察间隔116.3ms，恢复433ms误差；原件/源码、配置及服务清理核验通过。W→A与A→W的MP3正常交接已真实PASS（5857→5857；15749→15763.868ms），待原online相邻回归后整合针对性测试。其他格式/异常恢复仍未覆盖，SYNC-02 ENV-11仍待手动服务，iOS/容器/暂缓正式构建分别保留，不作整体GO。

最新覆盖：AUDIO-07/08/09已在主分支 `01ac165e` / `4f439b51` / `0ca6d1bb` 整合并关闭原捕获饥饿、串写、Stop迟到重启缺陷，测试 `b912b427`。两项真实竞态保留有效RED，新包同例GREEN；FLAC原5/10秒确认和8610ms重开、PCM10ms恢复误差均PASS，AUDIO-06原用例失败解除，不外推旧失败唯一根因。主代理核对diff/现场/hash/清理及独立复核完成，详见release-evidence首节。下方先前“候选未整合/FLAC仍FAIL/RISK-06待验证”均为历史。当前剩余可执行项为W↔Android同步、异常恢复及TEST-11完整时窗，ENV-11、iOS/容器和暂缓正式构建仍单独保留；尚无整体GO。

当前阶段R2（既有R1编号保留）：READER-03原问题关闭；AUDIO-05原AAC回零经新包真实恢复9906ms→9906ms及MP3相邻回归关闭，已整合 `9938c350`，长时/复杂VBR不外推。IMP-01正常两模式UI+同测试库只读持久化/拓扑子项PASS，原900秒退出和未存HTTPbody仍保留。AUDIO-06 FLAC仍FAIL；AUDIO-07受控捕获修复因新增跨资源writer风险RISK-06暂不整合，独立候选 `9df3d412` 待实际竞态与持久化验证。AUDIO-04原生产链PASS但TEST-11完整1800秒采样末段仍待补齐；尚未冻结RC。

新增AUDIO-05（AAC-LC，RG-03/AUD-04+RG-04/POS-01）：真实5/10秒确认及9911ms暂停通过，重开容差FAIL，瞬时恢复值未知。新增AUDIO-06（FLAC24-bit，RG-03/AUD-05+RG-04/POS-02）：首5秒确认期限FAIL，瞬时状态未知。均为尚待分类的必测失败，不能仅用finally后DB推断根因；只补既有断言前最小观测，各一次复验后转具体业务修复或真实环境结论。WAV同入口9955ms恢复PASS独立保留。

以上首次失败状态保留为历史，以首段及最新证据覆盖。RISK-06现已升级为AUDIO-08 / RG-04 POS-08真实串写：configureProgress提前替换active writer，B restore挂起时A暂停2507ms被写入B，A自己的持久化仍0；原始门控/实际Media3/SQLite证据在 `android-writer-identity-20260906/`，不是静态推断。原候选未整合。`9df3d412` 保留旧绑定直到新launch提交，完整host/lint通过；另 `567909e4` 修正stop漏取消local preparation，取消场景仍待实际回归。原失败、新候选同场景GREEN及必要相邻回归完成前，不关闭AUDIO-07/08，不扩测试框架。

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
| SYNC-03 | Chrome重载详情以已确认旧本地历史覆盖新远端位置；ffcbd4aa中间候选还缺完整服务端时间展示 | ead1ba20真实重载直接50%/0:15及同资产15秒恢复、原生详情相邻、针对性/完整回归与独立审查通过，已关闭；cff3e689和ffcbd4aa失败保留 |
| AUDIO-11 | Android普通首页继续已确认音频误进Reader；85662d5d真机原失败 | f8847633新包原首页强停恢复同AAC资产17380ms/误差0，针对性/相邻及独立审查通过，已关闭；M4B/M4A章节恢复相邻31ms |
| AUDIO-12 | 普通音频详情错误显示PDF/comic原生渲染器未提供 | 74098307复用主动作可用性owner；f8847633新包四轨和双单音频详情实际正常、独立审查及相邻保护通过，已关闭 |
| AUDIO-10 | Chrome真实四轨详情与播放器/Reader bootstrap排序不一致；04231cda原失败及持久化sequence_index见最新证据 | 521e74ed真实Chrome原场景/切轨/恢复/首轨接轨PASS；SQLite/API分页一致性及相邻16 PASS，主核验清理，已关闭；原失败保留 |
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
| DEC-02 / DEC-09 | RG-03 / AUD-* | 本轮验收仅M4B、MP3、AAC、M4A，记录实际容器/编码及Chrome/Android/iOS结果；平台缺执行条件独立BLOCKED，不因失败改预期 | 负责人已收敛格式范围；其他编码无须逐项验收，历史矩阵保留，不扩大为产品能力删除 |
| DEC-03 | RG-04 / POS-07 | 记录 ADR 0028 最后事务提交写入生效；离线首次迟到可能覆盖当前位置，是否符合 1.0 产品接受范围由负责人签收；若不接受另授权修复 | 待实测与签收，不引入新冲突算法 |
| DEC-04 | RG-04/RG-05 | release-gate.md 的保存间隔/确认延迟/音频恢复误差与性能建议阈值、机器预算、并发、数据分布、采样方法 | 待冻结；建议值不是实测值；失败后不得临时放宽 |

## 后续缺陷登记规则

后续确认缺陷应补：ID、Gate/Case、严重级别、平台/格式/账号角色、RC/产物、前置与最小复现、预期/实际、脱敏证据、修复 commit、原失败和相邻用例回归、关闭人/时间。状态为待复现→已复现→修复中→待回归→已关闭；证据可标自动失败/真机复现/压力复现。没有回归证据不能关闭。

门禁内硬要求失败无论 P0/P1/P2 均阻塞放行。延期只允许门禁外轻微问题且须负责人明确同意；本轮无已批准延期项。
