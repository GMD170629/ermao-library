# 二毛图书 1.0 Release Gate

本机负载预检复用 `scripts/python_release_load_precheck.py` 和既有真实 API/Worker 入口，记录源码摘要、样本 hash、请求延迟/错误、进程树 RSS、确认进度读回和重扫标识完整性。工具验证、紧凑样本准备及短窗口测量分别登记，不代替下文完整规模、时长和最终冻结 RC 验收。

执行记录约束补充：格式覆盖须以实际资源MIME/容器与采样文件对应，不能仅凭标题或测试名称计数；正常全链路中的服务端5xx即使页面继续可用也须登记调查。负载期间的其他构建/浏览器工作必须记录，受干扰运行只能诊断，不能作为安静基线放行。阅读状态、位置百分比、真实Locator是独立事实，标记已读不应伪造100%位置。

文档版本：v1-R1（自主收敛中；下列执行决策优先于历史 R0 描述）
建立日期：2026-09-06  
模板核对基线：`develop@9ff93969bf46c24d24e97c0103cae50244fd64aa`（2026-09-04）  
R0 实际分支/HEAD：`develop@9a4901edba41fab786bd28ff92144ff802ddfab3`（2026-09-05）加既有未提交工作树；不是冻结 RC。  
本文件性质：定义发布要求，不是运行验收报告。性能数字是建议冻结的产品阈值，不是现有系统测量结果，也不是外部行业标准。

### 2026-09-06 执行决策

- opaque Locator 的网络往返验收比较完整 JSON 对象值，保留所有未知引擎成员，不要求对象键的输出顺序；完整展示字段、身份、捕获时间、revision、确认状态和已冻结时限分别验证。不得以百分比或部分 Locator 字段替代完整位置比较。
- Android 真实 HTTP 验收使用显式 `-PenableReleaseLiveProbe=true` 的独立测试入口，普通仪器套件数量和该项结果分开登记。新增入口编译成功或测试进程退出成功不代表门禁通过，以 JUnit 结果、实际服务端确认和原文件校验为准；当前两次 bootstrap 失败保留，不跳过该链路。
- 用户明确批准：1.0 暂不支持第三方进度同步。OPDS 保留目录、搜索、下载；关闭 Progression 入口及能力声明并验证无进度写入。OPDS-04 原双向同步验收改为 N/A（DEC-05）；入口关闭回归仍必须通过，第一方跨端同步范围不变。
- 从实际已提交 `develop@197e81a808ba32595a8a6ffeda62422b3a7d3473` 开始；初始工作树干净。隔离工作区 `D:/www/ermao-release-1.0`，分支 `codex/release-1.0-convergence`。尚未冻结 RC。
- 用户授权持续验证、必要修复、回归和发布准备；R0 只读限制已经结束。仅操作隔离测试数据。用户随后授权按逻辑及时 commit/push 防止丢失；仅推送专用发布分支，推前核对隐式工作流副作用，仍不授权镜像/正式版本/生产发布。
- 用户随后决定：正式安装包构建/导出延后，暂不执行；优先代码层面门禁，允许 Android 真机测试。测试构建与真机结果仅是开发验收，不能替代正式 APK/IPA 交付。
- 用户接受本文件 RG-04/05 的现有建议阈值，以及 ADR 0028 的最后事务提交生效语义（首次迟到的离线位置可能覆盖当前位置）；DEC-03/04 的语义和阈值部分已冻结。各次性能运行仍须预先记录实际机器、资源预算、数据分布和采样方法。
- 用户决定低功耗 NAS 暂不测试，本轮本机预检即可；不得将本机结果外推为低功耗 NAS 性能结论。正式产物、iOS 设备及最终同 RC 放行要求保留，暂缓项目不填 PASS 或 N/A。
- 用户进一步收敛 Web 测试平台：仅 Chrome，不执行 Firefox、WebKit/Safari。入口保留 Chrome 桌面及移动视口（移动视口不是 Android/iOS 原生验收）；已跑其他浏览器结果仅作历史记录。本文和矩阵旧的 Safari/PWA 浏览器要求据此不再作为本轮 Web 必测范围。
- 用户允许本任务子代理使用更高级模型；已将复杂诊断和逐格式后端验证委派给gpt-6-astra/max，主代理保留架构、差异复核、整合验证与放行责任。
- 执行中发现音频自动保存超出已冻结5秒上限、独立阅读状态投影不一致，均按门禁缺陷修复；不得以缩减保存频率要求或重写真实位置解决。已捕获位置、客户端持久化、服务端确认分别举证；4秒周期捕获仅是满足上限的实现预算，不能直接证明5秒持久化通过。
- 发布准备的镜像入口必须显式使用 `scripts/publish-docker-hub.sh --output-dir <隔离产物目录>`；该模式从冻结提交归档导出本地 OCI，记录源码、版本、架构和 SHA-256，不推送。未提供此参数的旧默认模式仍属于对外发布，当前未授权执行；实际容器构建/运行受 ENV-08 阻塞，CLI stub 测试不能计入 ART-02 运行通过。

## 0. 发布边界

1. 1.0 为全新安装产品，仅使用全新数据。后台、Web、Android、iOS 作为一个版本组合验收。
2. 不做 `<1.0` 升级、旧数据库/阅读进度迁移、旧客户端兼容或回退到 0.x。不得借本任务删除真实旧数据；测试必须使用专用目录和数据库。
3. 全新安装并不排除当前版本的数据持久化：1.0 产生的账户、书库、任务状态和进度在应用或服务重启后仍应保留。用于创建当前 schema 的初始化机制仍可使用。
4. 交付后端生产部署产物（含 Web/API/Worker）、Android 正式签名 APK、iOS Release Archive 导出的 IPA。IPA 的签名、导出方式及适用安装方式必须明确。
5. iOS 不以 App Store 审核、TestFlight、商店截图或商店上架为本轮门禁；Android 不默认增加 AAB/Google Play/其他商店上架。
6. 不新增格式、转码系统、全局缓存框架、扫描框架或新的同步协议；不做大规模视觉重设计。修复范围以门禁内缺陷为准。
7. 按源码、公开声明和真实界面冻结能力矩阵。已经承诺可阅读的格式不能因测试失败而自行改成不支持；变更发布范围须由项目负责人明确批准并留痕。

## 1. 总体放行规则

`GO = RG-01..RG-05 所有适用必测项 PASS + P0/P1 清零 + 证据可追溯 + 交付物齐备 + 项目负责人签收。`

- 状态只使用 `NOT_RUN / PASS / FAIL / BLOCKED / N/A`。
- `NOT_RUN` 表示没执行；`BLOCKED` 表示缺设备、签名、样本或环境；二者都不能计为通过。
- `N/A` 只用于测试前已批准的不适用范围，必须写原因；不允许给“已承诺支持但失败”的项目填 N/A。
- 所有门禁内硬要求失败均阻塞发布，不能仅把问题标为 P2 绕过。
- 门禁外的轻微文案、外观问题可以列为 P2，由负责人明确接受；功能不可用、进度丢失、越权、初始化失败、扫描拖死服务不可延期放行。
- 本次只建立门禁，不把旧审计文档、历史 CI、测试文件存在或源码看起来正确当作当前 RC 的 PASS。
- 所有最终证据对应一个冻结的 RC commit，后端镜像使用不可变 digest，APK/IPA 使用 SHA-256。修复后的相关证据失效并复跑；有依赖变化或影响面不明时做完整回归。
- 历史 full regression 可作为辅助证据；最终 RC 仍需完成必要完整回归和发布产物上的关键端到端复测。相同版本号但不同二进制不能冒充已验收版本。

## 2. 门禁总览

| ID | 发布要求 | 最终判定 |
|---|---|---|
| RG-01 | 后端、Android APK、iOS IPA 完整交付，来自同一版本基线 | 产物可追溯、可部署/安装，运行验收通过 |
| RG-02 | 全新初始化、导入及第一方/第三方客户端连接顺畅 | 从空环境到可阅读闭环通过，不依赖开发者手动修数据 |
| RG-03 | 全部承诺格式可读/可听 | 冻结的格式 × 平台 × 播放/阅读方式矩阵通过 |
| RG-04 | 进度保存、恢复和跨端同步正确 | 真实位置、持久化、异常恢复及竞态结果可验证 |
| RG-05 | 超大书库扫描时前台仍可用 | 真实文件扫描与前台混合负载同时达到稳定性和响应阈值 |

## RG-01：发布产物与版本一致性

### 必须交付

| 产物 | 必须满足 | 必须保留的证据 |
|---|---|---|
| 服务端 | 生产部署镜像/包包含所需 Web、API、Worker；全新数据目录按公开说明即可启动 | 镜像 digest、commit、构建日志、部署配置、全新启动日志 |
| Android | 正式签名 Release APK；不是 Debug APK；安装后无需 IDE 即可连接并使用真实后端 | APK SHA-256、签名证书指纹（不含私钥）、versionName/versionCode、真机安装与启动记录 |
| iOS | 真实设备目标的 Release Archive 成功导出 IPA；明确签名/描述文件及分发安装方式；不是模拟器 .app 改后缀 | IPA SHA-256、Archive/export 日志、导出方式、Bundle ID/版本/build、对应方式的真机安装/运行证据 |
| 发布清单 | 同一 commit 的版本映射、产物地址/路径、文件校验、运行范围与已知限制 | `release-evidence.md` 中的交付清单 |

iOS IPA 能如何安装取决于签名与分发方式。默认要求有明确可执行安装路径并完成真机验证；不得把“存在 .ipa 文件”写成任意设备均可安装。签名或合法安装验证条件缺失时记录 BLOCKED，不绕过签名验证。若最终选择不同交付方式，应先由负责人明确批准，不自动改为商店发布或未签名交付。

公开支持的服务器架构都要验证。当前 README 声明 `linux/amd64`、`linux/arm64`；至少验证每个架构的启动、初始化、导入与媒体链路，不以另一个架构构建成功替代。

### 必测

- 同一提交必要的 Python/Web/KMP/Android 检查通过；按现有测试政策完成发布完整回归。不得跳过失败测试、修改预期或降低门槛造绿。
- iOS 使用实际可用物理设备做构建、安装、测试和阅读验收，不以 shared 编译或 Simulator 结果替代。
- 安装后的包能连接真实测试服务器，不依赖 fixture、硬编码开发 URL、调试开关或测试账号注入。
- 测试账号、数据库、私钥、token、私有路径和读物正文不得混入发布物和公开日志。
- 同步发布指版本组合和物料齐备，不要求构建作业同时结束；最终宣布发布前，三项交付物全部可追溯且已通过对应检查。

## RG-02：初始化、导入与客户端连接

### A. 从空环境到可读

最小闭环：

`空数据目录 → 部署 → 创建管理员 → 添加书库 → 扫描真实文件 → 列表/详情 → Web/Android/iOS 阅读或收听。`

- 无手工 SQL、修改数据库、复制开发者本地配置、预置管理员或隐含测试数据要求。
- 不支持/不可读路径、无权限、重复提交、网络失败等情况有明确反馈；修正后可重试，不进入永久卡住或半初始化状态。
- 完成初始化后重启当前版本服务，账户、书库设置和已产生数据保持；不重新要求创建管理员。
- 正常书库仅扫描读取时不修改、移动、删除用户源文件；需要写入的显式操作按实际权限和交互验证。
- 元数据外部服务失败不得阻塞本地书籍基础入库和已可用内容阅读，除非该文件本身无法解析。

### B. 导入

- 覆盖当前正式支持的所有根目录组织模式；先从现行源码/配置和界面列出，不能仅凭旧文档推断。
- 覆盖独立文件、业务目录、合法多层节点、图片目录漫画、多轨音频目录，以及当前公开支持的上传入口。
- 有预先确定的期望清单：书库、Node、Book、ReadableResource、Asset、音轨/页分别计数；验证业务身份与目录层级，不混用数量。
- 中文、空格、特殊字符、长名称、多层目录能按已支持边界处理。
- 坏文件、DRM、加密压缩包、不支持编码/格式、不可读文件须单项报告；合法同级文件继续处理。
- 重复扫描同一批未变文件不重复建书、不打乱已确认结构、不丢失当前 1.0 数据和进度。
- 扫描中受控重启，重启后可按现有机制恢复或安全重扫；不能丢任务到永远不可恢复，也不要求新增一个不存在的暂停/取消功能。
- 增删改文件的同步、任务失败与重试，以已经暴露的功能为验收对象，不擅自新增组织规则。

### C. 第一方连接

Web、Android、iOS 均覆盖局域网 HTTP（在产品允许的配置下）、受信任 HTTPS 反向代理、自定义端口、错误凭据、会话失效、普通用户权限和多端同账号。

合法配置必须能连接；不受信任证书按已有显式安全流程处理，不通过默认关闭 TLS 验证来满足门禁。若产品公开支持 URL 子路径部署，加入子路径；没有承诺则不强制新增支持。

### D. 第三方客户端 / OPDS

- 至少两个独立第三方客户端实测并记录名称、版本、平台与支持能力。优先纳入用户此前使用的静读天下；R0 未能确定另一个真实客户端的名称/版本，已在矩阵中记为环境待补，不能只写“兼容 OPDS 客户端”。
- 真实应用完成：添加目录 → 认证 → 浏览/分页 → 搜索 → 封面 → 获取原文件 → 在其自身支持的格式上打开。
- 未登录/错误密码获得协议适配的认证响应；正确凭据可继续。检查 `WWW-Authenticate`、认证文档、Content-Type，不能被通用 API 包装器或登录 HTML 覆盖。
- 经过反向代理后，目录、封面、分页、下载链接仍使用正确公开地址；权限沿所有链接保持，普通用户不能读到无权资源。
- 对原文件做字节数/哈希核对；对支持 Range 的资源校验状态、区间与 Content-Range，不以 HTTP 200 或拿到一段数据作为完整获取证据。
- 当前项目有 OPDS Progression 声明与路由。若 1.0 保留“第三方进度同步”承诺，须验证全新 1.0 数据上的协议 GET/PUT、鉴权和进度互通，并至少用一个明确支持该扩展的客户端完成实际联调。
- 只支持 OPDS 目录的客户端不被要求实现进度扩展；不能把它的“连接成功”当成第三方同步通过。尚无合适客户端时该承诺的真实联调为 BLOCKED，不由接口单测替代。
- OPDS 扩展的真实支持范围必须单独记录，不把百分比同步宣传为任意第三方与第一方 Reader 的精确位置互换。

## RG-03：已承诺格式阅读/播放

### 当前核对到的格式基线

格式注册以 `packages/reader-contracts/reader-safety-policy.json` 等当前源码为依据，公开承诺同时参考 README 与界面。

| 类别 | 至少纳入的格式/结构 | 验收端 |
|---|---|---|
| 可重排电子书 | EPUB、MOBI、AZW、AZW3、PRC、FB2、TXT | Web、Android、iOS |
| PDF | PDF（不可因本次需求未单列而遗漏） | Web、Android、iOS |
| 漫画 | CBZ、ZIP、CBR、RAR、IMAGE_DIR 图片目录 | Web、Android、iOS |
| 有声书 | AUDIO 单文件、AUDIOBOOK_DIR 多轨目录；各已承诺容器与编码组合 | Web、Android、iOS |

这是应验收清单，不表示当前全部通过。旧的接收兼容枚举不自动扩大为新安装的新功能要求；但例如 M4B/M4A/MP3 源文件仍按 AUDIO 容器/编码矩阵验收，不能因存储枚举名变化漏测。

### 样本与矩阵

- 每种承诺格式至少有正常样本与一种非平凡样本；每类媒体都包含损坏或超限样本。复用已有 corpus，缺样本记 BLOCKED；不能用改扩展名来代替另一种真实格式。
- 区分真实内部变体：如 EPUB 内容结构、MOBI/KF8、RAR 变体、TXT 编码；列明哪些变体有承诺、哪些受当前引擎限制。
- 每个样本记录 ID、哈希、格式/容器/编码、大小、章节/页/音轨事实、预期结果和适用平台。
- 漫画中实际已支持的图片格式、自然排序、嵌套路径及非图片过滤都要覆盖；不临时引入新图片格式。
- TXT 的当前支持编码、中文与换行场景须有实样，不能只用一个 UTF-8 英文文件代表全部。

### 必测动作

| 类型 | 必测动作 |
|---|---|
| 全部 | 首次打开、加载失败可理解、退出重进、同一本不同入口打开、后台前台切换、已公开的下载/本地读取路径 |
| 可重排 | 连续翻页/滚动、跨章、目录跳转、字号/字体/主题与方向变化、返回后恢复，不丢段或系统性重叠错位 |
| PDF/漫画 | 首页/中间/末页、页码/目录跳转、顺序、缩放与已有阅读方向设置、大页/长图边界、返回与重开 |
| 音频 | 播放/暂停、拖动进度、切轨、连续播放、倍速、已有睡眠定时；移动端锁屏、后台、系统音频中断后恢复 |

移动端主体验要有真机证据；web 使用冻结的浏览器与版本。任意一种格式的核心路径不能只以“能打开首页”验收。

### 音频的特别规则

当前公开说明区分“可导入”和“设备可解码”，且不做服务器转码。因此矩阵按 `容器 + 编码 + 平台/浏览器 + 运行模式` 记录，结果明确为：

- `PLAYBACK_REQUIRED`：该组合已承诺可以播放，必须实际完成播放、seek、恢复等流程。
- `IMPORT_ONLY`：此前已明确仅兼容导入/当前设备不支持播放，必须正确导入与展示能力提示、无崩溃/无限缓冲。不能伪造播放成功。
- `REJECT_EXPECTED`：DRM、损坏、超安全预算等已明确拒绝的输入，按既有规则安全失败。

每个平台均须具备实际可播放的有声书核心样本。已承诺可播放的组合不得因测试失败降为 IMPORT_ONLY。

## RG-04：进度保存与跨端同步

### 正常同步矩阵

Web、Android、iOS 三者之间六个有向组合全部覆盖：Web→Android、Android→Web、Web→iOS、iOS→Web、Android→iOS、iOS→Android。

每一种发布承诺格式都参与保存/重开与跨端验证；每类引擎至少有完整异常矩阵。用一条三端循环仅覆盖三个方向，不代表六个方向都通过。

### 位置判定

- 可重排：回到同一语义文字位置/段落；不同屏幕排版后的页码不要求相同。准备可唯一识别的合法测试内容锚点，不只比较百分比。
- PDF：同一物理页；如果当前合同保存页内位置则同时核对。漫画：同一图片资源/页，及已承诺的页内位置。
- 音频：同一音轨与时间位置；从已保存时间点恢复后的暂停位置误差建议不大于 2 秒，计入实际音频 seek 粒度与测量方式并在测试前冻结。
- 首页、详情和阅读器显示取各自实际语义：显示进度与真实位置不能混用，读取不同卷册不得串写。
- “已读状态”独立于阅读位置；标记已读不能制造一个虚假的恢复位置，用户主动往前翻也不能被最大百分比策略拦截。

### 时间与持久化目标（建议值，测试前冻结）

- 自动保存间隔建议上限 5 秒；正常退出/暂停触发的最后已捕获位置要可靠保存。
- 网络健康时，一次待同步记录进入可发送状态后 5 秒内完成服务端确认；另一端重新进入同一资源能取得确认后的进度。
- 强杀保证的是最后已成功持久化的位置，不能承诺尚未落盘的一瞬间也不丢。未确认位置损失不得超出冻结的保存间隔。
- 对“不足 5 秒立即退出/切后台”和“保存期间立刻强杀”分别测试，不能用等待很久后的单一恢复测试代表全部。

### 异常与竞态必测

1. 正常返回、App 前后台、系统回收、进程重启、浏览器刷新以及当前版本服务重启。
2. 已打开/已具备合法本地资源的阅读断网 → 保存待同步 → 恢复网络 → 重试确认；本要求不扩展独立离线登录或离线浏览能力。
3. 请求超时但服务器已保存 → 相同 mutation 重试；不能重复生效或覆写后来确认的新状态。
4. 新进度产生后旧请求才回包；旧确认只能清理匹配的 pending，不能删掉新 pending。
5. 同一账号两端写入、未提交的离线位置迟到、用户主动回读，按已冻结竞态语义核验，并记录用户可见结果。
6. 账号切换、服务器切换、不同资源/卷册，不能相互覆盖或越权。
7. 显式从某章/页进入只在本次入口生效；后来读到别处再重建，不能又跳回最初目标。
8. 已经打开的阅读会话不被另一设备的写入强行跳转。

当前 ADR 0028 明确：服务端按事务提交顺序最后写入生效，不按客户端捕获时间或最大百分比排序。尚未提交的离线位置晚到时，可能成为新的当前位置；与“已成功 mutation 的幂等重放”不是同一个场景。本轮不擅自改协议，但必须实测并在报告写出这种用户可见行为。若负责人认为不可接受，登记产品阻塞项，再单独授权修正；不得把这个事实写成“任何情况下都不会回退”。

若保留 OPDS 进度承诺，第三方协议与第一方 v5 的互通加入此门禁；不以旧数据兼容不在范围为理由跳过当前新数据上的 OPDS 功能。

## RG-05：超大书库下扫描与前台可用性

### 核心要求

扫描吞吐不是最高优先级。允许扫描慢，不允许因为扫描造成服务崩溃、持续不可用、进度丢失、源文件损坏或常规阅读被拖死。

### 测试前冻结的环境

- 服务器/NAS CPU、内存、磁盘、文件系统、挂载方式、操作系统；服务容器的 CPU/内存预算；数据库位置；网络带宽与延迟。
- 建议使用目标用户级别的低功耗 NAS 基准（例如 N100/8 GB）；这只是建议，不是用户已确认拥有该设备，也不宣称所有机器均可达标。
- 不能只拿高配开发机结果推断低配 NAS。若仅能测开发机，记录已测配置与能力边界，目标基准缺失记 BLOCKED。
- 固定扫描并发、元数据策略与核心配置；并发用户数、文件分布和采样方式不能测试后改写。
- 性能阈值是本门禁提出的产品目标，执行前由负责人冻结；未冻结时不得给出性能 PASS。调整须说明理由并重新测试，不因失败临时放宽。

### 数据规模与真实性

- 阶梯覆盖 1 万、10 万、30 万级。每级分别记录文件、目录 Node、Book、ReadableResource、Asset、总字节及各类占比。
- “30 万节点”不等于“30 万书”。目标为 30 万级有效书籍/可读资源，不能用一部漫画的 30 万张图或 30 万目录节点偷换。
- 全程真实遍历/解析/入库，可使用合法生成的有效测试读物加代表性真实 corpus；不能只预填数据库、使用空文件或错误格式快速跳过。
- 大小分布和媒体比例写入清单，包含各媒体的代表性内容；一批极小 TXT 只能证明对应 TXT 工作负载，不代表重型漫画/PDF/音频扫描全部通过。
- 同时使用：已有可读书库 + 正在增长/扫描的大书库，验证已有内容不被扫描影响；并抽查新入库内容何时可读取。
- 至少完成一轮 30 万级全量扫描和一次相同源文件的重复扫描，核对不重复/不丢数据。扫描完成没有固定耗时上限。

### 并发场景与时长

- 扫描与解析/入库/实际启用的元数据任务持续处于忙碌状态，不能只测任务队列创建后闲置。
- Web、Android、iOS 同时在线，至少三条活动会话：浏览/搜索、电子书或漫画/PDF阅读、音频播放，轮换平台和媒体覆盖。
- 每级至少 30 分钟并发观测；30 万级至少连续 2 小时，且其中扫描持续活跃；另外保留全量扫描完成证据。
- 在持续压力下进行进度写入、退出重进、客户端重连；在隔离测试环境执行一次受控服务重启和任务恢复验证。
- 采集同一数据集、设备、网络、发布产物的空闲基线与扫描期间数据，分别记录冷/热路径和不同媒体，不以平均值混盖长尾。

### 建议冻结的定量阈值

下表 p95 表示 95% 的对应请求/操作不超过该时间。它不是全系统混算的一个 p95；列表、详情、搜索、保存、各媒体分别统计。

| 项目 | 建议通过阈值 | 测量边界 |
|---|---|---|
| 服务稳定性 | 无扫描诱发 OOM、崩溃、重启风暴、不可恢复死锁、数据库损坏、源文件损坏 | 全部压力区间和扫描完整周期 |
| 列表/详情 API | p95 ≤ 2 秒 | 认证成功的正常请求，经实际入口/代理；不包含读物全文件传输 |
| 搜索 API | p95 ≤ 3 秒 | 已冻结典型关键词与筛选条件，命中/无命中、不同分页分别记录 |
| 进度写入确认 | p95 ≤ 2 秒；已确认数据零丢失 | 客户端发送到服务端明确确认；和 RG-04 保存间隔分别度量 |
| 已加载内容翻页/切换 | p95 ≤ 1 秒，无连续无响应超过 5 秒 | 已就绪资源和正常样本；不能用此项替代首次打开或下一章/页按需请求测试 |
| 新打开/跨章/按需取页 | 正常样本 p95 ≤ 10 秒；大文件按传输、解析、首屏分段，较空闲基线的扫描额外耗时 p95 ≤ 3 秒 | 相同文件与网络；完整原文件传输不硬塞入 1 秒翻页要求；用户应看到真实加载状态 |
| 音频连续播放 | 任一 30 分钟连续段无扫描引发的超过 2 秒中断或持续缓冲 | 稳定测试网络，同一媒体/编码，记 underrun 与系统中断原因 |
| 核心 API 成功率 | ≥ 99.9%，无超过 5 秒连续前台不可用区间 | 分端点统计；有意注入的鉴权错误/坏文件与计划重启单列，不能混入掩盖失败 |
| 内存 | 不超过预先冻结的安全工作集预算；无随已处理数量持续无界增长或持续 swap 导致前台超时 | 记录总服务工作集、RSS、缓存、容器上限和系统余量，不只看单进程 |
| 扫描任务 | 有持续可观察进展，坏文件有记录，完成后计数符合期望，重扫不重复 | 队列接收不等于解析入库完成；不能虚构进度或静默跳过大量有效文件 |

端点性能统计建议每个核心读/写端点至少 1,000 个样本；不足则记录样本数，不据少量点击断言高成功率。原始延迟、错误、超时均保留。CPU 使用率高本身不是失败，前台响应和资源失控才是判定对象。

原始监控建议每 5 秒采集 CPU、内存、I/O、队列、DB 锁等待等，并保留请求级耗时。只需足以验证的采集脚本和图表/数据，不新增生产监控平台作为发布前置。

## 3. 证据与缺陷管理

每个 PASS 必须指向：测试 ID、RC commit、产物 hash/digest、环境/账号角色、样本 ID/hash、实际步骤或命令、预期/实际结果、时间、日志/报告/截图/录屏路径、执行人。

- 证据类型分为静态源码、自动测试、发布物真机/E2E、压力实测，不能互相替代。
- 截图可证明页面结果，不单独证明请求次数、持久化提交或压力响应；这些需要对应数据。
- 错误日志脱敏；不记录密码、token、用户书籍正文或完整 Locator 文本。测试锚点采用合法、可公开测试内容的标识。
- 缺陷必须有门禁归属、严重级别、复现步骤、影响平台/格式、证据、修复 commit、回归结果。仅文档中的旧问题先标“待复现”，不能冒充当前确认缺陷。
- 当前没有发现记录不等于已知缺陷为零。首轮审计未执行前，总体结论为 NOT_RUN / 尚未具备放行依据。

## 4. 执行顺序

R0：将本门禁落库，冻结范围/阈值，盘点真实执行入口与环境，填充矩阵并创建证据/阻塞项记录；不改业务、不批量修复、不实际发布。

R1：全新部署与真实客户端主流程冒烟，尽早验证签名/IPA可导出条件，同时跑一轮扫描期间前台可用性预检。

R2：按五个门禁逐项执行，登记已复现阻塞项，小批修复并补对应回归，不按陈旧审计整批重构。

RC：冻结候选 commit，完成所需完整回归、双端真机、真实 OPDS 和全量压力验收；签收的是对应产物，而不是一个宽泛分支名。

Release：所有适用硬门禁 PASS、P0/P1 为零、产物齐备，经负责人明确授权后执行打 tag/推送生产产物/发布操作。本轮建立文档并不授权这些外部写操作。

## 5. 核对依据

以下为本次制定门禁使用的源码与文档，不是当前运行验收证据：

- `README.md`：公开格式、部署架构、初始化和 OPDS 能力声明；其中部分移动端阶段说明仍需按当前源码核实。
- `packages/reader-contracts/reader-safety-policy.json`：可重排、PDF、压缩包/目录漫画、音频的格式与安全边界。
- `packages/reader-contracts/README.md`：安全策略、契约和物理设备验证边界。
- `apps/api-python/app/contracts/media_capabilities.py`：格式驱动能力边界。
- `apps/api-python/app/modules/opds/presentation/http.py`：认证、目录及进度协议入口。
- `apps/api-python/app/infrastructure/opds_runtime.py`：OPDS 跨能力适配器。
- `docs/adr/0028-reader-v5-opaque-position-report.md`：当前 v5 保存、重试、位置/展示及写入顺序。
- `docs/testing/test-execution-policy.md`：发布完整回归、iOS物理设备证据要求；历史测试数量不得当作当前规模。
- Apple 官方文档：Distributing your app to registered devices；Archive export files；Export an iOS, tvOS, or watchOS app。核查日期 2026-09-06。
- OPDS 官方规范/草案：OPDS Catalog 1.2；OPDS Progression 1.0；Authentication for OPDS 1.0。进度为独立扩展能力，不能推定所有目录客户端均实现。核查日期 2026-09-06。

## 6. R0 当前工作树发布范围与执行入口（静态核实）

以下来源均于2026-09-06读取当前工作树，不表示运行通过。模板中的外部规范核查日期属于原资料记录，R0没有重新联网核验；本轮以实际源码、现有配置与测试入口建立计划。后续冻结RC时须重核有变化的来源。

### 服务、构建、初始化与导入

| 范围 | 当前实际入口 / 源码锚点 | 发布矩阵含义 |
|---|---|---|
| 服务组成 | `scripts/start-unified-app.sh:41`：prestart→Uvicorn/API→Python Worker→Next Web→网关；`scripts/unified-http-gateway.mjs:11`：/api及/opds到API，其余到Web；`apps/api-python/app/worker/main.py:41` | 同一服务交付包含Web/API/Worker；不能只验静态页面 |
| 对外部署 | `README.md:55`声明linux/amd64与linux/arm64；`apps/web/Dockerfile.prod:74`；`docker-compose.prod.yml:1`暴露可配置端口并挂载storage/library | ART-02逐架构部署；采用专用隔离配置和候选digest，不能直接把可变prod镜像当RC。当前本地docker-compose.yml另有无关服务，不能盲目启动整份本地配置 |
| 镜像构建 | `.github/workflows/fnos-package.yml:164`有Dockerfile.prod/双架构构建；`scripts/publish-docker-hub.sh:127`默认含push | 仅登记来源，不执行发布脚本/工作流外部写入；无推送RC本地构建参数与隔离部署覆盖文件待补 |
| 附属包 | `deploy/fnos/README.md:12`、根package.json的fnos:build/validate | FNOS已有入口；是否随本次交付清单使用由负责人决定，不替代双架构后端，也不另增硬门禁 |
| Android | `apps/mobile/androidApp/build.gradle.kts:9`：com.ermao.library、1.0.0/build1；`apps/mobile/gradle/libs.versions.toml:24`：minSdk26；`.github/workflows/mobile.yml:199`只有Debug组装/单测/lint/shared任务 | wrapper与Android application模块存在，但未找到仓库正式签名配置或正式Release脚本；正式构建/签名命令待补，不能拿assembleDebug代替 |
| iOS | `apps/mobile/iosApp/ErmaoLibrary.xcodeproj/xcshareddata/xcschemes/ErmaoLibrary.xcscheme:111`有Release ArchiveAction；`project.pbxproj:1258`为Automatic signing、已设Team、1.0.0、com.ermao.library、iphoneos、最低iOS17 | Team字段存在不证明有效证书/描述文件；可从Xcode现有scheme执行Archive，实际export/ExportOptions与IPA安装方案待补；未找到可复用archive/export脚本。必须Mac+Xcode+授权真机，不禁用签名 |
| 初始化/管理员 | `apps/api-python/app/modules/auth/presentation/http.py:210` GET /api/auth/setup/status；:221 POST /api/auth/setup；`apps/web/features/settings/setup-page.tsx:82`提交管理员，:103加库 | INI-01/02从无用户新库开始，重复初始化应拒绝，无默认管理员 |
| 组织模式与建库 | `apps/web/features/settings/model/organization-mode.ts:1`：FLAT/VOLUMES；`apps/api-python/app/modules/imports/presentation/http.py:227` POST /api/libraries，:292更新/启用触发导入 | IMP-01两模式分别建新根，不能只凭旧设计推断更多模式 |
| 上传/扫描/重试 | `apps/api-python/app/modules/imports/presentation/writes.py:104` POST /api/books/import；:261 POST /api/libraries/{library_id}/scan；:295 POST /api/library-import-tasks/{task_id}/continue；:328 SourceNode继续/缺失项；`apps/web/features/import-tasks/import-tasks-page.tsx:128`任务轮询和继续导入 | IMP-03..06使用真实用户入口；不编造暂停/取消API |
| 自动与手动扫描 | `apps/api-python/app/modules/imports/application/readable_resource/request_library_scan.py:16`包含STARTUP/WATCHER/PERIODIC/UPLOAD/MANUAL/ENABLE；`tests/integration/modules/imports/test_source_snapshot_semantics.py:299`自动保留缺失，:402手动成功扫描清理缺失拓扑 | IMP-06对照不同意图；测试显式删改只在专用源目录，不清真实旧库 |
| 计数 | `apps/api-python/app/modules/imports/application/readable_resource/scan_source_tree.py:50`分别nodes_inserted/resources_created/tasks_enqueued；现有模型区分LibrarySourceNode/LibraryBook/LibraryReadableResource/LibraryResourceAsset | LOAD必须与源文件事实对账；队列数/节点数不能代替有效书籍数；规模负载与计数导出命令待补 |

### 格式、引擎与样本来源

| 范围 | 权威源码锚点 | 实际支持/验收边界 |
|---|---|---|
| 格式与安全唯一源 | `packages/reader-contracts/reader-safety-policy.json:19` EPUB、:36 FB2、:55 TXT、:72 MOBI、:89 AZW、:106 AZW3、:124 PRC、:141 PDF、:158 CBZ、:176 ZIP、:193 CBR、:211 RAR、:229 IMAGE_DIR | 13类全部保留三端矩阵；只有生成规则能决定安全动作/预算，不复制私有阈值 |
| 后端导入适配 | `apps/api-python/app/modules/imports/domain/resource_adapters.py:64`：EPUB/PDF独立，TXT/FB2文本，MOBI家族共用，漫画归档共用，图片目录与音频目录；`.../infrastructure/readable_resource/adapter_registry.py`注册实现 | 匹配适配器不等于解析或真机可读；同一扩展别名仍需源格式样本 |
| 第一方读取形态 | `packages/reader-core/src/format-capabilities.ts:3`；AGENTS.md Reflowable Download-Then-Read | 七种可重排下载校验完整原文件再读；PDF/漫画有界读取；音频独立播放，不允许派生EPUB或隐藏章节兜底 |
| Web引擎 | `apps/web/features/reader/v3/adapters/readium-publication.ts:616`分派EPUB、TXT/FB2、MOBI家族；`.../original-publication/mobi-publication.ts:96`共用C ABI；`apps/web/package.json:33`锁Readium navigator2.8.2/shared2.4.0、PDF.js6.1.200 | Readium TS+内存原格式解析；PDF.js与漫画适配；依赖锁不等于运行证据 |
| Android引擎 | `apps/mobile/androidApp/src/main/kotlin/com/ermao/library/features/reader/infrastructure/ReadiumEpubSession.kt:208`；`ReadiumComicSession.kt:163`；`AndroidReaderCapabilities.kt:8`；`apps/mobile/gradle/libs.versions.toml:21`Readium3.3.0 | 原生Readium+FB2/TXT/MOBI工厂；PDFium、漫画归档/图片目录；13类已登记能力，逐格式真机验收 |
| iOS引擎 | `apps/mobile/iosApp/ErmaoLibrary/Features/Reader/IosReadiumRuntime.swift:52`；`IosReaderComposition.swift:537`；`apps/mobile/iosApp/verify_readium.py` | Readium Swift3.9.0当前批准基线；原格式工厂/PDF/漫画13类；SDK校验不能替代实际适配器/真机 |
| TXT编码 | `apps/api-python/app/modules/publications/infrastructure/txt_adapter.py:75`、`apps/web/features/reader/v3/original-publication/text-decoder.ts:16`、Android `TxtReadiumPublicationFactory.kt:154` | UTF-8、BOM UTF-16LE/BE及GB18030候选；逐编码正常/复杂样本与iOS适配需实测，不把UTF8一例外推 |
| 漫画环境 | `apps/api-python/app/infrastructure/comic_archives.py:312`检查unrar/unar后端；`test-data/library/comics/CORPUS.md:3` | 当前CBZ/ZIP/CBR/RAR小样本存在，RAR为RAR5 stored；压缩RAR/大图/复杂样本另补；缺外部工具是环境阻塞，不能改为格式拒绝 |
| corpus | `test-data/library/mobi/CORPUS.md:3`与SHA256SUMS/GENERATED-SHA256SUMS；`test-data/library/fb2/CORPUS.md:3`；test-data/library/{epub,novels,pdf,comics}；packages/reader-contracts/fixtures | 实际文件与R0散列清单见acceptance-matrix.md §3.1；现有AZW/PRC为同源扩展名变体，不能代表独立内部变体；缺完整音频/复杂/规模样本 |
| 音频接收与生命周期 | `packages/reader-contracts/reader-safety-policy.json:274`旧AUDIOBOOK/M4B/M4A/MP3为RECEIVE_ONLY；:941音频扩展/MIME；:995 codecDecision=ENGINE_CAPABILITY；`apps/api-python/app/modules/imports/application/audio_types.py:19` | 新AUDIO/AUDIOBOOK_DIR与旧接收枚举不同层次；不能漏测.m4b/.m4a/.mp3源文件；枚举不等于设备解码能力 |
| 音频真实元数据 | `apps/api-python/app/services/audio_metadata.py:219`、:333、:776、:1044；README.md:46–50 | Mutagen/ffprobe识别真实流，禁止从MP4臆测AAC；不转码；README区分常用与兼容导入，非每浏览器均可播 |
| 音频三端 | `apps/web/features/audio/audio-playback-provider.tsx:90` HTMLAudioElement；`apps/web/features/audio/api.ts:44` MIME仅提示；Android `features/audio/infrastructure/AndroidAudioPlaybackService.kt:22` Media3/ExoPlayer，`features/audio/application/AndroidAudioPlaybackRuntime.kt:1356`；iOS `Features/Audio/IosAudioEngine.swift:123` AVPlayer | 解码器失败是引擎能力类别；现无完整容器×codec×设备承诺表，DEC-02须在执行前冻结。当前有真实播放器入口，不能拿早期“音频不可用”阶段文字缩范围 |

表内缩写Android features路径均相对`apps/mobile/androidApp/src/main/kotlin/com/ermao/library/`；iOS Features相对`apps/mobile/iosApp/ErmaoLibrary/`，同目录类名指该表给出的目录，不是新脚本。

### OPDS 与 Reader v5

| 范围 | 当前调用链 / 源码位置 | 必须验证的含义 |
|---|---|---|
| OPDS对外承诺/认证 | `README.md:38`；`apps/api-python/app/main.py:256`挂载；`apps/api-python/app/modules/opds/presentation/http.py:145`认证、:247目录、:391进度、:465媒体；`apps/api-python/app/modules/opds/application/settings.py:24`启用需合法publicBaseUrl | 实际目录 /opds/v1.2/catalog；静读天下与第二独立客户端均做Basic challenge、authentication.json、目录/分页/搜索/封面/下载；publicBaseUrl需要正确配置，不推定代理自动修正 |
| 原文件与Range | `apps/api-python/app/infrastructure/opds_runtime.py:784`send_file；`apps/api-python/app/modules/media/infrastructure/http_streaming.py:727` HEAD/ETag/Last-Modified/206/416/Content-Range，:210 If-Range；runtime:809 PSE页 | 实际 /opds/v1.2/resources/{resource_id}/asset 和cover支持GET/HEAD；原文件hash/Range及权限须证据；PSE转换页不能代表原始文件Range；统一网关和实际反代均要保留Authorization/公开URL |
| Progression风险 | `apps/api-python/app/infrastructure/opds_runtime.py:660`调用`apps/api-python/app/bootstrap/reader.py:27` retired v4服务；`.../application/resource_reader.py:299`与`.../infrastructure/resource_repository.py:338`仍写旧ReaderResourceProgress；`tests/contract/api/test_opds_http.py:165`断言旧表 | 路由为 /opds/v1.2/resources/{resource_id}/progression（GET/PUT）。RISK-01：有对外路由不等于第一方v5互通。新数据上协议GET/PUT和真实扩展客户端联调均保留为硬条目；不能以不迁移0.x为理由跳过或删声明 |
| v5服务端写入 | `apps/api-python/app/modules/reader/application/resource_reader_v5.py:170`：授权/序列化/payload hash→查mutation receipt→新写入及commit；`.../infrastructure/v5_repository.py:203`在同事务写current+receipt、revision递增 | 第一方入口为GET /api/reader/v5/resources/{resource_id}/bootstrap与PUT /api/reader/v5/resources/{resource_id}/progress；最后事务提交生效，不按客户端捕获时间/最大百分比；相同mutation同payload重放返回旧acceptedRevision和当前snapshot，不再改current；同ID异payload冲突 |
| v5本地与ACK | `apps/web/lib/reader/v5-sync-coordinator.ts:263`、`v5-storage.ts:309`；`apps/mobile/shared/src/commonMain/kotlin/com/ermao/library/shared/modules/reader/application/ReaderPositionSyncCoordinator.kt:42`、:115 | 完整报告与latest pending原子落地；重试同body/mutation；ACK只清匹配pending，不能清新位置；显式入口→pending→server→出版物的恢复顺序需真机核对 |
| 迟到首次提交 | `docs/adr/0028-reader-v5-opaque-position-report.md:23`与上述service/repository | 离线未提交位置晚到可以成为current，与已成功mutation重放不同；POS-07实测并签收，不承诺无条件永不回退 |
| 现有协议辅助测试 | Python `tests/contract/api/test_opds_http.py`、`tests/unit/modules/opds/test_http.py`、`test_protocol.py`、`tests/contract/api/test_reader_v5_progress.py`、`test_reader_v5_contract.py`（均相对apps/api-python）；Web `apps/web/lib/reader/v5-sync-coordinator.test.ts`、`apps/web/features/reader/v3/local-resume.v5.test.ts` | C-09可用这些确实存在的测试路径；它们不替代真实客户端、下载Range或三端六方向 |
| 原生进度辅助测试 | `apps/mobile/shared/src/commonTest/kotlin/com/ermao/library/shared/modules/reader/ReaderPositionSyncTest.kt`；`apps/mobile/androidApp/src/androidTest/kotlin/com/ermao/library/features/reader/infrastructure/ReaderV5PersistenceInstrumentedTest.kt` | fake/shared测试不证明离线首次迟到真实网络竞态；真机仪器测试需确认runner和非破坏性安装策略，不能默认connected任务卸载用户应用 |

### R0之后的最小验证批次（仅计划，本轮不执行）

先交接ENV-01..07与DEC-01..04：确定可追溯RC、隔离服务器/双架构目标、Android签名真机、Mac/iOS签名与IPA安装方式、两OPDS客户端及扩展客户端、已有corpus补缺与性能冻结表。随后优先ART-03/04构建安装可行性、INI-01新库小闭环、OPDS-04新数据互通探针、POS-05/06/07小样本时序验证；条件齐备后再安排LOAD-00空闲基线与扫描并发预检。完整规模和全部格式回归仍按矩阵分批执行，不因R0文档完成自动启动。
