# Mobile 书库搜索与筛选控件 · 2026-08-28

## 范围与复用

- iOS / Android：阅读状态筛选入口迁入书库右上角三点菜单，移除结果数量旁的独立筛选按钮。保留结果区的活动条件与直接移除动作。
- iOS：保留与 `ShelfCatalogView` 相同的系统 `.searchable` 配置，书库名筛选改用系统分段 `Picker`，删除 `librarySourceButton` 自绘胶囊实现。动态书库名原样显示。
- 继续调用原有 `LibraryStore.selectLibrary/applyFilters/removeReadingFilter`、Android `LibraryScreen` 的 ViewModel 回调和既有 Filter Sheet；不增加筛选规则、网络适配器、状态存储或 API。
- Menu / Sheet 属于系统容器，搜索框与分段选择器属于原生控件，结果与活动条件继续使用 Warm Page 内容样式。Sheet 关闭后焦点目标从被删除的筛选按钮迁至三点按钮。
- 更新第七阶段规范的入口位置。未改书架页面、Reader、下载、后端或 Web 业务；保留工作区其他正在进行的修改。

## 回归覆盖

- 在现有 `ContentDiscoveryUITests` 中加入中英文真机流程：系统搜索框、原生书库分段选择、切换后的结果、仅菜单中存在筛选入口、取消不应用、应用与再次打开的选中态、清除以及关键词搜索。
- 扩展现有隔离内容 fixture，提供两个书库及对应查询/阅读状态响应；只在 fixture 客户端中使用，不写入真实账号。系统语言决定 fixture 会话语言，供中英文测试使用。
- 在现有 `AndroidShellSmokeTest` 中加入菜单→筛选 Sheet→取消/应用/清除流程，断言旧入口不存在、弹出 Sheet 时菜单已关闭，以及应用回调收到正确草稿。

## 已执行与阻塞

- `swiftc -frontend -parse`：本次修改的三个 Swift 文件语法检查通过。这不是编译、类型检查或运行时验收。
- Web `pnpm i18n:check`：2053 条中英文 catalog 校验通过；界面使用已有的双语原生资源，未新增文案。
- `git diff --check` 通过。
- iPhone 17 Pro Max 已连接、配对，Developer Mode 开启且无需解锁密码；自动签名 Team 已配置。未使用 Simulator。
- iOS `xcodebuild test` 已使用该物理设备执行，但在 KMP 构建阶段失败，未运行 XCTest/UI 测试、未安装本轮产物，也未取得本轮截图。失败来自本次范围外正在修改的 `OnlinePublicationSession.kt` 的 suspend `@Throws` 声明及 `ReaderLaunchCoordinator.kt` 的结果类型；未修改或绕过这些代码。
- Android 未连接物理设备，未执行安装、冷启动、仪器测试或截图，也未启动 AVD。构建中另发现范围外 `ReaderDownloadTransition.kt` / `ReaderScreen.kt` 的 Reader 字符串资源引用未解析。
- 共享 JVM 测试中 `LibraryDiscoveryRuntimeTest` 6 项全部通过；全量共 322 项，1 项 `OnlinePublicationSessionTest.resourceFailuresExposeStableNativeErrorCodes` 失败，不能宣称全量通过。Android 仪器 APK 合并还遇到现有 MOBI/Comic 语料中同名 `CORPUS.md` 的资源冲突。
- 本地诊断日志：`/tmp/ermao-library-controls-ios.log`、`/tmp/ermao-library-controls-android.log`；失败的 Xcode result bundle：`/tmp/ermao-library-controls-20260828.xcresult`。

结论：控件修改与回归测试已写入；完整构建、双语真机流程、VoiceOver/TalkBack、深色与大字视觉验收仍待构建阻塞解除及 Android 真机连接，不能将语法检查计为运行验收。

## 同日补充：用户要求安装 iOS 更新

- 用户明确要求在 iOS 真机安装更新。Reader/Downloads 的负责任务修复了本轮 KMP、可选长度、导出成员命名和异步锁的编译阻塞；本任务仅补充 `IosOnlinePublicationFactory` 对可选 `Locator` 的显式校验解包，无效项抛既有 `corruptFile`，不跳过定位项、不强制解包、不修改阅读流程。
- 指定物理 iPhone `00008150-0011112211A0C01C`、`iphoneos` 的自动签名 Debug 构建成功，`codesign --verify --deep --strict` 通过。日志：`/tmp/ermao-ios-install-20260828-final.log`。仍有现有 iPad 全屏/方向配置警告，未在安装任务中修改配置。
- 10:49（Asia/Shanghai）通过 `devicectl device install app` 保留数据更新成功；未卸载、未清数据。设备为 iPhone 17 Pro Max（设备名 `Xiaomi 17 Pro Max`），bundle 为 `com.ermao.library`，版本仍为开发版本 `1.0.0 (1)`。
- 使用 `--terminate-existing` 正常冷启动并明确关闭内容 fixture；启动成功后再次读取进程列表，确认同一安装路径的 App 进程 `37013` 正在运行。
- 安装、启动和版本证据分别保存在 `/tmp/ermao-library-install-device-20260828.json`、`/tmp/ermao-library-launch-device-20260828.json`、`/tmp/ermao-library-installed-version-20260828.json`。
- 本次完成的是签名构建、保留数据安装与冷启动检查。未执行新增 UI 测试、真实书库截图或 Reader 功能验收；前述 Android 与视觉待验项仍然保留。

## 同日补充：书库双语真机回归通过

- 后续封面菜单排查期间在同一物理 iPhone 执行新增书库 UI 测试：中文、英文两项均通过。覆盖系统搜索框、原生书库分段选择、菜单筛选、取消、应用、再次打开的选中状态、清除和关键词搜索。
- 结果：`/tmp/ermao-cover-locale-ui-20260828.xcresult`；书库中英文 root / overflow 截图位于 `/tmp/ermao-cover-locale-ui-attachments`。该 bundle 另有封面管理旧崩溃导致的失败，不能将整组称为通过；封面修复的独立通过记录见 `mobile-cover-menu-localization-2026-08-28.md`。
- 此记录补齐书库双语 UI 回归；不替代 Android 真机或尚未执行的深色、大字与无障碍检查。
