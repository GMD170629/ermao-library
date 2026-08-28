# iOS Readium 3.9.0 升级与验收 — 2026-08-28

## 版本与授权

用户明确授权升级 iOS Readium 至官方 3.9.0，覆盖此前“SDK 版本不变”的 iOS 3.8.0 基线。Android、Web、libmobi 和 PDFium 的版本不变；没有修改 SDK 源码或原始图书，没有引入私有接口、格式转换、替代阅读器或排版补偿。

- 官方版本：[Readium Swift Toolkit 3.9.0](https://github.com/readium/swift-toolkit/releases/tag/3.9.0)。
- 锁定提交：`de07026e9f825a5791f27a7ac4cd6bb1a784ab8d`，与官方 `3.9.0^{}` 一致；Xcode 工程固定 revision，SwiftPM 重新解析生成锁文件。
- 包含 [官方修复 #781](https://github.com/readium/swift-toolkit/pull/781)：公开偏好提交引起 CSS 更新后，SDK 清除带旧 CSS 的 HTML 资源缓存，非 HTML 缓存保留。
- 本机实际 checkout HEAD 与锁一致，`git status --short` 为空。其他 SwiftPM 依赖 revision 没有改变。
- 防回退规范：`AGENTS.md`、`.cursor/rules/architecture.mdc`、`docs/mobile-reader-architecture.md` 第 10/13/15 节。旧审计/测试保留原始证据，并标明已被新基线覆盖。

## 复用、迁移与删除

| 所有者 | 调整 |
| --- | --- |
| Xcode SwiftPM 依赖 | 原官方库引用固定到 3.9.0 提交；不设 3.8.x 回退。 |
| `IosOnlinePublicationFactory` | Manifest/positions 使用 SDK 的 `JSONValue` 和公开 JSON 解析接口；保留既有共享网络、资源容器与分阶段错误传递。 |
| `ReadiumSwiftLocatorMapper` | 使用 SDK 3.9 的排序 JSON 序列化，删除重复 Foundation JSON 反序列化/排序封装；新位置诊断版本为 3.9.0，旧 3.8.0 位置仍恢复。 |
| `IosReflowableReaderSession` | 书签序列化迁移到 throwing API，失败仍显示保存错误；导航 selector 读取 typed JSON 字符串；viewport 使用新公开 resources API。设置仍由原持久化所有者保存，再提交给既有 Navigator。 |
| TXT/FB2/MOBI/在线 Publication 工厂 | 原 `DefaultContentService` 保留，四处旧 `StringSearchService` 切到 SDK 公共 `ContentSearchService`；MOBI 额外元数据改为 typed JSON。 |
| 本地 PDF 会话 | 按 3.9 公开初始化接口移除不再需要的 HTTP server、导入及生命周期字段；保留原 PDF Navigator。在线 PDFium 不变。 |
| 漫画 | 继续原 CBZ Navigator/HTTP adapter，不在本次更换引擎；删除归档页面映射中已不抛错的多余 `try`。 |
| 版本校验 | `apps/mobile/iosApp/verify_readium.py` 是唯一版本校验实现，Xcode 原构建阶段与 Mobile CI 共用。检查官方 URL、准确 revision、SwiftPM 锁、运行时诊断版本和架构规范。 |

没有为设置重新打开图书、重建 Navigator、恢复位置、校验重排、添加 loading UI、修改进度协议或发起设置同步。正常目录跳转、进度恢复和关闭重开保留各自所有者。

## 已完成验证

设备：连接的 iPhone 17 Pro Max（设备显示名 Xiaomi 17 Pro Max），iOS 26.6；Developer Mode enabled、paired、解锁可用。自动签名 Team `W5G54L42KQ`。仅使用实际设备 destination，没有模拟器或关闭签名。

| 检查 | 结果与证据 |
| --- | --- |
| Xcode Debug 真机目标构建 | 通过。`/tmp/readium390-build2.log`。 |
| ReaderSecurityTests 17 项 | 全部通过，包含真实 WebKit CSP、NUL/编码、FB2、原文件保留、在线错误保真和文字阅读设置。 |
| ReaderProgressContractTests 6 项 | 全部通过；3.8.0 精确 Locator 在 3.9.0 恢复，完整锚点不变，仅新序列化键排序可变。 |
| MobiPublicationFactoryTests 8 项 | 全部通过；MOBI 家族实际解析、内存 Publication、懒读取和新 ContentSearchService 的结果位置/文本。 |
| 偏好持久化重点测试 5 项 | 账户隔离、连续修改合并与保存失败、v5 迁移、全部格式重置、重排不计作用户导航全部通过。 |
| 上述合计 | **36 项通过，0 失败**。`/tmp/readium390-reader-tests4.xcresult`、`/tmp/readium390-tests4.log`。 |
| 核心滚动/字体/切章复跑 | **连续两轮通过**，9.933s/9.690s。`/tmp/readium390-scroll-repeat.xcresult`、`/tmp/readium390-repeat.log`。 |
| 版本防回退 | 正常基线通过；六种变异（工程/锁回退、旧诊断版本、旧规范、非官方仓库、分支代替准确 revision）全部被拒绝。`python3 -m unittest discover -s apps/mobile/iosApp -p test_verify_readium.py`。 |
| Python 校验脚本 | Ruff format/check 通过。 |
| Web 国际化 | `pnpm i18n:check` 通过，2066 条 zh-CN/en-US 文案。无新增用户文案。 |

### 核心真机回归的实际范围

扩展既有 `testNativeTextControlsRenderBundledFontsAndThemesOnPhysicalDevice`，使用原始 TXT 中完整的三章（测试标题 44/45/46，**不是用户原书**），而不是在应用中拆章或添加排版检测。

- 设置在视图挂载前提交，实际渲染后检查字号；后续编辑从 SDK 公开 viewport 就绪开始。等待仅存在于测试，不加入应用链路。
- 检查字号 14/18/20/24/28/30、行距、内置字体加载、主题、系统明暗、恢复默认和真实保存失败。
- 连续设置修改保留同一 Navigator，偏好引起的重排不写入新进度或时间戳。
- 关闭重开后，切换滚动/分页/滚动及 22/16/24 字号；遍历 46→44→45，检查所有已加载/预加载 WKWebView 的正文末段、计算字号、CSS column-width 与原生 isPagingEnabled 一致。
- 断言原始文件和托管文件字节不变、没有转换/解包产物。

最初运行暴露并修正了测试的两处旧假设：动画关闭值应为目录中的 `off`，不是 `none`；完整 Locator 应按语义比较，不能要求旧序列化 JSON 的键顺序与新排序输出相同。初始 DOM 的 CSS 出现早于 SDK viewport 就绪，测试在下次用户编辑前等待公开 viewport；未增加固定延时或应用排版等待，未删除失败断言。早期失败/中断的 xcresult 留在本机，不作通过证据。

## 安装状态

- **Release 真机目标构建成功**：`/tmp/readium390-release2.log`，18:00 完成；明确使用已安装 JDK 17，自动开发签名，没有禁用签名。
- 首轮 Release 在环境排查时中断；完整日志随后确认 KMP 构建成功、耗时 1m17s，并非 Java 不可用或应用源码编译失败。重试复用构建缓存，不改依赖或项目签名。
- 产物：`/tmp/ermao-readium390-device-build/Build/Products/Release-iphoneos/ErmaoLibrary.app`；`codesign --verify --deep --strict` 通过，arm64 UUID `9DFA1C70-AB8A-3D0C-81C7-A3D349874B7C`，二进制包含 `readium-swift:3.9.0` 诊断标识。
- **18:00:42 覆盖安装成功，18:00:54 正常启动成功**：Bundle ID `com.ermao.library`，进程 `38043`；随后进程列表确认仍运行，安装路径与启动路径一致。没有卸载 App、清除账户、下载、偏好或阅读进度；没有测试启动参数。
- 安装/启动证据：`/tmp/readium390-install.json`、`/tmp/readium390-launch.json`、`/tmp/readium390-processes.json`。这是本地设备 Release 安装，不是 App Store/TestFlight 发布；进程启动核对不替代所有页面的交互验收。

## 受限和未验收项

- **漫画 SDK 弃用警告未关闭**：3.9.0 对 GCDHTTPServer 新增弃用声明，旧 CBZ Navigator 的唯一公开初始化仍需要它。去掉它需要迁移漫画 Navigator，超出本次批准范围；不能为消除警告改 SDK、使用私有接口或无声更换引擎。仍有旧 CBZ 弃用警告，图片解码无错误回调限制也未解决。这不是“零警告”交付。
- 其他既有 SwiftUI `onChange`、ViewBuilder、方向声明和 AppIntents 构建警告未因本次依赖升级扩展修改。
- 用户原书《惊悚乐园》第44–46章的升级后人工复核、旋转屏幕后重开，以及 EPUB/FB2/MOBI/PDF/漫画全部入口的完整交互验收，**尚未完成**。本轮有 TXT 实际滚动回归及多格式解析/安全测试，不能据此宣称所有格式全链路验收完成。
- 完整 `ReaderPersistenceTests` 旧测试 `testExactProgressRoundTripsWithoutCreatingDurableSyncState` 的历史表结构断言问题未纳入本轮修复；只执行上列五项重点测试，没有跳过/弱化该测试或宣称全套通过。
- Android/Web 引擎未升级，本轮未重跑其完整构建与交互回归。用户最初第45章字号不符的原现场未复现，详见 [升级前现场记录](ios-reader-scroll-confirmation-2026-08-28.md)。
