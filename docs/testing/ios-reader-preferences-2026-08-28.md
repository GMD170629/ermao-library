# iOS 阅读设置直接提交 — 2026-08-28

> **版本后续更新**：本页保留升级前的历史证据。用户随后批准 iOS Readium 3.9.0；当前版本、防回退规则与验收见 [3.9.0 升级记录](ios-readium-3.9.0-2026-08-28.md)。旧版“SDK 不变”描述不再构成回退依据。

> 后续统一设置目录、偏好 v5、全格式重置及本轮真机结果见 [阅读设置统一验收记录](reader-settings-unification-2026-08-28.md)。下文保留此前实现与安装的历史证据，不能替代最新修改的验收。

## 问题与用户确认的边界

用户报告 iOS 调整字号提示无法应用阅读设置，并明确要求：重排交给底层阅读器，不在应用层校验或封装切换后的排版。

旧实现每次改变原生设置都会捕获首个可见 Locator、创建新 Navigator，并要求重排后的首个可见段落与之前完全相同。分页后同一段落可能处于新页中间，这个条件不能代表设置是否有效。原来的单次字号 UI 测试也可能因上次运行已保存相同字号而没有实际改变设置。

## 当前实现与复用 owner

- `IosReaderPreferenceEditor` 继续负责原生控件草稿、连续修改合并与提交；没有增加第二套设置流程。
- `IosReaderPreferences.readium(for:)` 继续作为设置到 Readium 的唯一映射。
- `IosReflowableReaderSession.executeControlPreferences` 在主线程同步检查控件可用性、保存设置，然后向现有 Navigator 调用一次公开 `submitPreferences`。字号、字体、行距、主题、阅读模式、重置和系统外观变化共用这个入口。
- `IosReaderPreferencesStore` 继续负责按服务器和用户隔离的持久化。保存失败发生在 SDK 提交之前，不修改已提交的设置。
- `IosReaderPersistenceGate` 继续抑制设置引起的进度事件，真实翻页后才恢复进度记录。

删除了设置路径中的 Locator 捕获和比较、重建 Navigator、80 次轮询、渲染器回滚、额外偏好队列、系统主题 Task、临时 applying 标记及 SwiftUI Navigator 身份重挂载。`submittedControlPreferences` 仅记录已经提交的原生偏好，用于去重；它不表示排版完成。

未修改共享精确进度比较、正常目录/书签/恢复导航、原始文件、在线阅读/下载边界或 Readium 固定版本。生产代码没有新增 JavaScript、DOM 几何检查或 SDK 私有接口。测试中的只读 CSS 检查只用于验证输出，不参与应用运行。

## 已执行的检查

真机：iPhone 17 Pro Max，iOS 26.6，`iphoneos` / arm64，自动签名。运行前确认配对、Developer Mode、连接及解锁状态；没有使用 Simulator。

| 检查 | 结果 |
| --- | --- |
| 修复前原有 EPUB UI smoke | 1 项通过；原测试可能提交相同字号，不构成本缺陷的否定证据 |
| 首轮 ReaderSecurity、ReaderPersistence、ReaderProgressContract、Localization 真机 XCTest | 43 项，41 通过、2 失败、0 跳过；失败详情见下节 |
| 最终上述四个套件和四种格式 UI 回归 | 47 项，44 通过、3 失败、0 跳过；未将局部断言通过记为整个套件通过 |
| EPUB、FB2、MOBI 真实书目 UI | 三项均通过：实际改变两个不同字号，无应用失败提示，关闭/重开后设置值保持 |
| 真实 session 字号路径 | UI 挂载前 18→20 成功，不需要首屏 Locator；长章中段和原生设置 Sheet 内 18→30→14 的实际 CSS、同一 Navigator 和持久化断言通过 |
| 相邻文字设置 | 三种字体、行高、五主题、系统明暗外观、恢复默认、连续修改、不可用控件拒绝及原始文件不变的断言通过 |
| 保存失败 | 非有限数导致 JSON 保存失败时，同一 Navigator、原设置、已保存值和实际默认排版均保持不变 |
| 设置与进度隔离 | 真实本地数据库中的完整进度 JSON 和事件数在重排、flush、后台及关闭后保持不变 |
| `pnpm i18n:check` | 2053 条消息通过，覆盖 zh-CN/en-US |
| `git diff --check` | 通过 |
| 正常 App 启动 | 最终签名构建已安装至连接的 iPhone；13:35:43 以非测试环境重新启动，13:40:26 确认同一 App 进程仍存在 |

UI 测试已改为两个不同方向的字号变化，并在关闭/重开后检查保存的最终值。正文断言等待实际 WebView 出现，不再把 Reader 外层容器出现当作正文已加载；未降低正文必须存在的断言。真实 session 回归使用原始 TXT、真实本地数据库和实际 SwiftUI/Readium 宿主，覆盖上述字号、字体、主题及进度隔离。

未新增用户可见文案。原有中英文 LocalizationTests 和 Web 词条检查通过；未将中文真机 UI 运行描述为英文 UI 验收。

## 未通过的检查与范围

1. `ReaderSecurityTests.testNativeTextControlsRenderBundledFontsAndThemesOnPhysicalDevice` 的连续滚动实际渲染断言失败。字号、字体、主题等直接提交断言通过，但切换滚动触发 SDK 内部章节重载后，DOM 再次出现首次缓存的 20px、暖色和分页列宽。该结果与 2026-08-27 的独立真机记录一致，不能称为所有阅读设置均已验收。根据本次用户指示，不恢复应用层重建、校验或排版补偿，也不擅自升级 SDK。
2. `ReaderPersistenceTests.testExactProgressRoundTripsWithoutCreatingDurableSyncState` 的两条断言仍要求新数据库包含旧 `reader_outbox` 和 `reader_sequence_counters` 表。该测试和数据库实现相对 HEAD 均无修改；当前数据库不创建这两个旧表。本次没有改数据库或通过恢复旧状态机让该测试通过。
3. `ContentDiscoveryUITests.testLiveTxtOpensFromWorkDetailOnPhysicalDevice` 在打开真实书目阶段失败，未进入字号设置。将 WebView 等待增加到 45 秒后仍失败，附件中的原生错误页明确显示“已下载的图书不再可用。”和“重新获取并打开”。因此不是单纯的视图等待问题，也不能宣称真实 TXT 书目端到端通过。该提示不能当作下载文件丢失的证据；用户追问后的只读诊断见下一节。本次没有删除用户下载、重新下载书目或修改下载恢复流程。本地原始 TXT 的真实 session 字号/字体/主题断言已通过。

构建还有未触及的 CBZ API 弃用、旧测试 Sendable 捕获、方向配置和 AppIntents 元数据提示；没有增加或抑制这些警告。没有跳过、降低或删除失败断言。

## 追问诊断：为什么提示已下载的图书不再可用

只读检查真机下载清单与文件属性后，确认本例不是文件被删除：该 TXT 的记录仍为 `completed` / `verified`，原始文件 `asset.txt` 存在、可读、不是符号链接，实际大小 1,539,839 字节，与 `expectedBytes`、`receivedBytes` 完全一致。未读取或输出书籍正文，也未修改设备上的记录或文件；这里不把文件大小一致当作全文内容校验。

已定位两个代码问题：

1. **旧下载记录未接入新版共享目录。** 该记录创建于 2026-08-26，缺少 `sharedTaskJSON`。`IosDownloadCatalog.listTasks` 直接跳过缺少此字段的记录，`listArtifacts` 又仅从这些 task 获取本地原件。`ReaderLaunchCoordinator.prepare` 因而看不到该下载，继续走在线启动。下载 UI 仍使用原生记录的 `isVerifiedOfflineCopy`，所以会出现界面显示“已下载 1 项”，阅读入口却没使用它的矛盾。`findTask` 有迁移分支，但阅读启动的目录查询不会调用它；不能以存在迁移函数就宣称读书路径已迁移。
2. **资源缺失文案混淆在线和本地。** 共享 `readerErrorCodeForFailure` 把包含 `MISSING` 或 `NOT_FOUND` 的错误映射为 `ResourceMissing`，iOS 再统一显示“已下载的图书不再可用。”。因此在线 manifest/positions/资源缺失也会显示这句文案。后续进一步确认：服务端还把 TXT 解析异常合并成了 `PUBLICATION_NOT_FOUND`，所以解析失败也会触发这句提示；不能只看客户端的 `CORRUPT_FILE` 映射推断实际原因。

本次附件是 session 的 `reader.reflow.screen` 错误页，按钮为“重新获取并打开”；结合当前启动代码和旧记录状态，可定位到遗漏本地原件后的在线 session 打开失败。结果包没有可导出的 App console log，未获得服务端原始失败码，故不进一步声称具体哪个在线接口 404 或服务器已删除文件。

旧下载记录兼容是独立发现，不能当作本次在线打开失败的根因，不应以删除下载或强制重下掩盖问题。后续已通过实际服务端原件定位到自写 TXT NUL 拒绝与错误被合并，修复和验证状态详见 `docs/testing/reader-online-errors-2026-08-28.md`。下载实现未因这次诊断修改。

## 本地证据

- `/tmp/ios-reader-preferences-baseline-20260828-1318.log` 与同名 `.xcresult`
- `/tmp/ios-reader-preferences-direct-20260828-1322.log` 与同名 `.xcresult`
- `/tmp/ios-reader-preferences-ui-20260828-1325.log` 与同名 `.xcresult`
- `/tmp/ios-reader-preferences-final-20260828-1328.log` 与同名 `.xcresult`：最终 47 项结果
- `/tmp/ios-reader-preferences-final-txt-attachments/23970649-1B3B-4CAA-BCF8-7FC9A7B36AC6.txt`：TXT 打开失败时的原生界面层级
- `/tmp/ios-reader-preferences-i18n-20260828.log`
- `/tmp/ios-reader-preferences-launch.json`：测试后正常启动结果
- `/tmp/ios-reader-preferences-running-process.json`：后续同一进程存活确认
- `/tmp/ios-reader-txt-download-manifest.json` 与 `/tmp/ios-reader-txt-download-file.json`：只读获取的下载记录与对应文件属性；清单仅用于本地诊断，不作公开附件

固定 SDK 公开接口和缓存调用链可对照 [EPUBNavigatorViewController](https://github.com/readium/swift-toolkit/blob/f7d10d2bf5876408feae14d634416f69d1473fd8/Sources/Navigator/EPUB/EPUBNavigatorViewController.swift)、[EPUBNavigatorViewModel](https://github.com/readium/swift-toolkit/blob/f7d10d2bf5876408feae14d634416f69d1473fd8/Sources/Navigator/EPUB/EPUBNavigatorViewModel.swift) 和 [WebViewServer](https://github.com/readium/swift-toolkit/blob/f7d10d2bf5876408feae14d634416f69d1473fd8/Sources/Navigator/EPUB/WebViewServer.swift)。本机 checkout 已核对同一 revision，未修改依赖源码。

## 后续修正：删除设置面板的加载反馈

此前只删除了 session 层的排版等待，外观和设置两个原生 Form 仍会在提交期间插入、移除一行转圈控件。这改变了表单布局，且该状态不来自引擎的排版完成回调。

本次删除编辑器中仅供该 UI 使用的状态字段和全部赋值、两个 Form 中的加载分支及其无障碍标识。复用的 `IosReaderPreferenceEditor` 仍负责草稿、顺序提交、最新值合并、失败恢复和退出时 flush；本地 `UserDefaults` 保存、现有 Navigator 的公开偏好提交及真实失败提示均保留。没有新增状态、延迟显示、隐藏占位或另一套提交实现。三个阅读形态共用这两个面板，因此均走同一删除后的实现。

旧 UI 测试不再等待被删除的控件消失，改为在两个不同字号变化后检查没有加载指示器、字号控件位置不变；保留设置成功与关闭重开后值一致的检查。仓库源码、测试与资源检索确认原状态和标识已无引用，该转圈原本没有本地化文案；现存设置失败词条仍有实际调用，不能作为无用文案删除。

本次验证：三个变更 Swift 文件的 iphoneos/arm64 语法检查通过，`git diff --check` 通过，`pnpm i18n:check` 验证 2,069 条中英消息通过。连接的 iPhone 当前为 unavailable，故本次改动未运行 XCTest/UI 回归、未重新构建签名包或覆盖安装；上文的早前真机结果不作为本次修改的验收证据。恢复连接后需验证两种设置面板、连续修改和本地重开。

### 恢复连接后的安装记录

2026-08-28 16:04（Asia/Shanghai），确认 iPhone 17 Pro Max 有线连接、已配对、已解锁且 Developer Mode 启用后，对该真机目的地完成 Release archive，签名校验通过。新的 Release 可执行文件不含已删除转圈的无障碍标识。通过覆盖安装更新 `com.ermao.library` 1.0.0（1），没有卸载或清除数据；16:04:17 正常启动，16:04:29 确认同一新 App 进程仍在运行。

构建与安装证据为 `/tmp/reader-ios-no-settings-spinner-build.log`、`/tmp/reader-ios-no-settings-spinner-install.json`、`/tmp/reader-ios-no-settings-spinner-launch.json`、`/tmp/reader-ios-no-settings-spinner-processes.json`；归档为 `/tmp/ermao-reader-no-settings-spinner-20260828-160121.xcarchive`。本次完成编译、签名、安装和启动检查，未执行设置面板交互 XCTest/UI 回归，不能将启动成功等同于上述交互验收。
