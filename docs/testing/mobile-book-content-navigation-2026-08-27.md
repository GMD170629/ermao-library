# Mobile 图书内容导航调整：实现与验收记录

日期：2026-08-27。状态：**代码已接入，完整运行时验收未完成，不能按发布验收通过处理。**

产品契约见 [Mobile 图书内容导航契约](../mobile-book-content-navigation.md)。

## 已接入

- Book 根节点和下级节点均由服务端目录／资源身份决定页面；目录不因零个、一个或多个资源改变页面类型。
- Android Navigation3 和 iOS NavigationStack 分别推进目录、资源详情；资源封面不启动 Reader。来源 Tab 保留，宽屏使用同一导航路径的详情区域。
- 根页限定 Book 管理／书架操作；阅读状态和下载使用当前 resourceId，目录批量下载从当前 sourceNodeId 子树开始。
- 页面状态按导航条目保存；排序、视图、目录／章节分页、简介展开、滚动位置保留。iOS 保存节点锚点及偏移；授权 namespace 隔离轻量导航恢复记录，恢复后重新读取服务端对象。
- 阅读主按钮恢复进度；章节 href、PDF 页码、漫画页码与资源 href 通过可选客户端目标进入现有 Reader。无效明确目标不会退化为无目标恢复。
- 音频详情与音轨保留，播放显示双语暂不支持提示。未实现播放器。
- 后端、Web、Reader v4 服务端协议、进度身份、出版物原始格式均未修改。

## 已运行的检查

| 检查 | 结果 |
| --- | --- |
| Shared Android host tests | 通过，含节点分类／加载／资源补齐及 Reader 目标测试 |
| Android debug 单测 | 132 项通过 |
| Android debug APK 构建 | 通过 |
| Android instrumentation 源码编译 | 通过；不代表仪器化运行通过 |
| verifyDesignTokens | 通过 |
| verifyMobileOfflineContract | 通过 |
| iosArm64 framework / iphoneos 签名构建 | 通过 |
| iOS ContentStoreTests + NavigationThemeTests | 已在物理 iPhone 上运行，27 项通过 |
| iOS 新增目录→资源→返回 UI 测试 | 未执行到测试步骤；运行器启动异常，退出码 74，单独串行重试亦失败 |
| git diff --check | 通过 |
| Android Lint | 未通过：现有 ExifInterface 使用与两个无引用文案，未关闭规则或新增 baseline |
| Web pnpm i18n:check | 未通过：现有管理员消息缺失／过期；本轮未修改 Web 或后端目录 |

主要命令（在 apps/mobile 运行 Gradle，Xcode 命令在仓库根目录运行）：

```sh
ANDROID_HOME=/Users/guyu/Library/Android/sdk ./gradlew :shared:testAndroidHostTest :androidApp:testDebugUnitTest :androidApp:assembleDebug :androidApp:compileDebugAndroidTestKotlin verifyDesignTokens verifyMobileOfflineContract
ANDROID_HOME=/Users/guyu/Library/Android/sdk ./gradlew :androidApp:lintDebug
ANDROID_HOME=/Users/guyu/Library/Android/sdk xcodebuild -project apps/mobile/iosApp/ErmaoLibrary.xcodeproj -scheme ErmaoLibrary -configuration Debug -destination 'platform=iOS,id=00008150-0011112211A0C01C' build
```

本地执行日志：`/tmp/ermao-book-navigation-gates-final.log`、`/tmp/ermao-book-navigation-android-lint.log`、`/tmp/ermao-book-navigation-ios-build-final.log`、`/tmp/ermao-book-navigation-ios-units-final.log`、`/tmp/ermao-book-navigation-ios-ui.log`。这些是当前主机执行记录，不是仓库可移植测试产物。

## 设备与未完成门禁

- Android：`adb devices -l` 无物理设备。未安装 APK、未执行仪器化或模拟器替代验收。
- iOS：物理 iPhone 17 Pro Max（设备显示名称为 Xiaomi 17 Pro Max），iOS 26.6，已配对、Developer Mode 已启用、未要求密码解锁。已验证 com.ermao.library 1.0.0 (1) 安装及普通冷启动。
- 已补充下方 iOS 真机静态截图；完整 UI 交互验收仍未完成。
- 多层导航及 Reader 往返、真实章节／页面定位、数据重排后的锚点恢复、快速点击、旋转／分屏、进程重建、权限变化、慢网／失败、真实下载子树、大字体、读屏、Reduced Motion、双语与深浅色仍需完成物理设备交互验收。
- iOS 现有 Readium CBZ 过时接口和其他既有构建警告仍存在；本轮未进行跨 Reader 引擎迁移或无关清理。

只有物理设备交互证据、相关回归和阻塞门禁补齐后，才能将本记录升级为完整验收通过。

## iOS 真机截图补充（13:29–13:31）

通过 Xcode Devices 的 Take Screenshot 从上述物理 iPhone 直接保存，原始尺寸 1320 × 2868，未修图。使用已安装的 App、现有登录会话和真实服务端内容，通过既有 DEBUG 入口打开目标 Book／Resource；未启用 UI fixture。截图只证明对应时刻的页面展示，不替代点击推进、返回恢复或 Reader 验收。

| 页面 | 原始截图 | 观察 |
| --- | --- | --- |
| EPUB 资源详情：《祈祷落幕时》 | [截图](screenshots/ios-book-content-2026-08-27/01-epub-resource-detail.png) | 显示真实封面、3% 进度、继续阅读及资源资料 |
| 根目录：《星港巡夜人》 | [截图](screenshots/ios-book-content-2026-08-27/02-root-directory.png) | 显示四个下级封面节点及浏览控制；**仍显示 50% 阅读进度，与目录不显示阅读进度的契约冲突**；当前画面封面为占位状态 |
| PDF 资源详情：《矛盾论 (毛泽东)》 | [截图](screenshots/ios-book-content-2026-08-27/03-pdf-resource-detail.png) | 显示 PDF 格式、43 页、4% 进度；当前画面封面为占位状态 |
| 显式漫画资源入口：《01 启航》 | [截图](screenshots/ios-book-content-2026-08-27/04-comic-resource-loading.png) | 13:31:11、13:31:33 两次采集均停留在加载画面，尚未获得内容详情截图；需排查，不能算成功 |

iPhone Mirroring 持续提示“iPhone 使用中，锁定 iPhone 以连接”，因此本次未获得可交互镜像，尚未采集下级目录、章节／页面列表及音频详情。没有为完成截图而改动产品代码、服务端数据或阅读进度。

## iOS 真机镜像截图补充（13:37–13:43）

用户连接 iPhone Mirroring 后，直接操作同一物理 iPhone 上的 App。镜像接管期间 Xcode Take Screenshot 得到的是锁屏，因此本组保存的是 **iPhone Mirroring 窗口原始截图（354 × 781）**，不是上述 1320 × 2868 原生截图；未裁切、修图或使用模拟器。放大窗口导致桌面边缘裁切的中间图片已重新采集为完整窗口，以下图片均可见四项底部导航。

| 页面 | 截图 |
| --- | --- |
| 根目录《星港巡夜人》，真实封面加载完成 | [截图](screenshots/ios-book-content-2026-08-27/09-root-directory-loaded-mirror.png) |
| 下级目录《单行本》，包含目录和资源 | [截图](screenshots/ios-book-content-2026-08-27/05-directory-single-volumes-mirror.png) |
| 下级目录《番外篇》，只有一个资源，未跳过目录 | [截图](screenshots/ios-book-content-2026-08-27/06-directory-one-resource-mirror.png) |
| ZIP 漫画资源详情《03 无线电幽灵》 | [截图](screenshots/ios-book-content-2026-08-27/07-comic-resource-detail-mirror.png) |
| 该漫画的五页真实预览及页码 | [截图](screenshots/ios-book-content-2026-08-27/08-comic-page-previews-mirror.png) |
| IMAGE_DIR 目录型可读资源《02》的资源详情 | [截图](screenshots/ios-book-content-2026-08-27/10-image-directory-resource-detail-mirror.png) |
| EPUB《祈祷落幕时》的章节列表与章节状态 | [截图](screenshots/ios-book-content-2026-08-27/11-epub-chapters-mirror.png) |

实际操作路径：根目录 → 单行本 → 番外篇 → ZIP 资源详情 → 滚动查看五页预览 → 返回番外篇 → 点击祖先面包屑返回根目录；另从根目录封面进入 IMAGE_DIR 资源详情。点击目录／资源封面均发生了页面推进，未自动启动 Reader。只有一个资源的番外篇仍保留独立目录页。资源详情不显示根页书架操作；目录及资源详情保留底部四项导航。

观察与边界：

- 目录仍显示 50% 阅读进度，与既定契约冲突，未在本截图任务中修复。
- ZIP 资源详情同时显示 50% 进度与“未开始／开始阅读”，需进一步核对资源进度归属；本次只记录画面，未修改进度。
- 之前占位的目录封面本次加载后已显示，不能据此前瞬时占位判定真实封面缺失。
- 本次 ZIP 与 IMAGE_DIR 的封面入口成功，不证明此前指定 CBZ resourceId 启动持续加载的问题已解决。
- 没有点击章节或页面进入 Reader，没有执行下载、阅读状态、书架或管理写操作。音频详情及完整返回状态恢复矩阵仍未覆盖；截图不等于完整验收通过。

## 目录首屏精简修订（13:56–14:00）

按用户对《番外篇》真机截图的反馈，Android / iOS 目录页移除整个身份头部、简介、进度和独立快捷动作行，进入后直接显示浏览控制、面包屑和下级封面。根目录和下级目录遵循同一模板，资源数量不影响布局。资源详情的身份、阅读主按钮、元数据和预览布局未改动。

- 目录下载移入导航栏原生“更多”菜单，仍调用现有当前目录子树的下载选择流程。
- 仅根目录菜单追加书架和按现有权限过滤的 Book 管理操作；子目录菜单不重复图书管理。
- 保留系统标题、返回、四项底部导航、六种排序、网格／列表、分页与页面独立恢复状态。
- 本次仅调整 Mobile 呈现和相关测试／规范，没有修改后端、Web、节点分类或进度数据。

### 当前修订检查

| 检查 | 结果 |
| --- | --- |
| Android debug 单测 / APK | 132 项通过（0 失败、0 跳过）；APK 构建通过 |
| 新增 Android 目录呈现 UI 测试 | 覆盖 0 / 1 / 3 资源 × 根／下级目录，包含菜单权限与点击意图；源码编译通过，物理设备未连接，未运行仪器化 |
| verifyDesignTokens / verifyMobileOfflineContract | 通过 |
| iphoneos 签名构建与保留数据安装 | 通过，在原物理 iPhone 上冷启动并完成以下手工复核 |
| iOS ContentStoreTests / NavigationThemeTests | 本次重新在物理 iPhone 运行，27 项通过 |
| iOS 新目录 UI 测试 | 已编译；运行器初始化失败：`com.apple.sharing.authentication error 12`，认证响应超时，未进入断言步骤；xcodebuild 退出 65，不记为通过 |
| 双语文案 | 复用已有 zh-Hans / en 与 Android 双语菜单文案；列表／网格切换无障碍标签已核对 |
| Android Lint | 仍为既有 4 项错误：2 处旧 ExifInterface、2 个未使用资源；没有添加排除或降低规则 |
| Web pnpm i18n:check | 仍为既有管理员文案缺失／过期；未修改 Web 文案 |
| git diff --check | 通过 |

iOS 结果包：`/tmp/ermao-directory-browser-only-20260827.xcresult`；执行日志：`/tmp/ermao-directory-browser-only-20260827-tests.log`。结果包为当前主机诊断产物，不对外上传；总体结果仍为 Failed（27 个单测通过、1 个 UI 运行器初始化错误）。

### 新版真机镜像证据

以下均为真实服务端内容、原登录会话、更新安装后的 iPhone Mirroring 窗口原始截图（354 × 781），没有使用 UI fixture、模拟器或图像加工。保留 01–11 的旧截图，便于与用户标注的 06 对照。

| 页面／操作 | 截图 |
| --- | --- |
| 根目录直接展示四个下级节点 | [新版根目录](screenshots/ios-book-content-2026-08-27/12-root-browser-only-mirror.png) |
| 根目录菜单：下载、书架、现有授权管理项 | [根目录菜单](screenshots/ios-book-content-2026-08-27/13-root-directory-menu-mirror.png) |
| 《单行本》直接展示目录和资源 | [下级目录](screenshots/ios-book-content-2026-08-27/14-child-directory-browser-only-mirror.png) |
| 《番外篇》只有一个资源，进入无需滚动 | [对应用户示例的新首屏](screenshots/ios-book-content-2026-08-27/15-one-resource-directory-browser-only-mirror.png) |
| 子目录菜单只有当前目录下载 | [子目录菜单](screenshots/ios-book-content-2026-08-27/16-child-directory-menu-mirror.png) |
| 下载选择页仅列出当前番外篇的 ZIP，随后取消 | [下载子树范围](screenshots/ios-book-content-2026-08-27/17-child-directory-download-scope-mirror.png) |
| 点击 ZIP 仍推进独立资源详情，未自动启动 Reader | [资源详情保持](screenshots/ios-book-content-2026-08-27/18-resource-detail-preserved-mirror.png) |
| 六种排序菜单保留 | [排序](screenshots/ios-book-content-2026-08-27/19-directory-sort-options-mirror.png) |
| 切换列表 → 资源详情 → 返回，仍保持列表 | [返回后列表状态](screenshots/ios-book-content-2026-08-27/20-directory-list-restored-mirror.png) |

本次明确验证了根目录 → 单行本 → 番外篇 → 资源详情 → 返回、目录菜单呈现、下载选择范围、列表／网格切换和列表返回恢复。没有执行下载、书架／管理修改或阅读状态写入，没有启动 Reader。

此前截图中的目录 50% 进度问题已随目录头部移除而消失。ZIP **资源详情**的 50% 与“未开始”不一致仍属待核查问题，并未通过本次布局修改解决。长列表滚动／分页、权限变化、大字体／读屏、深浅色、横屏／分屏及完整 Reader 路径仍需原计划的物理设备验收，本组截图不替代这些门禁。

## 后续修订：只恢复点击图书进入的根页

按用户再次明确的最小范围要求，Android / iOS 仅在现有根入口且绑定目录时恢复原有图书封面、图书信息、下载／加入书架／更多快捷操作与图书简介，下方继续原有内容浏览区。根页不恢复混合阅读进度或阅读主按钮，导航栏不重复快捷菜单。

下级目录保持精简布局；直接绑定资源的图书及下级资源详情保持原样；Reader、页面目的地、导航栈、资源解析、后端和 Web 均未修改。本轮生产代码只调整两端 WorkDetail 的根页布局分支及根页呈现资料，复用既有 Warm Page 组件与操作回调。

检查结果：

- Android debug APK、132 项单测、UI 测试源码编译通过；增加根页图书身份／简介／无混合进度与下级目录／资源呈现不变的断言。0／1／3 资源的根页与下级目录 UI 测试已更新，未在物理 Android 上运行。
- `verifyDesignTokens`、`verifyMobileOfflineContract`、`git diff --check` 通过；本轮复用已有双语文案，没有新建文案键。
- Android Lint 仍有原有 4 项错误，Web 国际化检查仍有原有管理员消息缺失／过期；没有降低检查规则。Lint 日志：`/tmp/ermao-book-root-restore-lint-20260827.log`。
- iOS 两个修改后的 Swift 文件通过语法解析检查，此结果不等于类型检查、iphoneos 构建或运行验收。
- 14:19 的指定物理设备构建未进入编译：Xcode 找不到 `00008150-0011112211A0C01C`，退出码 70。再次检查 `devicectl list devices` 显示该 iPhone 为 `unavailable`，`xcodebuild -showdestinations` 没有可用物理设备；iPhone Mirroring 显示“iPhone 使用中，锁定 iPhone 以连接”。
- **本次根页恢复版本尚未安装到 iPhone，也没有新真机截图或新的 iOS 单测／UI 测试结果。** 上述 01–20 截图及 27 项 iOS 单测属于此前版本，不能用来证明本次根页恢复的效果。等待物理 iPhone 重新连接后进行签名构建、保留数据安装和截图复核，没有使用模拟器替代。

## 根页恢复版本重新连接后安装（14:28–14:31）

用户反馈点击《星港巡夜人》仍无顶部信息后，确认 iPhone 已重新连接。此前最新本地可执行文件时间为 13:59:39，根页恢复代码更新时间为 14:18:23；上一次指定设备构建因设备不可用失败，没有形成可安装的新包。

- 重新核对物理设备 ID、配对、Developer Mode、解锁状态及签名 Team，完成 `iphoneos` 签名构建，14:29:05 输出新可执行文件，构建结果为 `BUILD SUCCEEDED`。
- 14:29:33 开始保留数据安装 `com.ermao.library`，安装成功；14:30:10 正常冷启动，不使用 UI fixture 或指定 Book 的 DEBUG 启动参数。启动进程路径对应本次新安装包。
- 14:30:22 在已恢复的书库根页看到《星港巡夜人》封面、书名、下载／加入／更多快捷操作，下方仍为四个真实内容节点；根页没有混合阅读进度。
- 新证据：[恢复后的图书根页](screenshots/ios-book-content-2026-08-27/21-book-root-header-restored-mirror.jpeg)。这是当时 iPhone Mirroring 输出的原始 JPEG（354 × 781），未修图，未使用旧截图冒充新版本。
- 此次未再修改生产代码，只构建安装上一次根页恢复改动并更新验收记录。下级目录、资源详情及导航实现没有额外改动。
- 随后手机被直接操作，镜像再次中断，未完成从书库重新点击及下级目录往返的新一轮镜像操作；本次没有新增 iOS 单测／UI 自动化运行结果。原有 Readium 过时接口等构建警告和其他尚未通过的门禁继续保留，不将这张根页截图视为完整运行时验收。

当前构建日志：`/tmp/ermao-book-root-restore-ios-build-20260827.log`。本节取代上一节“尚未安装到 iPhone”的即时状态，保留上一节作为断连时的历史记录。

## 图书根页恢复卷册阅读区（14:38–14:45）

按最新反馈，仅图书入口根页新增当前卷册阅读区，保持精简下级目录和直接绑定资源详情不变。名称和进度取自同一 `continueResourceId` 对应资源，零进度只显示开始阅读／收听；缺失、隐藏或不可读目标不替换为列表中另一资源。Reader 仍以明确资源启动，原始格式和 v4 协议未改；音频按钮有暂不支持说明和既有反馈。

本轮检查：

- 共享 260 项测试、Android 132 项单测均通过，无跳过；debug APK、仪器化源码编译、设计令牌和离线契约检查通过。ADB 未发现物理设备，未安装或执行 Android 仪器化验收。
- `iosArm64` / `iphoneos` 真机签名 `build-for-testing` 通过；在物理设备 `00008150-0011112211A0C01C` 上执行内容／导航 28 项单测，0 失败。新增覆盖根页继续目标与目录选择隔离、阅读后刷新不丢失本地目标；现有进度乱序测试新增目标稳定性断言。
- 物理设备 UI 测试运行器再次因 `com.apple.sharing.authentication error 12` 认证响应超时初始化失败，未执行断言，不能记为通过。
- 14:42:16 保留数据安装、14:42:19 冷启动 `com.ermao.library`，版本 1.0.0（1）；实机沿用当前登录服务器，非 UI fixture。
- 《星港巡夜人》根页初始显示开始阅读；点击进入真实资源标题“02”的漫画 Reader。返回后根页显示“正在阅读 · 02”、进度条和继续阅读，再次继续仍打开“02”、恢复到 2/2。下级“单行本”仍为精简目录，返回保留根页阅读区。测试期间切到 Reader 1/2，显示百分比降至 0 时根页恢复开始按钮，未以最大历史百分比维持错误进度。
- **Reader 内容渲染未通过**：该 IMAGE_DIR 卷册在镜像中呈黑色画面，控制栏和页码可显示、切页；仅证明阅读入口目标与返回进度生效，不能据此声称图片正常渲染。本轮未更改 Reader 引擎。
- **2026-09-01 后续复核**：上述现场资源的两张 PAGE 实际为 1×1 黑色 PNG，因此黑色画面不是可归因于 Reader 的生产缺陷。后续使用两张不同颜色的 320×480 PNG，在实体 iPhone 上分别通过 OriginalPageSet 原字节/像素、远程 Publication Resource 到 `UIImage`、以及真实 `CBZNavigatorViewController` 首页与下一页像素渲染和翻页验证；生产 Reader 未修改。结果包：`apps/mobile/iosApp/build/Logs/Test/Test-ErmaoLibrary-2026.09.01_11-46-06-+0800.xcresult`。
- 切页检查后已恢复本轮进入 Reader 时的 2/2 页，并返回图书详情。测试产生了正常的资源进度保存，没有清空图书、下载或登录数据。
- Android Lint 仍有 4 个既有错误（两处 ExifInterface、两项未使用字符串）；Web `pnpm i18n:check` 仍有管理员文案 4 个缺失／6 个过期。新阅读区文案已同时提供英文和中文，iOS 新占位符匹配；未降低门禁。iOS 既有 Readium/SwiftUI 过时接口警告及滚动锚点重复帧更新警告保留记录。

新原始 iPhone Mirroring JPEG 证据，未修图：

- [无进度：开始阅读](screenshots/ios-book-content-2026-08-27/22-book-root-start-reading-mirror.jpeg)
- [有进度：卷册名称、进度条和继续阅读](screenshots/ios-book-content-2026-08-27/23-book-root-continue-reading-mirror.jpeg)
- [下级目录保持精简](screenshots/ios-book-content-2026-08-27/24-child-directory-unchanged-mirror.jpeg)
- [Reader 恢复目标，但内容呈黑屏](screenshots/ios-book-content-2026-08-27/25-reader-resume-black-content-mirror.jpeg)

日志：`/tmp/ermao-book-reading-android-20260827.log`、`/tmp/ermao-book-reading-ios-20260827.log`、`/tmp/ermao-book-reading-ios-unit-20260827.log`、`/tmp/ermao-book-reading-ios-ui-20260827.log`。结果包：`/tmp/ermao-book-reading-unit-20260827.xcresult`、`/tmp/ermao-book-reading-ui-20260827.xcresult`。此节为当前阅读区版本证据，不代表所有跨平台／无障碍／Reader 真机门禁已完成。

## 统一操作栏与页面对象归属（15:00 后）

用户明确：操作栏作用于当前页面对象，而不是续读资源。图书页的下载／阅读状态／加入／更多全部作用于图书；卷册页作用于该卷册。只有图书主阅读按钮解析上次阅读到的资源和位置。

- Android 和 iOS 分别删除根页独立三按钮行与独立主按钮实现，图书和卷册详情共用同一原生操作栏；下级目录只保留当前子树下载菜单，删除不可达的目录 Book 操作分支。
- 新共享规则明确区分 `objectKind + objectId` 和 `readingResourceId`。图书绑定单资源时仍是 Book 操作对象；切换续读卷册不会切换图书操作身份。
- 图书下载按钮显示整书本地下载任务状态，点击原有整书资源树管理；已验证副本显示已下载资源数量，不暗示整个图书全部下载。卷册继续使用独立下载暂停／重试／管理。
- 图书状态使用既有 `/api/library/operations/books/reading-status`，卷册使用既有资源状态接口；失败不乐观地假装成功，成功后清理相应范围的旧进度投影并非阻塞刷新。
- 265 项共享测试、133 项 Android 单测通过，无跳过；APK、仪器化源码、设计令牌和离线契约检查通过。新增对象归属、整书下载统计隔离、四按钮及缓存失效断言。
- 指定物理 iPhone 的 `iosArm64`／`iphoneos` 签名测试构建通过，包含更新后的 Swift 单测和 UI 测试源码。
- 15:03 开始的真机单测尚未进入断言：Xcode 报设备密码锁定，`deviceprep Code=-3`，等待解锁。15:05 再核对仍为 `passcodeRequired: true`，镜像未恢复。**本版本没有新的真机测试通过结果、安装／冷启动证明或截图；上一节截图不能代表本次四按钮版本。**
- Android 未连接物理设备；Lint 仍为原有 4 个错误，Web 国际化检查仍为原有管理员 4 个缺失／6 个过期。新增文案中英文及占位符已检查，未放宽规则。此前 Reader 黑屏未在本轮处理。

构建与检查日志：`/tmp/ermao-unified-actions-android-final-20260827.log`、`/tmp/ermao-unified-actions-ios-build-final-20260827.log`、`/tmp/ermao-unified-actions-i18n-20260827.log`。真机待解锁记录：`/tmp/ermao-unified-actions-unit-20260827.log`。

已中止本次等待解锁的 XCTest 进程，避免后台无限等待；解锁后需重新运行，不计为通过。

## 解锁后统一操作栏版本真机复核（15:09–15:12）

用户解锁后，重新确认物理 iPhone `00008150-0011112211A0C01C` 已连接、配对、Developer Mode 启用，`passcodeRequired: false`，且 Xcode 列出了该物理目的地。

- 使用最新签名测试构建执行 `ContentStoreTests` 和 `NavigationThemeTests`：28 项真机单测通过，0 失败。日志 `/tmp/ermao-unified-actions-unit-unlocked-20260827.log`，结果包 `/tmp/ermao-unified-actions-unit-unlocked-20260827.xcresult`。
- 再次执行目录／资源推进返回 UI 测试，但运行器在启用自动化模式时超时，未执行页面断言；退出码 65，不能记为通过。日志 `/tmp/ermao-unified-actions-ui-unlocked-20260827.log`，结果包 `/tmp/ermao-unified-actions-ui-unlocked-20260827.xcresult`。
- 15:11:17 开始保留数据安装最新 `ErmaoLibrary.app`（可执行文件时间 15:03:16，签名 Team `W5G54L42KQ`）；15:11:31 冷启动 `com.ermao.library`，版本 1.0.0（1），进程 PID 35131 的包路径对应此次安装。未卸载、清空数据或使用 fixture／指定图书启动参数。
- Xcode Devices 的物理设备截图已确认《星港巡夜人》根页出现四项操作：**已下载 3 项／正在阅读／加入／更多**，上方保留主阅读按钮，下方保留真实内容浏览区。此截图只证明按钮呈现，不能单独证明每个写操作的目标或执行成功。
- [最新图书根页四按钮](screenshots/ios-book-content-2026-08-27/26-book-root-unified-actions-device.png)：15:11:56 获取的原始 1320 × 2868 iPhone PNG，未裁切或修图，不是旧版本镜像截图。
- 此时镜像提示“iPhone 使用中，锁定 iPhone 以连接”，已请求用户锁屏以便继续操作。当前未完成本版本整书下载弹层、卷册操作和下级目录往返的手动复核；没有改动真实阅读状态，也没有发起下载。

本节取代上节“本版本尚未安装／没有新截图”的即时状态，保留原先锁定失败的历史记录。UI 自动化、Android 真机、既有 Lint／国际化错误及 Reader 黑屏等未通过项目仍不计为完成。

### 镜像恢复后补充检查（15:13–15:18）

- 镜像恢复后，点击图书下载状态打开“下载卷册”整书树，看到单行本、彩色重制版、`02`、`01 启航`；展开单行本还显示番外篇和 `02 雾港来客`。范围不是主阅读按钮指向的一个资源。未选择或发起下载，取消后返回同一图书页。
- [整书下载树](screenshots/ios-book-content-2026-08-27/27-book-downloads-whole-book-mirror.jpeg)为本版本原始镜像截图。
- 检查阅读状态入口时，误以为会打开选择框，实际按钮直接将整书标记已读。立即向用户说明后，用户明确“无需恢复数据，测试数据可以随意变更”，因此保留测试结果，没有通过标记未读清空进度，也没有执行数据库恢复写入。
- 随后的只读 ORM 核对确认：`op_1787814827886182000` 为本书 `BULK_READING_STATUS / FINISHED` 操作，时间 `2026-08-27 07:13:47.881 UTC`；快照包含操作前 3 条进度（50%、0%、50%），操作后本书 5 个资源均为 100%。这证明图书状态作用于整书，而非续读卷册。此核对仅执行只读查询，没有改动后端代码、接口或数据结构。
- [图书已读后的统一操作栏与继续阅读区](screenshots/ios-book-content-2026-08-27/28-book-root-unified-actions-continue-mirror.jpeg)显示“正在阅读 · 01 启航”、进度条、继续阅读及四项操作。该进度来自上述测试状态修改，不是实际完成阅读的证据。
- 此后镜像截图仍可读取，但所有坐标点击持续报 `Computer Use server error -10005: noWindowsAvailable`。置前、重新连接和窗口位置／大小调整均未恢复点击；没有将失败点击记为实际打开书架或更多菜单。
- **当前版本的书架／更多菜单、卷册状态隔离、下级目录推进返回手动复核仍待完成**；此前旧版本截图不能替代。UI 自动化运行器初始化失败也仍未解决。本轮没有进入 Reader 或发起下载。
