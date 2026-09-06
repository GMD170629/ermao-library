# 1.0 发布验收矩阵

配套硬要求与建议阈值唯一见 release-gate.md；事实来源见其 §6；证据登记见 release-evidence.md；缺项见 release-blockers.md。本表是可执行计划，**未执行不计 PASS**。

## 1. 执行基线与展开规则

当前为 `develop@9a4901edba41fab786bd28ff92144ff802ddfab3` 加未提交修改；模板基线为 `9ff93969bf46c24d24e97c0103cae50244fd64aa`。实际 RC、产物 hash/digest、浏览器/系统版本、机器预算与负责人均待冻结。不得将当前工作树运行结果登记成纯 HEAD 结果。

以下公共前置是每行的组成部分，减少重复而不省略要求：

- **P0**：冻结同 RC 的产物/依赖锁/版本，专用新数据库与源目录、测试管理员及普通账号，备好请求/屏幕证据；不触碰真实旧数据。
- **P1**：P0 + 对应 Release 产物、真实服务器、Web 浏览器；Android 精确授权物理设备，iOS 配对解锁物理设备/Mac/签名/安装方式。每行均注明平台；W/A/I 分别为 Web/Android/iOS。
- **P2**：P1 + 下方样本组真实文件，SHA-256、合法来源、大小、内部容器/编码、章节/页/轨事实和预期清单。样本 ID 是预留登记槽，**不是已存在文件**。
- **P3**：P2 + 同账号三端、可控制请求与回包延迟/断网的隔离网络、已冻结保存间隔/位置误差；故障注入实现入口待补，可由受控代理人工操作，不能改业务代码制造证据。
- **P4**：P1/P2 + 大库隔离环境与阈值全部冻结，真实有效资源数据集、负载/采集步骤已复核。
- **E**：`artifacts/releases/1.0/<rc-commit>/`，仅计划证据根；每行保存到 `E/<ID>/`，实际执行后登记具体路径、时间、操作者、hash、原始结果。

参数组须按 `ID/平台/源格式/样本/场景` 展开成独立执行记录；不能一次 PASS 覆盖未跑组合。默认 NOT_RUN；已明确缺交接前提的真机、真实客户端、素材/大库条目标 BLOCKED。若共享行含 W/A/I，W 不因 I 阻塞被伪造为已执行；各子项分别记状态。

## 2. 发布、初始化与接入

命令编号 C-* 见 §7，人工操作依据 release-gate.md §6 的实际 UI/API；所列命令本轮均未运行。

| ID / Gate | 前置、平台/样本 | 具体命令或人工步骤 | 预期 | 证据位置 | 状态 / 关联 |
|---|---|---|---|---|---|
| ART-01 / RG-01 | P0；Python/Web/KMP/Android/iOS | C-01..05；发布候选完整回归，分别记录当前结果；无可用执行器的检查停为 BLOCKED | 必要检查全部通过，无 skip/弱化；原生最终证据来自真机 | E/ART-01/ | NOT_RUN；ENV-01..03 |
| ART-02 / RG-01 | P0；linux/amd64、linux/arm64 各一行 | 按 C-06 对同 RC 构建隔离产物；逐架构启动 Web/API/Worker，执行 INI-01 和每媒体首条样本 | 三组件健康、网关正常、初始化/导入/媒体链路正确；一架构不代替另一架构 | E/ART-02/ | BLOCKED（本地RC构建/部署入口待补）；ENV-01、ENV-03、ENV-07 |
| ART-03 / RG-01 | P1；Android 正式签名、授权测试设备 | C-07；确认正式签名/包版本后，通过现有安装方式安装至专用测试设备，不清除用户数据；冷启动登录和读听，核对 crash/ANR | 正式 Release APK 可独立安装使用；签名/版本/hash/设备可追溯 | E/ART-03/ | BLOCKED；ENV-01、ENV-03、ENV-07 |
| ART-04 / RG-01 | P1；iOS Team/证书/描述文件、设备 | C-08；Release Archive→正式 export→IPA；记录合法安装方式并按其安装，在真机冷启动、登录、读听 | IPA 签名有效、设备适用且实际运行；无 Simulator/无签名绕过 | E/ART-04/ | BLOCKED；ENV-01..03、DEC-01 |
| ART-05 / RG-01 | P0/P1；三产物 | 比对根/Web/Python版本与运行版本、Android/iOS版本build、构建commit及hash；复核包中测试注入/凭据；与全部报告关联 | 同一 RC 版本组合，无测试 URL/账号/秘密混入；测试二进制即待交付二进制 | E/ART-05/ | NOT_RUN；ENV-01、ENV-03 |
| INI-01 / RG-02 | P1/P2；新库；正常 EPUB+MP3 | Web 打开首次设置、创建管理员→登录→新增根目录→继续导入→列表/详情→三端阅读/播放 | 无默认管理员、手改 DB；初始化至可读闭环顺畅 | E/INI-01/ | NOT_RUN（原生子项 BLOCKED）；ENV-02、ENV-03、ENV-06 |
| INI-02 / RG-02 | P0；无权/不存在路径、重复请求 | 设置重复提交；普通账号访问设置；新增坏路径，修正后重新提交/导入 | 重复初始化和越权正确失败；路径反馈明确，修正可恢复 | E/INI-02/ | NOT_RUN；ENV-03 |
| INI-03 / RG-02 | P1；INI-01已完成 | 记录账号/书库/任务/已确认位置，受控重启当前版本服务，再登录与重开 | 新数据持久化，无再次初始化或已确认数据丢失 | E/INI-03/ | NOT_RUN；ENV-03 |
| IMP-01 / RG-02 | P2；FLAT、VOLUMES 各独立根 | 按 UI 分别建库、扫描根文件与含子目录书籍；对照预期清单记录目录和独立资源身份 | 两正式模式 Book/Node/Resource/Asset/页轨计数与层级正确 | E/IMP-01/ | NOT_RUN；ENV-03、ENV-06 |
| IMP-02 / RG-02 | P2；中英名、空格、特殊字符、多层、图片/音频目录 | 导入后进入每层，切换排序/分页，打开图片目录与多轨音频 | 不乱码、不漏资源、不用资源数决定页面类型；正常播放/阅读 | E/IMP-02/ | NOT_RUN；ENV-06 |
| IMP-03 / RG-02 | P2；合法+损坏/DRM/无权文件混合 | 隔离根扫描；使外部元数据不可达；核对任务错误与同级合法资源 | 错误隔离可解释，基础入库/已可读内容不被拖死；源文件不变 | E/IMP-03/ | NOT_RUN；ENV-06 |
| IMP-04 / RG-02 | P2；IMP-01源保持不变 | 记录文件hash/拓扑/进度→再次手动扫描→对账 | 不重复不丢失，未变文件进度保留 | E/IMP-04/ | NOT_RUN；ENV-06 |
| IMP-05 / RG-02 | P2；仍有真实待处理任务 | 扫描活跃时受控服务重启→查看队列→继续导入/安全重扫 | 任务可恢复、有进展、不永久卡住；不要求新暂停接口 | E/IMP-05/ | NOT_RUN；ENV-03、ENV-06 |
| IMP-06 / RG-02 | P2；专用可写/只读根，测试文件 | Web 上传→文件详情；使用已有增删改入口；坏文件修正后资源重扫/继续导入；分别观察自动扫描和手动扫描对缺失项处理 | 仅授权显式写操作变动测试源；自动保留缺失、手动成功完成后按既有语义清理拓扑；失败可重试 | E/IMP-06/ | NOT_RUN；ENV-03、ENV-06 |
| CON-01 / RG-02 | P1；W/A/I × HTTP/HTTPS/自定义端口 | 逐地址添加服务器/登录，浏览与读听；HTTPS经受信任代理；非信任证书走现有显式流程；公开链接检查 | 合法配置可连接；无默认关闭TLS；冷/热启动均不依赖localhost | E/CON-01/ | NOT_RUN（原生 BLOCKED）；ENV-02、ENV-03 |
| CON-02 / RG-02 | P1；管理员、普通账号、两个服务器 | 错密码→修正；服务端使会话失效后重登；切账号/服务器再取无权资源 | 错误反馈正确、权限重验，数据与会话不串用 | E/CON-02/ | NOT_RUN（原生 BLOCKED）；ENV-02、ENV-03 |
| OPDS-01 / RG-02 | P2；静读天下+第二独立客户端，名称版本待补 | 先在Web OPDS设置启用并填写可达publicBaseUrl；每个应用添加实际返回的 /opds/v1.2/catalog，先错误密码再正确凭据；记录认证challenge和客户端行为 | 两真实应用可认证，错误凭据不可访问；认证文档/Content-Type正确 | E/OPDS-01/ | BLOCKED；ENV-04 |
| OPDS-02 / RG-02 | P2；两个客户端各支持的合法格式 | 各应用浏览→分页→搜索→封面→下载→在该应用打开内容中段 | 不仅目录首页成功；分页/检索正确，原文件可读 | E/OPDS-02/ | BLOCKED；ENV-04、ENV-06 |
| OPDS-03 / RG-02 | P2；代理HTTP/HTTPS/端口；两账号 | 沿真实返回链接下载与取封面，记录公开URL/认证；对原文件SHA-256；用有Range的实际链接请求有效/越界区间，核对206/Content-Range/416及无权路径 | 链接不泄漏内网地址、权限不丢；完整文件一致；区间语义正确 | E/OPDS-03/ | BLOCKED；ENV-03、ENV-04；协议辅助可单独 NOT_RUN |
| OPDS-04 / RG-02+04 | P3；全新资源+支持Progression真实客户端 | C-09辅助；检查 /opds/v1.2/resources/{resource_id}/progression 的真实GET/PUT、未授权和重复写；第一方写→第三方读，第三方写→第一方重开；记录精确位置/仅比例/无Locator边界 | 扩展承诺可验证，不以目录替代；所有失败保留，不能隐去新数据链路问题 | E/OPDS-04/ | BLOCKED；ENV-05、RISK-01 |

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

每行证据 `E/<AUD-ID>/<平台>/<容器-编码>/<结构>/<N-C-X>/`；真实样本/hash 均待补，当前 BLOCKED / ENV-06、DEC-02（原生另 ENV-02/03）。平台能力尚未获明确已有承诺的组合在执行前冻结，不能先失败后决定预期。

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

前置 P3；每个 REF-*/PDF/COM-*/可播 AUD-* 逐格式保存/重开并跑六方向：**W→A、A→W、W→I、I→W、A→I、I→A**。分别生成 `SYNC/<方向>/<源格式>/<样本>` 记录，步骤为来源端到唯一内容锚点→等明确确认→目标端新进入同资源→核对真实位置→主动回读再反向记录。预期：可重排同语义文字锚点（不比统一页码）；PDF物理页；漫画图片/页；音频轨ID+时间（误差按门禁建议冻结）。证据 `E/SYNC/<方向>/...`，六方向当前均 BLOCKED（ENV-02、ENV-03、ENV-06），不是只做一条三端循环。

以下异常组每类实际引擎至少一套，不能用单个EPUB或只比百分比替代；执行前先列样本与引擎对应关系。

| ID / RG-04 | 前置/平台/样本 | 操作步骤 | 预期 | 证据 | 状态/关联 |
|---|---|---|---|---|---|
| POS-01 | P3；W/A/I、全部承诺格式 | 各格式记录唯一文字/物理页/图片/轨时间→保存→退出重开；目标端换字体屏幕 | 精确语义恢复；展示百分比不反推Locator | E/POS-01/ | NOT_RUN（原生/缺样本子项BLOCKED）；ENV-02/03/06 |
| POS-02 | P3；各引擎代表样本 | 连续读听，量测捕获/本地持久化/发送/确认；不足5秒即返回/暂停/切后台 | 最后捕获位置按冻结间隔可靠保存，确认延迟单列 | E/POS-02/ | NOT_RUN（原生/缺样本子项BLOCKED）；DEC-04 |
| POS-03 | P3；各引擎 | 分别在本地持久化前、后、网络确认后强杀；App重启/系统回收/浏览器刷新 | 至少最后已持久化位置恢复；已确认零丢失，未持久化损失不超冻结间隔 | E/POS-03/ | NOT_RUN（原生/缺样本子项BLOCKED）；ENV-02/03 |
| POS-04 | P3；已合法打开/可本地读取资源 | 断网读到B→观察pending→重启客户端→重连→重试并另端重开 | pending持久保留并最终确认；不扩展离线登录契约 | E/POS-04/ | NOT_RUN（原生/缺样本子项BLOCKED）；ENV-03 |
| POS-05 | P3；同账号同资源两端 | 写mutation M让服务提交但丢回包→另一端新写N→重试M；另测同M不同payload | 重放M不再覆盖N，不递增revision；不同payload受既有冲突处理 | E/POS-05/ | NOT_RUN（原生/缺样本子项BLOCKED）；ENV-03 |
| POS-06 | P3；各端读/听writer | 阻留旧M响应→本端生成新pending N→释放M响应→重开/重试N | 旧ACK仅清对应M，N保留；不能回滚本地较新位置 | E/POS-06/ | NOT_RUN（原生/缺样本子项BLOCKED）；ENV-03 |
| POS-07 | P3；双端并发、离线首次提交 | A/B分别写并控制事务完成顺序；再让离线未提交C在N后首次到达；主动回读 | 按服务端最后事务提交生效；C可成为新当前位置，区别成功mutation重放；明确记录用户可见回退，不自创最大百分比算法 | E/POS-07/ | NOT_RUN（原生/缺样本子项BLOCKED）；DEC-03 |
| POS-08 | P3；两账号/服务器/资源 | 在途保存时切账号/服务器/资源，释放旧请求；尝试无权资源和同mutation跨namespace | 无串写、越权、错误清pending；业务身份以资源为准 | E/POS-08/ | NOT_RUN（原生/缺样本子项BLOCKED）；ENV-03 |
| POS-09 | P3；有章/页入口的各格式 | 从目录显式目标A进入→读到B保存→旋转/重建/重进 | 显式入口只应用一次，回到后来B | E/POS-09/ | NOT_RUN（原生/缺样本子项BLOCKED）；ENV-06 |
| POS-10 | P3；各引擎 | 确认位置→服务受控重启→重开；另保持目标端正在阅读，远端写入 | 已确认位置保留；活动会话不被强行跳转 | E/POS-10/ | NOT_RUN（原生/缺样本子项BLOCKED）；ENV-03 |
| POS-11 | P3；各格式 | 标记已读/取消已读→主动回读→检查首页/详情/目录/Reader | 已读状态独立；不制造恢复位置；展示与实际语义一致 | E/POS-11/ | NOT_RUN（原生/缺样本子项BLOCKED）；ENV-06 |

以上NOT_RUN异常组若执行到缺设备/样本的具体子项则为BLOCKED，已知原生前提未交接不得启动；辅助自动测试 C-09 单独记录，不替代真机和竞态网络证据。

## 6. 大库扫描并发

P4的冻结表必须填写：CPU/架构、RAM、磁盘/文件系统/挂载、数据库位置、OS、容器CPU/内存预算、系统余量、网络带宽/延迟；扫描并发/元数据策略；三端版本和至少三活动会话；总字节/大小分布/媒体比例/目录深度/坏文件比例；冷/热基线；采样方法/窗口/样本量/阈值/批准人时间。N100/8GB只是建议目标，无设备事实。所有阈值沿用 release-gate.md 的建议，尚未冻结且**不是实测值**。

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
| C-02 | apps/web | `pnpm lint`、`pnpm typecheck`、`pnpm test`、`pnpm i18n:check`、`pnpm test:e2e`；真实iPhone Safari/PWA另做人工验收 |
| C-03 | packages/reader-contracts | `python3 generate-reader-safety-policy.py --check`；`python3 check-reader-safety-boundaries.py`；`python3 -m unittest discover -s tests -p 'test_*.py'` |
| C-04 | apps/mobile | 当前 .github/workflows/mobile.yml 的 `./gradlew :shared:testAndroidHostTest :androidApp:testDebugUnitTest :androidApp:lintDebug :androidApp:assembleDebug`；完整回归使用GitHub Actions workflow_dispatch输入 `run_full_android_regression=true`；CI模拟器仅补充，不替代正式APK物理设备 |
| C-05 | 仓库根 | `pnpm smoke:python-worker-import`：现有临时新库小样本Worker测试，仅辅助；`python3 apps/mobile/iosApp/verify_readium.py`：SDK静态检查，不是IPA或真机通过 |
| C-06 | 仓库根 | apps/web/Dockerfile.prod / docker-compose.prod.yml / scripts/start-unified-app.sh 的实际构建部署入口见门禁§6；RC本地双架构构建参数/测试compose覆盖文件待补；不执行 docker:publish / tag推送 |
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




