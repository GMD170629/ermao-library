# iOS 滚动模式翻章定位 — 2026-08-28

## 原因与行为

原应用将“上一页”直接交给 Readium `goBackward`。实际锁定的官方 Readium Swift 3.9.0 在滚动模式跨阅读资源后定位 `.end`，因此进入上一章末尾是引擎默认导航语义，不是正文损坏。依据为 SDK `EPUBNavigatorViewController.go(to:options:)` 与 `EPUBReflowableSpreadView.go(to:options:)` 的真实调用路径。

本次仅调整 iOS 可重排文字阅读的应用翻页入口：滚动模式“上一页”进入上一原始阅读资源顶部，“下一页”进入下一资源顶部；第一页/最后一页不循环。资源以 Publication 的 reading order 为准，不通过目录标题重新切章。分页模式仍执行 SDK 普通前后翻页。

## 复用与删除

- `IosReflowableReaderSession` 是应用导航所有者；工具栏、点击区域和键盘均进入同一个 `turnPage`，左右方向沿用公开 `presentation.readingProgression` 的 LTR/RTL 映射。
- 复用既有 `IosReaderNavigationQueue` 和目录跳转流程。原 `executeTOCNavigation` 收敛为唯一 `executeLinkNavigation`，目录与相邻章节共用，没有保留另一套跳转实现。
- 直接向公开 `navigator.go(to: Link)` 提交不带 fragment 的原始资源链接，由 SDK 定位资源起点。没有先跳章末再补滚动，也没有新增 JavaScript 定位、排版验证、设置 loading、Navigator 重建、下载或偏好字段。
- 使用正常用户导航的可见锚点持久化；设置重排仍不算用户翻页。原始图书和托管文件保持原字节。
- 官方 SDK revision 仍为 `de07026e9f825a5791f27a7ac4cd6bb1a784ab8d`，SDK 工作区无修改。

## 真机验证

设备为已配对、解锁可用的 iPhone 17 Pro Max，iOS 26.6；使用真实设备 destination 与正常开发签名。

扩展既有 `ReaderSecurityTests.testNativeTextControlsRenderBundledFontsAndThemesOnPhysicalDevice`，使用原始 TXT 三章夹具（44/45/46，非用户原书），没有新增替代阅读器或应用等待逻辑。

- **修改前失败**：新增返回章首断言在旧应用路径失败，证据 `/tmp/reader-scroll-top-before.xcresult`。
- **修改后 23 项通过，0 失败**：ReaderSecurityTests 17 项、ReaderProgressContractTests 6 项；`/tmp/reader-scroll-top-after4.xcresult`、`/tmp/reader-scroll-top-after4.log`。
- **核心真机回归连续两轮通过**：17.671s / 17.810s；`/tmp/reader-scroll-top-repeat.xcresult`、`/tmp/reader-scroll-top-repeat.log`。
- 新增覆盖：前后翻章顶部、首尾边界、并发连续上一章、键盘 delegate、正常/反向点击区域、真实章首锚点保存、同一 Navigator、切回分页后同章内下一页/上一页。
- 原有字号、字体、主题、模式切换、关闭重开、设置不写阅读进度、原文件不变、无转换产物的断言保留。
- 输入回调异步执行，测试等待公开 location 通知及可见 DOM 后断言；等待只在测试中，不加入应用设置链路。
- `verify_readium.py`、`git diff --check`、Web `pnpm i18n:check` 通过（2066 条文案，本次无新增用户文案）。

## 正常版本安装

- Release 真机目标构建成功，`/tmp/reader-scroll-top-release.log`；`codesign --verify --deep --strict` 通过，arm64 UUID 为 `5A7B4E25-7C99-3E19-979B-081FF85E33FF`。
- 18:25 覆盖安装 `com.ermao.library` 成功，正常启动成功，随后查询确认进程 `38258` 仍运行且安装/启动路径一致；没有测试启动参数、卸载 App 或清除用户数据。
- 安装、启动、进程证据：`/tmp/reader-scroll-top-install.json`、`/tmp/reader-scroll-top-launch.json`、`/tmp/reader-scroll-top-processes.json`。仅为连接设备的本地 Release 安装，不是 App Store/TestFlight 发布。

## 边界与独立待查项

- 本次实际渲染验收为本地 TXT；EPUB/FB2/MOBI 和在线入口共用同一文字会话，但没有逐格式、逐入口重新验收。Android/Web 未修改，PDF/漫画不在此文字翻章规则内。
- SDK 自己处理的 VoiceOver 滚动未修改；RTL 原始图书、外接实体键盘及用户原书尚未人工验收。键盘和点击区域证据是设备内调用应用入口，不冒充硬件输入或端到端 UI 点击。
- 扩展测试时另行观察到：完成连续翻章并由滚动切到分页后，调用 `seekControlProgress(0.5)` 返回 false，未得到预期百分比位置。**根因未确认，本次未修复**，不能据此归因于图书或 SDK。保留现场 `/tmp/reader-scroll-top-after3.xcresult`。原有较早阶段 `seekControlProgress(0.45)` 测试继续保留并通过；新增普通分页回归改用 SDK 下一页建立同章测试位置，再验证上一页，没有宣称百分比跳转已通过。
- 构建仍有前次升级记录中的既有 SDK/SwiftUI 等警告；未降低检查或修改 SDK 消除警告，不宣称零警告。
