# 1.0 发布证据与最终签收

当前结论：**NOT_RUN / R1 执行中，尚无整体放行依据**。正式安装包构建/导出由用户暂缓；代码回归、修复与 Android 真机验证继续。下方 R0 为历史记录，不能覆盖本节当前事实。

## R1 当前执行与恢复入口（2026-09-06）

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
