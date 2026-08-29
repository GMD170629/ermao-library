# App 在线优先阅读与 2 GiB 准入：实现及验证记录

> 历史记录：本文记录 2026-08-28 当时的 online-first 实现与证据。
> 可重排交付合同已于 2026-08-29 被 ADR 0025 的“原文件下载后本地解析”取代；
> 本文不得作为当前产品行为或验收标准。

日期：2026-08-28。状态：实现及聚焦自动化已通过；真机完整流程尚未验收。本文不把准入测试当作真实 2 GiB 文件打开能力的证明。

## 所有权与迁移

- `ReaderLaunchCoordinator` 是 KMP 启动决策入口，返回在线、已验证本地、下载过渡或不可打开；`ReaderAdmission` 拥有 2 GiB（2,147,483,648 字节，含边界）准入规则。目录资源按原始成员总字节数计算，溢出拒绝。
- 复用 Downloads 的公共 `DownloadBootstrapGateway`、`DownloadCatalogRepository`、`DownloadResourceRuntime`。Reader 不实现下载器；原文件传输、队列、去重、恢复、版本检查、临时文件和完成发布仍由现有 Downloads 所有。
- Android 阅读按钮、继续阅读及章节目标经 `MainShell` 进入 `ReaderActivity`；iOS 相应入口经 `MainTabView` 进入 `IosReaderBootstrapHost`。原本去详情页的封面行为不改。下载中心继续直接打开已验证原文件，无需等待在线 bootstrap。
- Android 下载运行时由 Application 的账号生命周期持有，移除页面销毁时取消全部下载的装配；iOS Reader 注入 App 已持有的 `DownloadCenterStore`。原下载入口和过渡页复用同一实例。
- 在线大小/解析预算超限、Range 不支持才允许一次下载分流。鉴权、网络、损坏、版本变化不分流。下载启动前及完成后验证预期资源版本，防止观察到另一版本后误开。
- 取消关闭会撤销观察和自动打开；本次启动/恢复的传输暂停，已有运行中任务仅解除观察。账号变化隔离任务和 UI，异步解析完成前再次检查账号/取消。下载后解析失败不重复下载，也不自动返回在线模式。
- 章节目标传到本地启动；已有进度仍由原 Reader 进度存储和定位合同负责。无新进度体系、正文缓存、转换文件、虚拟章节、索引或增量解析器。
- 删除触及的无调用 `ApiClient.cancelQuietly`、本地失败页旧“在线阅读”回跳、废弃启动判断及页面级下载装配。没有恢复 Reader 下载端口。未进行仓库无关功能的全面旧代码清理。

## 产品与引擎边界

普通在线路径仍按整章、页、Range 请求，不主动下载或后台补齐整本。仅需要下载时展示封面、书名、原因、排队/下载/暂停/失败/解析状态、真实字节/百分比及取消/重试。解析阶段不显示假百分比。

TXT/FB2 的应用整文件 64 MiB 门槛移除；MOBI 的应用 512 MiB 门槛由 KMP 参数替换。整文件大小与偏移保持 Long/Int64/C uint64_t；已知 Kotlin 数组/String 容量边界在分配前返回错误。章节、图片、XML、解压、正文装饰等独立引擎/安全预算不机械上调；仍接受卡顿和无法优雅恢复的系统内存终止。

后端仅给已有超预算路径增加 `PUBLICATION_ONLINE_LIMIT` 类型错误，并保证 Library 原资源元数据仍可取得；不增加服务端预算。Web 前端及依赖补丁没有因本能力而修改。AGENTS、架构和 ADR 明确区分原生允许普通 SDK 缓存与 Web 原策略。

## 已执行检查

| 检查 | 结果与证据范围 |
| --- | --- |
| KMP Android host tests | 333 通过，0 失败/跳过；`/tmp/ermao-launch-tests.log` |
| Android unit tests | 146 通过，0 失败/跳过；同一日志 |
| Android debug APK | `:androidApp:assembleDebug` 成功 |
| iOS iphoneos/arm64 App | 实机 destination 的签名 `build-for-testing` 成功；`/tmp/ermao-reader-device-build.log` |
| iOS 真机聚焦测试 | 最终 47/47 通过，0 失败/跳过；ReaderSecurityTests、LocalizationTests、DownloadStoreTests、MobiCoreTests、MobiPublicationFactoryTests |
| 后端聚焦合同/单元测试 | 28 通过；`/tmp/ermao-launch-python.log` |
| 后端 Ruff | 本次触及的 9 个 Python 文件 check 和 format --check 通过 |
| Web i18n | `pnpm i18n:check` 通过，2053 条；`/tmp/ermao-launch-i18n.log` |
| 原生文案静态检查 | iOS 8 个新增 Reader key 均含 en/zh-Hans；Android 两份资源各 10 个新增 key；实际渲染仍需真机流程检查 |

新增及复跑的关键用例：

- 2 GiB−1、2 GiB、2 GiB＋1；目录求和/溢出；准入与整数组分配错误分离。
- 模拟续传偏移 2 GiB−1、完成累计量 2 GiB、任务 JSON 持久化及百分比计算。这里没有分配或传输真实 2 GiB 文件。
- 空目录在线启动不创建下载任务/文件；已验证本地启动不调用元数据网络端口。
- 仅指定在线限制分流一次；已知本地边界拒绝；资源版本变更在创建任务/调用传输前失败，完成观察也不接受另一版本。
- 现有 Downloads 并发去重、取消暂停/原偏移恢复、重试、进程中断恢复和完成原子发布测试。
- `OnlinePublicationSession` 元数据不读取章节、并发当前章请求合并、切章淘汰和关闭；bounded transport 在错误/超限/版本错误响应体永不结束时仍立即拒绝、取消，以及请求体中途断开不视为成功。
- 后端 TXT 超单章/超整文件预算仍能获取原资源描述，Reader bootstrap、manifest、positions 返回类型化 413，原文件不改变。
- 合法封面尺寸/版本查询参数不能阻止 Downloads 元数据或 Reader 启动；外域、路径逃逸、fragment/control characters 仍拒绝，原文件路径仍不接受查询参数。此兼容问题由扩大的 iOS 真机 Live Downloads 回归发现，修复没有放宽原文件安全校验。

复现命令（仓库根目录以外的命令注明目录）：

```sh
# apps/mobile
ANDROID_HOME=/Users/guyu/Library/Android/sdk ./gradlew :shared:testAndroidHostTest :androidApp:testDebugUnitTest :androidApp:assembleDebug --console=plain

# 仓库根目录；仅构建，不运行设备
xcodebuild -project apps/mobile/iosApp/ErmaoLibrary.xcodeproj -scheme ErmaoLibrary -destination 'id=00008150-0011112211A0C01C' -derivedDataPath /tmp/ermao-reader-launch-ios-tests build-for-testing

# apps/api-python
.venv/bin/python -m pytest tests/contract/api/test_reader_publication_http.py tests/contract/api/test_fb2_publication_http.py tests/unit/modules/publications/test_snapshot_cache.py tests/unit/modules/publications/test_txt_adapter.py tests/unit/modules/publications/test_fb2_adapter.py

# apps/web
pnpm i18n:check
```

## 真机及未完成的验收

本次检查时 `adb devices -l` 没有 Android 物理设备；没有使用模拟器。iPhone 17 Pro Max（iOS 26.6，arm64，UDID `00008150-0011112211A0C01C`）已运行本版签名测试包。`/tmp/ermao-reader-online-first-device-20260828.xcresult` 记录 17/17 通过，0 失败/跳过，日志为 `/tmp/ermao-reader-online-first-device.log`。其中包括实际原生文本渲染、TXT/FB2 安全和内容保持、两个新增下载/准入测试，以及中英文文案检查。设备的自定义名称是“Xiaomi 17 Pro Max”，xcresult 的实际 modelName 为 iPhone 17 Pro Max；不是 Android 或模拟器。

扩大回归的第一轮 32 项有 2 项 Live Downloads 失败（`/tmp/ermao-reader-download-mobi-device-20260828.xcresult`）。根因是旧 Downloads 拒绝服务端封面查询参数；补齐命名校验后定位为 `DOWNLOAD_COVER_PATH_INVALID`。修复并补安全回归后，最终 `/tmp/ermao-reader-download-cover-fix-20260828.xcresult` 的 **47/47 全部通过，0 失败/跳过**，日志为 `/tmp/ermao-reader-download-cover-fix.log`。包含真实服务器 EPUB 下载及任务复用、AZW3 原文件 SHA-256 校验和 libmobi 解析、MOBI 原生 Publication、存储原子发布及恢复。它们不是下载过渡页交互测试。

测试结束后第一次普通启动 PID 未在后续列表中保留，未据此认定启动通过。重新捕获控制台后未出现异常；11:19 再次通过 devicectl 无 fixture/语言覆盖参数正常冷启动 App，12 秒后确认 PID 37134 仍存活，保持用户数据。最终证据为 `/tmp/ermao-reader-final-launch.json` 和 `/tmp/ermao-reader-final-processes.json`；未将第一次退出归因为已确认的代码故障。

iPhone 的其他任务安装/冷启动证据只说明 App 可启动，不说明 Reader 新流程通过；以上 Reader 聚焦测试也不等同完整在线到下载 UI 验收。

以下仍缺本版实际设备完整证据：空缓存阻断原文件和非当前章仍显示正文；自动过渡的视觉/无障碍；下载后目标/进度恢复；返回或账号切换后迟到完成不打开；已有独立任务保留；空间不足；完成文件离线重开。现有单元/端口合同覆盖其中部分规则，不能替代原生完整链路验收。未测试全格式真实 2 GiB 文件成功率/流畅度，也不以此作为本版完成条件。

未运行全仓库 Python mypy/coverage 与 Web lint/typecheck/test；本能力没有修改 Web 业务代码。环境既有警告包括 Starlette/httpx 弃用，以及 iOS CBZ Readium、onChange、测试捕获和 AppIntents/方向配置警告；本版未升级 SDK 或扩展无关 UI 重构来处理这些基线问题。

一次 KMP 全套运行还暴露未改动的 `KtorShelfRepositoryTest.loadsAllShelfKindsAndResolvesMembershipFromDetail` 顺序偶发失败：实现并发查询，测试 Harness 按 FIFO 分发不同详情响应。复跑全套 333 项通过；未跳过/改弱此测试，也未把无关书架测试重构混入 Reader 改动。该基线不稳定性仍需书架能力范围内处理。
