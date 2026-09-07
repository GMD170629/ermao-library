2026-09-08 READER-22 OPEN：Android漫画第4图切竖向连续实际回首页并保存，证据及最小定位见evidence首条。RTL方向/翻页子项已PASS；原偏好与隔离环境已收尾，正在定向修复，不重复已关闭方向测试。R2未冻结。

2026-09-08 POS-10普通Android EPUB回前台远端提示/不强跳/显式跳转子项PASS，完整UI与持久位置证据见evidence首条/cb623422结果；无业务/工具改动。下一项漫画普通方向设置既有缺口，R2未冻结及其他限制保持。

2026-09-08 POS-08普通Android账号/服务器取消隔离子项关闭：本轮跨服在途前置PASS，证据与共享owner覆盖边界见evidence首条。无需按PDF/Comic重复同一取消路径；其他POS、Chrome/iOS与最终RC不由此覆盖。下一项POS-10 Reader活动正文远端更新；R2未冻结。

2026-09-08 POS-08 Android普通Reader关闭在途保存后切账号取消隔离子项PASS，无新业务缺陷；原UI/完整位置/清理见evidence首条与e76fefb8结果。音频切账号已PASS，下一项切服务器既有入口；POS-08整体PARTIAL、R2未冻结及其他阻塞保持。

2026-09-08 POS-08 Android普通音频在途切账号取消隔离子项PASS，无新业务缺陷；完整A/B位置、注销94ms取消及清理证据见evidence首条/542f8d13结果。下一项Reader关闭独立路径；POS-08整体仍PARTIAL，R2未冻结与其他阻塞保持。

2026-09-08 RG-03 Android EPUB普通主题切换、M4A→M4B自然接轨子项PASS，无新缺陷/工具；证据bd65dd4a两目录result.json及evidence首条，专用环境已收尾。READER-20/21已关闭；下一项POS-08既有普通在途切账号入口核对。R2未冻结及其他阻塞保持。

2026-09-08 READER-21 Android原普通字号增减及正常重开CLOSED（69a5ba15），原件不变/18px偏好与专用环境已收尾；证据233ca471/txt-font-20260908/final/result.json及evidence首条。READER-20已关闭，R2未冻结及其余真实阻塞保持。

2026-09-08 READER-21最小字符锚点候选定向真机/编译PASS，原普通字号增减及重开最后复验中，仍OPEN；测试前置修正及真实拒绝候选保留，详见evidence首条。READER-20 CLOSED与R2未冻结/其余阻塞保持。

2026-09-08 READER-20 Android原普通目录往返CLOSED（d2f996d5）；READER-21原普通字号路径仍失败/OPEN，不能用仪器绿替代。证据及最小差异定位见evidence首条与233ca471/txt-font-20260908/green/interim-result.json。R2未冻结及其余阻塞保持。

2026-09-08 READER-20目录最小候选定向真机通过；READER-20/21均待普通原UI复验才关闭。实际失败候选、SDK就绪依据和原回归结果见evidence首条；无工具扩展，R2未冻结。

2026-09-08 READER-21 字号语义位置候选定向真机/原TXT相邻和编译通过，原普通UI待复验；READER-20仍OPEN。新增两项最小回归的必要性、真实红/绿结果及停止条件见evidence首条，未扩工具。R2未冻结，其余阻塞保持。

2026-09-08 RG-03 Android MP3真实连续30分钟、暂停确认及同进程runtime重开子项PASS（5388c1fd/a1040b09），完整时钟/位置/hash及清理证据43f75b02/android-audio-soak-20260908/result.json，详见evidence。不外推普通UI长时、其他格式/多轨或最终RC。下一项POS-01 TXT改字号后的章内语义位置及正常重开；R2未冻结与其余阻塞保持。

# 1.0 发布验收矩阵

2026-09-08 AUD-02 Android普通MP3 1.5×及恢复1×子项PASS；AUD-X实际MP3 ID3章节35s越过约30s音轨的解析拒绝/真实导入隔离/普通失败详情子项PASS，原件不变。证据0a8e7da3/android-audio-rate-20260908及audio-chapter-bounds-20260908/result.json，详见evidence；不外推全部倍速/容器异常或最终RC。

2026-09-07 POS-02 Android连续捕获增量PASS / SYNC-07 Android CLOSED：937b325b真实PDF 5/10秒SQLite新capture及普通UI持续HTTP确认通过；EPUB/CBZ连续操作相邻及三者最终完整local/server一致、pending空通过。具体计时、稳定副本限制与证据见release-evidence首条；不外推Chrome、iOS或最终冻结RC。此前PDF失败作为RED保留。

2026-09-07 POS-02 Android PDF连续捕获FAIL，登记SYNC-07：48次真实翻页约12秒，截图正文变动但本地/HTTP均35/r22，超过5秒上限；串行保存候选待编译/原场景验证。证据99d3e63b/reader-capture-windows-20260907，详见evidence。此前早退、pending恢复子项证据保留但不计本项通过。

2026-09-07 POS-02/03/04 Android CBZ子项PASS：显式下载，第5页r8→停API读4→完整pending/local跨强停及离线冷开一致，实际同第4页图像；恢复服务并回前台后原mutation唯一r9、完整载荷hash一致、pending空。随后第5页1.391s内退出并观察r10，设备完整位置一致/confirmed10/pending空。证据0de4d4fb/comic-pending-cold-20260907，计时/范围详见evidence；另端UI、连续捕获窗口、iOS/最终RC未覆盖。

2026-09-07 POS-02/03/04 Android PDF子项PASS：显式下载后35/r16→断服务读36→完整pending/local跨强停一致→离线冷开实际36；恢复服务原mutation唯一r17且载荷hash匹配，最终r20完整位置一致/pending空。早退35页2.515s内关闭并观察r21，设备confirmed21/pending空。证据a5d59625/pdf-pending-cold-20260907，观察偏差、时限与范围见evidence；不覆盖另端UI、连续捕获窗口、iOS或最终RC。

2026-09-07 POS-02 Android EPUB早退子项PASS：真实翻到第一章后2.469s点击关闭，2.484s观察到服务端r20完整位置；首页返回及本地confirmed20/pending空、完整位置一致。详见7c0baabb/epub-early-exit-20260907/timing.json和evidence；不外推5/10秒连续捕获或其他引擎/最终RC。

2026-09-07 POS-03/04 Android EPUB增量PASS：服务器第一章r17、设备离线第二章pending，完整local+sync跨强停一致；断服务冷启经已下载入口实际第二章。恢复服务并回前台重试后r18最新capture的完整位置与本地一致、pending为空、唯一receipt；旧pending在重开被新capture替代，原body重放不作PASS。详见c78a192d/epub-pending-cold-20260907及evidence；不覆盖纯服务恢复自动重试期限、另一端UI/iOS/最终RC。

2026-09-07 POS-09 Android EPUB内部目录后旋转/冷重开子项PASS：目录A第一章→B第二章确认r12→横屏/竖屏→强停冷首页继续仍B，独立HTTP r15完整Locator与r12相等。证据ed009144/pos09-epub-external-20260907/result.json，详见evidence。详情章节预览现有隐藏、外部启动参数路径NOT_RUN，不以此扩功能；iOS/其他引擎/最终RC仍待。

2026-09-07 RG-04/POS-04 Android EPUB可恢复查询失败重开子项PASS，SYNC-06 Android CLOSED：ebb4e3ea普通开发包，服务端r9第二章与设备confirmed9/pending=null前置核实后停API；普通继续仍第二章50%，关闭后本地Locator保持。证据ebb4e3ea/epub-offline-fix-20260907/result.json；首次可读观察10.657s（含网络失败等待），不外推其他格式UI、iOS或最终RC。iOS同类静态风险单列待处理。

2026-09-07 REF-EPUB active内容/原件重开子项PASS，TEST-15 CLOSED：9120453e Android生产实现未改，既有仪器方法补危险链接实际触发、原/parent执行标记、危险节点、样本请求/存储及原件重开断言后真机通过；普通首页进入第二章、点击链接后仍可读，确认r5完整第二章位置再正常重开同章50%。原件hash不变。证据9120453e/epub-active-20260907，详见evidence；不外推其他样本、iOS、全局网络捕获或同冻结RC。

RISK-10 待核实（RG-04 EPUB服务中断重开）：首次重开与本轮600s隔离服务到期退出重合，loading后曾显示首章；当时未在关闭前独立确认第二章位置，不据此认定已确认位置丢失，也不能用随后干净在线重开PASS关闭该观察。原图reopened.png/reopen-state.xml和api.log保留。下一项用现有入口固定已确认第二章后仅复测服务不可达重开，区分启动/同步时序与测试环境；不新增通用工具。

2026-09-07 READER-17 Android原失败CLOSED：归档预检IO/解码异常改用既有EPUB.RESOURCE_INTEGRITY，保留拒绝与cause；39B非ZIP及24B截断ZIP定向先FAIL后PASS，原路径/链接风险、容量及正常归档相邻全通过。新普通APK打开/重新获取损坏EPUB均为既有格式解析失败提示（PUBLICATION_CORRUPT映射ParseFailed），不再误报活动内容；同PID28438正常EPUB首章可读，坏资源进度/receipt均0。iOS同源修复已提交682b2679但ENV-02未编译/未执行。停止本分类问题扩验；下一项EPUB active正文/缓存重开及必要现有副作用用例，未冻结RC。

2026-09-07 READER-16 Android原失败CLOSED：9267a034普通开发APK实际打开安全DOCTYPE、可隔离external entity均保留正文，后者显示字面量&canary;；正常FB2相邻可读。测试canary未出现在正文，三个服务端原件及样本hash不变，同PID25985无所捕获崩溃。停止本缺陷Android扩验；iOS候选仍ENV-02待编译/真机，未声明整体原生放行。下一项EPUB损坏/active内容既有入口；原五项Chrome候选保持，未冻结RC。

2026-09-07 READER-16候选定向回归通过，原界面仍待：复用ReaderSafetyFacade XML准备及平台已有解码器，清理声明后交给原解析器；保持原件、预算和外部解析禁用。Android FB2 factory 11/11、shared 9/9、EPUB安全相邻10/10通过；iOS适配与针对性测试已修改，ENV-02下未编译/未执行。未改契约或通用测试工具。新普通APK及DOCTYPE/entity原失败复测为下一项，READER-16保持OPEN，未冻结RC。

2026-09-07 REF-FB2增量PASS：普通Android合成可辨识PNG、表格/诗行/嵌套正文、脚注往返与截断打开/重试拒绝、同库正常恢复已实际验收，失败资源无进度。证据ee5f3b15/fb2-complex-20260907，详见evidence首节；不外推实体/active内容安全、W/I或最终同RC。

2026-09-07 REF-AZW3精确锚点增量PASS：Android现有KF8三级目录在字号30px/大行距横屏形成实际分页，卷一根节点与细目甲fragment分别显示卷首/叶正文，root2-selected与leaf2-body图像及XML对应；证据8b80eacf/kf8-anchors-20260907，详见evidence首节。仅此同章跨页子项，无业务/工具修改；其他复杂内容/异常、W/I与最终同RC仍待。

2026-09-07 MOBI-X普通Android错误反馈及READER-15集成验证PASS（3cf54116，无新增业务修改）：真实DRM、96B截断、坏偏移分别明确受保护/内容损坏；DRM重新获取仍拒绝，关闭后同库正常MOBI正文可读。三种失败进度均null，坏偏移前后同PID18255且无崩溃，停止本缺陷扩验；其他格式/锚点与原五项Chrome候选保持，未冻结RC。

2026-09-07 MOBI-X原生检测/错误映射增量：READER-15坏偏移崩溃修复并经真机原失败及正常语料相邻PASS；真实DRM/截断后端读取明确422、同级正常200。仅native/HTTP层，普通错误UI与其他平台未覆盖；详见evidence。

2026-09-07 Android MOBI6/KF8普通阅读子项PASS（6f73ef35，无新增确证业务缺陷）：三份原始fixture正常入库READY；MOBI6三章正文/目录显示，KF8三个独立章节正文、三级目录层级和卷二目标阅读，确认r5后强停/冷首页33%继续恢复卷二且完整position与r6一致；KF8内嵌PNG/JPEG实际显示。详见evidence首节。MOBI/AZW3不再整体按缺样本阻塞；AZW/PRC独立来源、复杂锚点/异常/其他平台仍待，未冻结RC。

2026-09-07漫画预算增量：Android既有超页字节隔离/高压缩比拒绝及正常RAR相邻PASS；真实10000页CBZ新库导入/普通打开/末页完整确认与10001页导入拒绝/不可读界面PASS。重复小图仅作容量，不外推视觉/性能/其他平台或最终RC，证据d7ab754f/comic-budgets-20260907，详见evidence。

2026-09-07 RISK-09：真实Android ARM64归档引擎加密/截断检测码前后及共享分类定向验证已闭环，具体层级/限制见evidence；不据此覆盖普通新APK异常界面、iOS或完整格式矩阵。

2026-09-07增量：COM-CBR/COM-RAR真实加密和截断导入失败隔离、正常同级6页Android首图子项PASS；IMPORT-04普通详情误报无权限已修复且真机原/相邻闭环。仅此范围，不代替原生异常archive直接打开或iOS；证据da46248a/rar-exceptions-20260907，详见evidence。

2026-09-07 PDF-X页数边界增量：Android真实20000页首末及末页完整确认PASS；ef29559b普通20001页已下载打开/重试正确PDF_PAGE_LIMIT、无v5进度，READER-12错误映射已CLOSED，详见evidence。合成空白内页不作真实复杂巨书性能，未外推Web/iOS或PDF全部异常；下一项漫画异常，未冻结RC。

2026-09-07 RG-03 AUD-X / RG-04 POS-01/07显示缺陷回归补齐：SYNC-04新Android冷首页及详情正确采用服务端C约16%（不再被已确认旧N约57%覆盖），普通首页实际恢复5000→5015ms/969ms；AUDIO-14 Chrome真实离线拖动和重连均保持1条音轨/无Failed to fetch，定向Chrome E2E实际PASS。两缺陷CLOSED，证据见b72b3d83/sync04-audio14-regression-20260907及release-evidence；RISK-08后续已确证并按SYNC-05在e8c4b555关闭，实际定向真机证据见evidence，不外推其他引擎/iOS/最终RC。

2026-09-07 POS-07真实首次迟到子项PASS（9e017394业务源码同f778eecf）：Chrome离线C=5000ms网络发送失败，Android确认N=17298ms/r8后强停；只读ORM确认C尚无receipt，Chrome重连原body首次到达成为C/r9，旧8条receipt逐字段不变且仅新增C，独立GET完整相同。Android随后普通继续实际恢复5015ms/968ms。另发现SYNC-04首页显示旧57%而API16.6295%，以及AUDIO-14 Chrome音轨列表重连后仍Failed to fetch/0轨；两问题未关闭，不将正常恢复外推为显示通过或整体POS-07。双端受控并发事务排列、其他引擎/iOS/最终RC保持未验。

2026-09-07 POS-05增量：afe19dca Chrome MP3真实M提交丢ACK→Android新N→Chrome完全相同M重试子项PASS，receipt仍M/r4、当前完整快照N/r7、无新增revision；同M异payload409且N不变。Chrome保留暂停5s并提示远端34%，没有自动seek。详见release-evidence首节；未直接检查IDB或测5秒时限，不覆盖其余引擎/原生方向/iOS或同冻结RC。

2026-09-07 RG-04/POS-01详情与恢复相邻增量：SYNC-03在ead1ba20实际关闭。新库M4B Web确认5000→Android5015ms；Android确认15000/r8→Chrome重载详情在播放器未开时直接50%/当前收听0:15，随后实际恢复15000ms。完整presentation及非空章节由独立GET/reading-units核验；原生正常详情相邻通过。证据`artifacts/releases/1.0/ead1ba20/sync03-complete-20260907/`，原cff3e689/ffcbd4aa失败及清理在release-evidence。仅上述开发验证子项PASS，不覆盖POS-06真实ACK竞态、全部异常/格式或最终RC。

2026-09-07 RG-04 正常交接增量（cff3e689 Web/API、f8847633 Android）：M4B/M4A/AAC 的 Chrome→Android 分别5000→5015/5015/5000ms；Android→Chrome分别15000→15000、15000→15000、15039→15039ms，六个短时子项PASS。通过实际普通UI与独立GET核验，同资源/资产且两端clientId不同；详见release-evidence最新记录。既有MP3结果保留，四格式正常交接有开发证据，但异常组合、iOS和最终RC仍非整体PASS。详情重载旧位置另行追踪。

2026-09-07真实新包增量f8847633：AUDIO-11/12已关闭。Android普通首页AAC第四轨确认后强停冷启恢复17380→17380ms；M4B/M4A各自三章列表/上下章与确认后强停恢复10000→10031ms、第二章显示均PASS。详情正常收听可用且无无关能力提示。只覆盖上述已确认/短时/普通入口子项；离线未确认、其他异常、长时/全部边界和iOS仍未由本轮覆盖。证据、输入身份、原失败及清理见release-evidence最新记录。

2026-09-07候选增量f8847633：AUDIO-11首页进入播放器和AUDIO-12详情可用性提示已有修复与自动回归，独立开发包已准备；实际新包原场景仍NOT_RUN，故原Android普通UI FAIL尚未关闭。章节普通UI继续待执行，整体五Gate与最终同RC状态不变。

2026-09-07 Android普通UI增量（85662d5d）：四轨AAC确认17182ms/rev64，独立验收包强停冷启后的首页“继续阅读”FAIL_AUDIO-11（误入电子阅读器）；同一状态从详情“继续收听”恢复到实际17182ms，误差0ms，仅该对照子项PASS。普通音频详情无关能力提示FAIL_AUDIO-12。M4B→AAC实际系统回调确认自然接轨，不外推所有边界/长时。原生章节普通UI仍NOT_RUN，不能由此前runtime或Chrome证据替代。原件/源码/清理和失败证据见release-evidence最新记录。

2026-09-07 AUDIO-10已关闭：521e74ed Chrome原四轨详情/播放器顺序一致，指定轨播放、切轨、AAC同资产恢复（误差1097.585ms）和MP3自然结束自动进入M4A子项PASS；SQLite/API双端分页相邻16 PASS。原失败保持在04231cda证据目录，原件/源码/清理已核验。仅上述桌面短时子项通过，不代表多轨全部边界/长时/原生/异常或最终RC。

2026-09-07章节/多轨增量：04231cda Chrome M4B/M4A三章显示、列表跳转、上下章与重开恢复子项PASS，误差1133.828ms/132.305ms。首次四轨目录真实验收FAIL_AUDIO-10（详情与播放器顺序不同），候选代码回归通过、实际新候选待回归，不能将多轨标PASS；原失败和清理见release-evidence最新记录。

2026-09-07 AUD-01/POS-02增量：Chrome桌面普通详情/播放器入口的M4B与M4A短时播放、滑块定位、关闭重开子项PASS（d62438f0），15s确认位置恢复偏差1126.938ms/108.089ms；真实PUT与最终ORM、媒体206、原件/源码及清理已核验。相同30s音频字节分别导入，不代表两个编码，也不覆盖精确5/10秒时窗、章节、多轨或最终RC。章节与四轨样本仅准备并独立核对，客户端仍NOT_RUN，下一步继续。证据见release-evidence最新记录。

2026-09-07 Android后台/中断增量：MP3在Activity实际STOPPED且不回前台时完成5/10秒与暂停服务端确认；真实短暂音频焦点中断自动暂停、释放后自动恢复并确认，两子项PASS（0b234f2d）。新增前置误用TEST-13修正为首次播放前检查，eecff919原在线重开9905→9905ms回归PASS；原失败保留。仅对应这些运行时子项，不覆盖锁屏/真实来电/普通界面/其他格式或最终RC；证据、源码和安装测试APK分别见release-evidence最新记录。章节、多轨及其他进度异常仍待执行。

AUD-01 M4B新增Android真实短时子项PASS（2026-09-07）：`.m4b`独立导入/播放、5/10秒确认及暂停9912ms→重开9912ms；原件与M4A同hash，仍缺带章节/长时/多轨和普通界面完整验收。证据见release-evidence最新记录；共用后台/中断针对性用例待执行，不由短时结果覆盖。

2026-09-07 DEC-09最新范围：有声书仅M4B、MP3、AAC、M4A四种格式参加本轮验收。AUD-01中的M4B/M4A、AUD-02、AUD-04及这四格式的AUD-X/进度用例继续；其他格式和额外编码组合移出本轮必测，历史通过/失败原样保留，不伪填PASS。后台、中断、长时、多轨、异常、阈值与平台/最终RC要求不变。下方较早“其余格式待逐项验证”的描述仅为历史，不能重新增加本轮阻塞。

Android增量（ac25497d及已核验开发APK）：AUD-01 M4A/MPEG-4 AAC-LC单声道30s、AUD-08 Ogg/Opus单声道30.0065s的真实运行时播放、5/10秒确认及暂停重开子项PASS，分别9899→9899ms与9909→9909ms；不扩展到M4B/M4R/ALAC/Vorbis、长时/多轨/后台或普通界面完整入口。每项独立新库与8个真实样本，原件/源码/配置/清理通过，详见release-evidence首节。

READER-07增量：漫画详情页指定页链接边界实际复现一基/零基偏移，最小候选及CBZ/IMAGE_DIR首中末页、PDF相邻回归通过；真实点击后页面与POS-09仍未完成。PDF/漫画整体仍FAIL/待回归，不能用本次链接单测替代ENV-12浏览器验收。

最新覆盖：`1d298ce6`真实PDF/CBZ主资产启动失败已关闭READER-04；PDF69页的目录无关翻页按钮、CBZ6页的页号/末页上一页分别新增READER-05/06，故两格式整项仍FAIL。两个候选共用控制栏现有owner修复，完整Web/typecheck/lint/i18n通过；浏览器回归命令被自动审批拒绝（ENV-12），不得标PASS。真实CBZ退出重开第6页通过，不外推全部恢复/缩放/方向。运行清理、原件与源码hash已核验，证据见release-evidence首节。

`1d298ce6`生产Chrome：PDF69页首页、键盘第二页和滑块第35页已有实际证据，原READER-04启动失败解除；无目录PDF的底部下一页disabled，新增READER-05，故PDF正常用例仍FAIL。漫画相邻运行中，待完整结果与清理核验。

2026-09-06增量：RG-03 PDF正常69页Chrome真实导入后打开FAIL，登记READER-04；COM-CBZ相同PRIMARY契约选择错误在受控真实wire回归复现。基于3d798902的候选已通过针对性和完整Web静态/单元检查，真实PDF及漫画相邻待复测，不填PASS。样本SHA、真实UI、只读资产事实和RED/GREEN日志见release-evidence最新恢复点；不能据此声称复杂/异常或原生平台完成。

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
| INI-01 / RG-02 | P1/P2；新库；正常 EPUB+MP3 | Web 打开首次设置、创建管理员→登录→新增根目录→继续导入→列表/详情→三端阅读/播放 | 无默认管理员、手改 DB；初始化至可读闭环顺畅 | 3a1e4193/rg02-ui-intake-20260907/run/；见evidence | PARTIAL：Chrome真实新库普通初始化→入库→EPUB正文/MP3播放与保存PASS（development）；原生及最终同RC仍待 |
| INI-02 / RG-02 | P0；无权/不存在路径、重复请求 | 设置重复提交；普通账号访问设置；新增坏路径，修正后重新提交/导入 | 重复初始化和越权正确失败；路径反馈明确，修正可恢复 | fd26b7aa/rg02-fresh-api-boundaries-20260907/；3a1e4193/rg02-ui-intake-20260907/run/ | PARTIAL：真实API无效/重复setup、member403及重复库409通过；Chrome空表单、坏根修正和重复根可见错误已PASS；Windows真实无权根拒绝/无写入及恢复权限后建库导入PASS（644b3fef，20e7246c/unreadable-root-20260908/green/result.json，IMPORT-05 CLOSED）；Android普通成员管理入口隐藏及切回管理员恢复PASS（73031b2e/android-member-ui-20260908）；Chrome普通用户UI及最终RC仍待 |
| INI-03 / RG-02 | P1；INI-01已完成 | 记录账号/书库/任务/已确认位置，受控重启当前版本服务，再登录与重开 | 新数据持久化，无再次初始化或已确认数据丢失 | artifacts/releases/1.0/fd26b7aa/rg02-fresh-api-boundaries-20260907/ | PARTIAL：1e223e5e真实API重启后owner/library身份保持、setup仍关闭；既有M4B进度服务重启见POS-10；任务恢复及最终同RC仍待 |
| IMP-01 / RG-02 | P2；FLAT、VOLUMES 各独立根 | 按 UI 分别建库、扫描根文件与含子目录书籍；对照预期清单记录目录和独立资源身份 | 两正式模式 Book/Node/Resource/Asset/页轨计数与层级正确 | E/organization-live/imp01-ui-1788695317426/；database-readback-complete.json | 正常两模式UI+同库持久化/拓扑子项PASS；命令超期/HTTPbody未存见证据，不计最终RC |
| IMP-02 / RG-02 | P2；中英名、空格、特殊字符、多层、图片/音频目录 | 导入后进入每层，切换排序/分页，打开图片目录与多轨音频 | 不乱码、不漏资源、不用资源数决定页面类型；正常播放/阅读 | 66446a45/imp02-special-paths-20260907/ | PARTIAL：Chrome特殊路径/多层TXT、24本排序分页、图片目录解码及两轨MP3入口通过；图片目录标题IMPORT-02候选待普通UI复验；MEDIA-02封面500已CLOSED（c4f45456实际冷缓存HTTP回归）；其他平台/复杂布局另计 |
| IMP-03 / RG-02 | P2；合法+损坏/DRM/无权文件混合 | 隔离根扫描；使外部元数据不可达；核对任务错误与同级合法资源 | 错误隔离可解释，基础入库/已可读内容不被拖死；源文件不变 | e8c4b555/rg02-mixed-import-20260907/cbz-run/；详见evidence | PARTIAL：真实损坏CBZ失败隔离、合法同级READY、原件不变及修复重扫PASS；真实RAR5正文/头加密和256B截断失败隔离、正常同级6页READY/Android首图PASS，IMPORT-04详情误报已关闭；真实外部元数据搜索拒连502、已有原件可读及默认新TXT导入READY子项PASS（7ae823d3/metadata-unavailable-20260908）；96B截断MP3失败隔离/正常同级READY及原件不变PASS；Android错误详情IMPORT-06原场景7ac595aa已关闭（cc2579dc/audio-corrupt-20260908/green）；单文件NTFS拒读隔离/合法同级/恢复权限后同身份重扫PASS，错误路径泄漏IMPORT-07已关闭（43f75b02/file-permission-20260908/green）；其他DRM/自动整理重试及其他客户端错误UI仍待 |
| IMP-04 / RG-02 | P2；IMP-01源保持不变 | 记录文件hash/拓扑/进度→再次手动扫描→对账 | 不重复不丢失，未变文件进度保留 | local-load/measurement-20260906-065525/rescan-integrity.json；详见evidence最新记录 | FLAT历史原件/拓扑/进度保留与66446a45真实VOLUMES手动API重扫子项PASS：24本、33节点、27原件及完整TXT/MP3进度不变；普通UI看任务完成，非UI发起。最终同RC待，不重跑大库 |
| IMP-05 / RG-02 | P2；仍有真实待处理任务 | 扫描活跃时受控服务重启→查看队列→继续导入/安全重扫 | 任务可恢复、有进展、不永久卡住；不要求新暂停接口 | e8c4b555/rg02-worker-live-restart-20260907/；详见evidence | PARTIAL：真实RUNNING中断→新Worker标记WORKER_INTERRUPTED→同库安全重扫512资源READY通过；HTTP/UI入口及最终同RC仍待 |
| IMP-06 / RG-02 | P2；专用可写/只读根，测试文件 | Web 上传→文件详情；使用已有增删改入口；坏文件修正后资源重扫/继续导入；分别观察自动扫描和手动扫描对缺失项处理 | 仅授权显式写操作变动测试源；自动保留缺失、手动成功完成后按既有语义清理拓扑；失败可重试 | artifacts/releases/1.0/e8c4b555/rg02-source-rescan-20260907/；rg02-mixed-import-20260907/cbz-run/ | PARTIAL：真实Worker自动保留、缺失失败不误删、恢复/损坏CBZ修复同身份重扫、手动清理PASS；上传UI/只读权限及同RC仍待 |
| CON-01 / RG-02 | P1；W/A/I × HTTP/HTTPS/自定义端口 | 逐地址添加服务器/登录，浏览与读听；HTTPS经受信任代理；非信任证书走现有显式流程；公开链接检查 | 合法配置可连接；无默认关闭TLS；冷/热启动均不依赖localhost | E/CON-01/；987ece6b/android-server-switch-20260908/ | PARTIAL：Android自定义HTTP端口双服务器登录/身份及B冷启动子项PASS；非信任TLS默认拒绝/取消/显式接受/冷启动子项PASS（f936f99f/android-tls-20260908，版本边界见evidence），CONNECTION-01已闭环；Android无localhost依赖的真实LAN登录/冷启动/书库/MP3及EPUB读听PASS（873c2a50/android-lan-20260908）；受信任HTTPS/代理缺外部入口BLOCKED，Web公开链接另待，iOS ENV-02 BLOCKED |
| CON-02 / RG-02 | P1；管理员、普通账号、两个服务器 | 错密码→修正；服务端使会话失效后重登；切账号/服务器再取无权资源 | 错误反馈正确、权限重验，数据与会话不串用 | 3a1e4193/rg02-ui-intake-20260907/run/；5b538f2a/rg02-account-server-scope-20260907/isolated-cookies/；此前API见evidence | PARTIAL：Chrome普通错误恢复、真实双API跨服cookie隔离、member授权/撤权读写及禁用旧会话通过；Android普通账号切换权限展示/各自首页进度子项PASS（73031b2e/android-member-ui-20260908）；Android退出后跨服务器重登A→B→A及B冷启动子项PASS（987ece6b/android-server-switch-20260908）；Android服务端旧会话失效/错密码/重登/冷启动及完整进度保持PASS（362133f6/android-session-revocation-20260908）；普通注销后在途跨服重登另见POS-08/6af47724 PASS；保持登录切服未接普通导航；其他权限边界仍按实际证据，iOS BLOCKED |
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
| REF-EPUB | EPUB-N：真实章节；EPUB-C：嵌套目录、图文、非平凡布局 | W/A/I；P2 | R，正文/目录/锚点均正确 | EPUB-X：损坏包、active markup可恢复、具体外部实体风险 | PARTIAL：Android reader-v2普通打开/翻章/确认后强停恢复PASS（00563daf/android-epub-normal-20260907）；Chrome新库正文见3a1e4193/rg02-ui-intake-20260907；复杂/异常仍待，iOS BLOCKED |
| REF-MOBI | MOBI-N/C：实际MOBI7与复杂PalmDB/图片目录 | W/A/I；P2 | R，libmobi原格式内存出版物可读 | MOBI-X：截断/DRM | PARTIAL：6f73ef35 Android真实MOBI6普通三章正文/目录显示PASS；3cf54116真DRM/截断/坏偏移普通错误UI与无位置写入PASS；复杂跨页锚点/其他异常及W/I仍待，详见evidence |
| REF-AZW | AZW-N/C：独立实际AZW来源与内部变体证明；不只MOBI改名 | W/A/I；P2 | R，实际变体按承诺可读 | AZW-X：DRM/损坏 | BLOCKED；ENV-06、RISK-02 |
| REF-AZW3 | AZW3-N/C：实际KF8、复杂章节图文 | W/A/I；P2 | R，目录/跨章/锚点正确 | AZW3-X：损坏/DRM | PARTIAL：6f73ef35 Android KF8三章正文/层级目录、卷二确认后冷恢复与内嵌PNG/JPEG显示PASS；精确锚点/其他复杂异常及W/I仍待，详见evidence |
| REF-PRC | PRC-N/C：实际PRC/PalmDB与复杂资源来源证明 | W/A/I；P2 | R，不能由改扩展名证明全部变体 | PRC-X：截断/DRM | BLOCKED；ENV-06、RISK-02 |
| REF-FB2 | FB2-N/C：多section、嵌套目录与内嵌图片 | W/A/I；P2 | R，文本/图像/章节正确 | FB2-X：坏XML、可恢复active/具体实体风险 | PARTIAL：READER-08已CLOSED；原前置标题/嵌套目录见bea858b9/android-fb2-20260907；ee5f3b15/fb2-complex-20260907补齐Android图像/表格/诗行、脚注往返与截断拒绝/正常相邻PASS；其余安全异常、W/I及最终RC仍待 |
| REF-TXT | TXT-N/C：中文UTF-8、BOM UTF-16LE/BE、GB18030、混合换行、长章 | W/A/I；P2 | R；逐实际编码登记，不能一份英文UTF8代替 | TXT-X：损坏/超预算，失败类别正确 | PARTIAL：9cb26b94 Android UTF8/BOM UTF16LE/BE/GB18030正常中文正文PASS；UTF16BE混合换行/58060字符长章目录到末章及确认后冷恢复PASS（耗时未测），详见evidence；实际TXT预算+1字节的打开/重试下载前拒绝、共享截断UTF16LE解码拒绝及正常同级正文/原件/无错误进度子项PASS；READER-19文案已关闭（c53550ca/txt-errors-20260908）；其他平台及最终RC仍待 |
| PDF | PDF-N/C：文本目录+复杂大页/扫描图像PDF | W/A/I；P2 | F；真实物理页与内容可读，有界传输 | PDF-X：截断、密码/超预算 | PARTIAL/FAIL：Android一页PDF首次本地切换打开READER-09已CLOSED，69页普通首页相邻PASS（0271edd4；a389944e/android-pdf-20260907）；Android普通滑动/按钮、35中页/69末页边界及确认后冷恢复35正文子项PASS（64f1bbc1/android-pdf-navigation-20260907，耗时未测）；双指放大/缩回及横竖屏重建保持35/69和完整位置PASS（9a13322c/android-pdf-layout-20260907）；728a0cf8复杂PDF文字/纯图像两页可读、截断明确错误子项PASS；密码错误分类READER-10已CLOSED（cfec37f7新包原场景通过）；READER-11已CLOSED（554120b6新包新会话1→2→3实际三页/完整位置一致），大页四角正文可读，outline暂无章节不计通过，详见evidence。阅读方向设置/其余异常仍待。W正常69页首页/中页已读，READER-05候选待真实回归；iOS BLOCKED |
| COM-CBZ | CBZ-N/C：真实ZIP漫画、嵌套路径/自然排序/长图 | W/A/I；P2 | F；图片顺序与页数正确 | CBZ-X：加密/损坏/超预算 | PARTIAL/FAIL：Android正常6页/目录指定页/末页边界、设置缩放及确认后冷恢复5/6子项PASS（66f5efd5/android-comic-20260907，耗时未测）；W真实6页可读及末页重开，READER-06/07候选仍待真实回归；CRC坏中页隔离后两图实际PASS；不可解码中页后错误卡READER-13、单/双页切换崩溃READER-14均已CLOSED（79082997，见evidence），10000/10001页真实容量及超单页/压缩比原生子项PASS（d7ab754f，详见evidence）；方向/其余复杂异常及其他平台另计 |
| COM-ZIP | ZIP-N/C：独立ZIP源及含非图片条目 | W/A/I；P2 | F；正确筛图，顺序不漏重复 | ZIP-X：遍历/损坏/解压预算 | PARTIAL；IMPORT-03已关闭，148e0634真实六图+TXT全新导入/Android首末及前页PASS；ZIP逃逸/链接隔离及可规范化普通路径两图真实HTTP/Android PASS（fe90d7b5/comic-exceptions-20260907）；W/I与其他复杂异常待验 |
| COM-CBR | CBR-N/C：实际RAR容器与承诺变体 | W/A/I；P2 | F；不能用ZIP改名 | CBR-X：加密/损坏 | PARTIAL；d0126d3e真实RAR5压缩同字节CBR、Android首图/翻至4页/确认后冷恢复PASS；W/I与复杂异常待验 |
| COM-RAR | RAR-N/C：真实RAR4/RAR5分别登记适配能力 | W/A/I；P2 | F；变体失败记风险不删支持 | RAR-X：损坏/扩展预算 | PARTIAL；d0126d3e真实RAR5压缩Android首图/前翻及3/6确认PASS；RAR4、W/I及复杂异常待验 |
| COM-DIR | DIR-N/C：实际图片目录，多层/自然排序/非图片/已有图片类型 | W/A/I；P2 | F；图片文件数与Resource/Book数分开 | DIR-X：损坏图、单页失败隔离 | PARTIAL：bbb3fd71 Android六张PNG/JPEG顺序/末页边界、README过滤、确认后冷恢复第5页PASS；60b157c2补静态GIF/WebP、自然排序、嵌套目录一资源三页、坏页往返隔离PASS。READER-18 Android长图等比/首尾及150%内部拖动CLOSED（fa073fab普通、912d0254定向）；原件/位置限制见evidence，W/I及最终RC仍待 |

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

执行覆盖：按DEC-09，仅AUD-01的M4B/M4A、AUD-02 MP3、AUD-04 AAC及对应AUD-X为本轮必测。下表其他扩展名/额外编码清单保留作历史能力盘点，状态为本轮范围外，不是未完成门禁；不扩展通用测试工具，也不移除既有产品能力。

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
| POS-01 | P3；W/A/I、全部承诺格式 | 各格式记录唯一文字/物理页/图片/轨时间→保存→退出重开；目标端换字体屏幕 | 精确语义恢复；展示百分比不反推Locator | artifacts/releases/1.0/cff3e689/ordinary-audio-sync-20260907/；既有MP3见release-evidence | MP3及M4B/M4A/AAC正常W↔Android交接开发子项PASS；本轮后三格式误差最大15ms。Android TXT长p字号18↔19及19正常重开子项PASS（69a5ba15，READER-21 CLOSED，详见evidence）；其余格式/布局组合仍待逐项，iOS BLOCKED；未冻结RC |
| POS-02 | P3；各引擎代表样本 | 连续读听，量测捕获/本地持久化/发送/确认；不足5秒即返回/暂停/切后台 | 最后捕获位置按冻结间隔可靠保存，确认延迟单列 | 937b325b/reader-capture-windows-20260907/；2734ad51/mp3-lockscreen-20260908/；见evidence | PARTIAL：Android PDF实际5/10秒持久捕获、EPUB/CBZ连续操作相邻及各引擎早退子项PASS；普通MP3真实锁屏5/10秒持续确认、唤醒暂停完整一致PASS。其余平台/未涵盖组合及最终同RC待，iOS BLOCKED；阈值保持 |
| POS-03 | P3；各引擎 | 分别在本地持久化前、后、网络确认后强杀；App重启/系统回收/浏览器刷新 | 至少最后已持久化位置恢复；已确认零丢失，未持久化损失不超冻结间隔 | artifacts/releases/1.0/7e207c38/process-recovery/ | Chrome桌面/移动视口MP3已确认暂停后强杀并重登录恢复PASS（0/205.804ms）；Android普通首页已确认AAC四轨与M4B/M4A章节强停恢复PASS（f8847633，0/31/31ms）；Android EPUB确认后阅读中强停、冷首页50%及继续到第二章PASS（00563daf/android-epub-normal-20260907）；Android UTF16BE长章确认后强停/冷首页继续同末章正文PASS（9cb26b94/android-txt-encodings-20260907，耗时未测）；Android PDF确认35/69后强停冷首页继续同第35页正文PASS（64f1bbc1/android-pdf-navigation-20260907，耗时未测）；Android CBZ确认pages/4/5页后强停冷继续同图像PASS（66f5efd5/android-comic-20260907，耗时未测）；Android RAR5/CBR确认4/6后强停冷恢复同图像及完整position PASS（d0126d3e/android-rar-20260907，耗时未测）；未确认/其他引擎子项NOT_RUN；iOS BLOCKED |
| POS-04 | P3；已合法打开/可本地读取资源 | 断网读到B→观察pending→重启客户端→重连→重试并另端重开 | pending持久保留并最终确认；不扩展离线登录契约 | artifacts/releases/1.0/02d6ea2d/epub-offline-and-adjacent/ 与 epub-offline-mobile/；1d8d0c7c/pos10-native-server-restart-20260907/ | Chrome桌面/移动视口EPUB页面重建及重连子项PASS（965/959ms）；Android M4B离线完整pending持久、冷恢复20226→20247ms及最终r14/完整位置一致/pending空子项PASS；原mutation被新capture替代不证明精确原body重放，具体r12/r13回调不可归因；其他格式/另端交接NOT_RUN，iOS BLOCKED |
| POS-05 | P3；同账号同资源两端 | 写mutation M让服务提交但丢回包→另一端新写N→重试M；另测同M不同payload | 重放M不再覆盖N，不递增revision；不同payload受既有冲突处理 | artifacts/releases/1.0/afe19dca/pos05-lost-ack-chrome-android-20260907/；原62377271 API/ORM证据保留 | Chrome MP3真实丢ACK→Android N→Chrome原body重试及异payload409子项PASS，完整N/r7不变；非5秒时限/IDB清pending证据，其余引擎/方向与最终RC未覆盖 |
| POS-06 | P3；各端读/听writer | 阻留旧M响应→本端生成新pending N→释放M响应→重开/重试N | 旧ACK仅清对应M，N保留；不能回滚本地较新位置 | artifacts/releases/1.0/938afd24/pos06-native-late-ack-20260907/；5b967260/pos06-online-adjacent-20260907/ | Android实际同步owner/HTTP/SQLite子项PASS：M3933ms/r5实际提交后扣留ACK，N9939ms完整pending不被旧ACK清除，重建owner/DB原mutation重试r6；原online相邻PASS。控制点在真实HTTP返回后交付到coordinator，不是socket丢包、普通UI或进程强杀；Chrome/其他引擎NOT_RUN、iOS BLOCKED |
| POS-07 | P3；双端并发、离线首次提交 | A/B分别写并控制事务完成顺序；再让离线未提交C在N后首次到达；主动回读 | 按服务端最后事务提交生效；C可成为新当前位置，区别成功mutation重放；明确记录用户可见回退，不自创最大百分比算法 | artifacts/releases/1.0/9e017394/pos07-real-late-first-submit-20260907/；原62377271 API/ORM证据保留 | 真实Chrome MP3离线C→Android N→C首次提交及Android实际恢复子项PASS；完整C/r9仅新增一次receipt。首页SYNC-04、Web列表AUDIO-14已在b72b3d83真实原场景CLOSED（见首节）；服务/SQLite受控A→B、B→A及完整最后提交位置子项PASS（4d9e94b9/pos07-ordered-sqlite-20260907）；非HTTP/UI双端并发，其他引擎NOT_RUN，iOS BLOCKED |
| POS-08 | P3；两账号/服务器/资源 | 在途保存时切账号/服务器/资源，释放旧请求；尝试无权资源和同mutation跨namespace | 无串写、越权、错误清pending；业务身份以资源为准 | AUDIO-08/09实际RED/GREEN与93100b06；5b538f2a/rg02-account-server-scope-20260907/isolated-cookies/；见evidence | PARTIAL：Android音频切资源/Stop原缺陷已关闭；真实HTTP无权/撤权写入拒绝、同mutation跨user独立持久且owner不变通过。普通Android音频在途切账号、Reader关闭在途保存后切账号取消隔离PASS（542f8d13与e76fefb8目录result）；普通注销跨服务器重登取消隔离PASS（6af47724目录result）；Android共用Reader身份/取消owner，无需按PDF/Comic重复。Chrome相应在途UI、iOS及最终RC仍未覆盖；未接普通导航的保持登录切服不新增验收入口 |
| POS-09 | P3；有章/页入口的各格式 | 从目录显式目标A进入→读到B保存→旋转/重建/重进 | 显式入口只应用一次，回到后来B | E/POS-09/；58cff471/pos09-native-explicit-entry-20260907 | PARTIAL：Android M4B播放器章节导航后冷启恢复B子项PASS；AUDIO-13已关闭（582c81fc新包真实播放/暂停旋转保持、注销停止PASS）；Android EPUB阅读器内目录A→继续B→确认后冷重开B子项PASS（4d9e94b9/android-epub-toc-20260907）；Android CBZ阅读器目录指定4后继续到6/5，确认后冷恢复5而非4子项PASS（66f5efd5/android-comic-20260907）；带外部显式启动参数/旋转及其他引擎NOT_RUN，iOS BLOCKED |
| POS-10 | P3；各引擎 | 确认位置→服务受控重启→重开；另保持目标端正在阅读，远端写入 | 已确认位置保留；活动会话不被强行跳转 | E/POS-10/；34d4a24e/pos10-active-session-20260907 | PARTIAL：MP3 Chrome实际重连/Android ON_RESUME活动暂停会话远端提示不自动跳转、显式跳转PASS；1d8d0c7c的API/Worker终止重启后Android M4B同确认位置恢复PASS；Android EPUB原会话ON_RESUME远端提示/第一章保持/普通显式第二章及完整local=server PASS（cb623422/pos10-reader-active-20260908，远端为真实HTTP受控提交，非另端UI交接）；其余独立引擎行为/完整部署重启NOT_RUN，iOS缺设备BLOCKED |
| POS-11 | P3；各格式 | 标记已读/取消已读→主动回读→检查首页/详情/目录/Reader | 已读状态独立；不制造恢复位置；展示与实际语义一致 | artifacts/releases/1.0/938afd24/pos11-status-projection-20260907/；180bb697/pos11-native-reading-status-20260907/；f778eecf/status01-native-regression-20260907/ | STATUS-01 CLOSED；Android M4B普通详情67%标已读/强停重开/取消、API完整位置不变、首页冷恢复20247→20247ms子项PASS；API/SQLite公开投影及批量身份相邻PASS；100%未标已读与书/资源owner由自动回归覆盖，其他界面/格式NOT_RUN，iOS BLOCKED |

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
