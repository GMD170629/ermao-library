# 阅读设置统一：实现与验收记录 — 2026-08-28

> **版本后续更新**：本页保留升级前的历史证据。用户随后批准 iOS Readium 3.9.0；当前版本、防回退规则与验收见 [3.9.0 升级记录](ios-readium-3.9.0-2026-08-28.md)。旧版“SDK 不变”描述不再构成回退依据。

## 范围与结论

本轮落实用户确认的设置目录、偏好存储 v5、出版方总开关和原生直接提交规则。设置值继续保存在当前设备、服务器和账户的本地命名空间；没有增加设置同步接口。Reader v4 进度协议、原文件、下载、书签及 SDK 固定版本不变。

**代码迁移已实施，但不代表三端所有格式均已通过交互验收。** Web 自动检查通过；iOS EPUB 与漫画有本轮真机证据；PDF 在打开阶段失败，Android 未连接真机。具体限制及未通过检查见下文。此次 Xcode 测试安装的是签名 Debug 测试构建，不是新的 Release 发布记录。

## 权威实现、复用和删除

| 能力 | 权威所有者与迁移入口 |
| --- | --- |
| 设置目录 | `packages/reader-contracts/reader-settings.json`：稳定标识、面板、区块和顺序、阅读形态、中英文名称、选项、范围。生成 Web 元数据、KMP 类型化读取/修改和 iOS 原生词条。 |
| 目录消费 | Web `ReaderPreferencesPanel`、Android `ReaderPreferenceSheet`、iOS `ReaderPreferenceSheet` 均迭代目录；平台只保留控件和 SDK 映射。生成检查同时检查 iOS 字段映射覆盖。 |
| Web 偏好 | 复用 reader-core 偏好规则及现有设备偏好存储。`migrateWebReaderPreferences` 是唯一 Web 旧记录转换；设备存储和原有 IndexedDB 读取均调用它。 |
| Mobile 偏好 | 复用 KMP `ReaderPreferences`、`ReaderPreferenceChanges`、`ReaderPreferencesJson`。Android 存储与 iOS 公开桥接消费同一旧格式解码。iOS 不再持久化重复 `iosDraft`。 |
| 原生设置提交 | Android `ReaderScreenController` → 现有格式 session；iOS `IosReaderPreferenceEditor` → 现有格式 session。保存成功后只向已存在的 Navigator 提交必要偏好。连续修改仍由原编辑器合并。 |
| 恢复默认 | 共享全格式默认值替换当前命名空间偏好；三个格式入口均重置全部阅读格式，不再按当前格式局部重置。 |
| 字体 | 保留已有授权字体资源及 native 映射。同名不承诺跨平台字形或排版逐像素一致。 |

已删除：Web 三个出版方独立控件及其主题/字体/行高应用分支；运行时中的 `allowPublisherColors`、`allowPublisherFonts`；原生独有手势动画设置；各端重复设置清单和失去调用者的辅助代码/词条。两个旧字段只出现在集中旧存储迁移和迁移输入测试中。

Android 设置路径已删除排版事件等待、超时推测、首段捕获/比较、主动定位恢复、渲染回滚、专用计数器/忙碌标记和导航阻塞；不再通过第二次提交恢复渲染。正常打开、目录/书签定位和进度恢复保留。设置引起的重排事件继续由原持久化门控排除，不当作翻页上传。

无设置加载行、面板转圈、设置触发的 Navigator 重建、重新打开或下载。提交成功只代表已保存并向 SDK 提交，不代表排版已完成。Android 保存/引擎错误保留内部 cause，使用不同稳定错误码；没有制造 SDK 未提供的失败或完成回调。

## 兼容与能力边界

- 偏好版本 5 与进度版本 4 独立。Web 旧行高开关迁移为关闭；原生旧总开关保留。转换成功才写新结构；读取失败不覆盖原记录。
- 合法非预设值保留并展示当前值，包括连续行距/字间距。打开面板不吸附到最近选项。iOS 对浮点尾数的格式化只改变显示，不改保存值。
- 三端的“出版方样式 / Publisher Styles”位于“高级设置 → 段落与内容样式”。iOS/Android 使用 SDK `publisherStyles`；有效性依赖其公开 preference editor。Web 固定引擎没有总开关接口，显示关闭且禁用，明确说明原因；常规字体、主题和排版照常应用，不用 CSS 或多参数模拟总开关。
- 原生不能直接表达的负字间距、智能优化、漫画布局/适配/画质等路径保留原目录位置并说明限制。SDK 固定开启的滑动翻页显示实际开启，并说明无法关闭；不把已保存但无法生效的开关展示为已实现。
- iOS 漫画程序翻页动画接入现有公开 `go(..., options:)`；不更改 SDK 手势动画。
- iOS PDF 缩放通过已有公开 PDFView/UIScrollView 接口应用并在页面变化时使用保存值。**本轮只有编译证据，没有 PDF 缩放交互验收。**
- iOS PDF `fit` 虽然是公开参数，但固定 SDK 的 `PDFDocumentView.scaleFactor(for:)` 明确在分页模式忽略 width，使用整页适配。因此该路径继续禁用并说明原因，没有改阅读方式或增加自写适配。
- iOS 漫画 SDK 吞掉图片解码错误的既有分支不在本轮修补，没有添加预解码、超时猜测或日志推断。

## 自动检查

| 检查 | 本轮结果 |
| --- | --- |
| `python3 packages/reader-contracts/generate-reader-settings.py --check` | 通过；生成元数据/中英资源/原生字段映射一致。已接入 Web pretest。 |
| Web `pnpm lint`、`pnpm typecheck` | 通过。 |
| Web `pnpm test` | 408 通过，0 失败、0 跳过。 |
| Web `pnpm i18n:check` | 2,066 条 zh-CN/en-US 消息通过。 |
| Readium Chromium E2E 两项 | 2 通过：出版方关闭/禁用/限制说明、三个旧控件不存在；主题确实进入正文，重排不写成进度。截图已人工检查。 |
| KMP `:shared:testAndroidHostTest` | 349 通过，0 失败、0 跳过。 |
| Android `:androidApp:testDebugUnitTest` | 171 通过，0 失败、0 跳过；包括成功只提交一次、保存失败/引擎失败保留原因且无回滚提交。 |
| iOS 最终 5 项偏好 XCTest（真机） | 5 通过：命名空间/默认值、v5 迁移与坏记录保留、全格式重置、合并/保存失败、重排进度抑制。 |
| iOS 首轮完整 ReaderPersistenceTests | 23/24 通过；1 项既有进度数据库断言失败，未跳过或削弱，见下文。 |
| 残留检索、`git diff --check` | 通过；旧出版方字段只留在集中迁移/输入测试，没有应用分支。 |

测试覆盖了 Web 的迁移重复执行、不改坏记录、账户隔离、合法非预设值、全格式重置；用禁止 fetch 的测试端口断言偏好不发同步请求，检查进度/下载存储记录不变。KMP 验证原生总开关迁移及统一目录编辑；iOS 验证原生本地存储、编辑器合并与失败、进度抑制。它们不能替代每个真机格式入口的渲染验收。

执行命令：

```sh
python3 packages/reader-contracts/generate-reader-settings.py --check
# apps/web
pnpm lint
pnpm typecheck
pnpm test
pnpm i18n:check
env -u NO_COLOR PLAYWRIGHT_BASE_URL=http://127.0.0.1:3001 pnpm exec playwright test e2e/readium-reader.spec.ts --project=chromium --grep 'settings expose|applies reader themes'
# apps/mobile
ANDROID_HOME=/Users/guyu/Library/Android/sdk ./gradlew :shared:testAndroidHostTest :androidApp:testDebugUnitTest
```

E2E 复用真实 Readium 和既有网络 fixture。fixture 补齐当前安全实现要求的 CSP 响应头，未放宽生产安全规则。截图滚动目标是可见标签，不是 `sr-only` checkbox 输入节点；断言标签在视口内。没有为了截图修改运行时逻辑。

## 真机与未验收矩阵

> 后续现场核查已确认原生滚动状态与章节分页 CSS 错配：同一会话中第44/45章正常，第46章预加载正文仍横向分页。固定 SDK 的滚动缓存问题尚未修复，不能将上文局部 EPUB 交互检查解释为滚动阅读已通过验收。详见 [2026-08-28 滚动缺陷现场记录](ios-reader-scroll-confirmation-2026-08-28.md)。

真机：iPhone 17 Pro Max，iOS 26.6，iphoneos/arm64 自动签名；设备名称为“Xiaomi 17 Pro Max”。没有使用 Simulator 或禁用签名。

| 路径 | 证据/状态 |
| --- | --- |
| iOS EPUB | 本轮重测通过：从详情打开、两个方向修改字号、控件框架保持、无可见加载指示/重新打开标记、关闭重开保留值。 |
| iOS 漫画 CBZ | 本轮 UI 测试通过：打开、外观/设置面板、页面导航和关闭重开。不是所有漫画布局或动画选项的逐项效果验收。 |
| iOS PDF | 未验收。打开时出现“阅读引擎失败，未提供详细原因”，未进入设置面板；不能归因为具体网络、文件或缩放错误。 |
| iOS TXT/FB2/MOBI、英文面板、全部在线/本地入口、每项设置的后台恢复 | 本轮未逐项跑完；不挪用此前测试结果充当此次目录改动的完整验收。 |
| iOS 最后文字显示修正 | 浮点尾数显示、固定滑动翻页说明、PDF 公共缩放回调修正已通过最后真机构建与 5 项 XCTest；EPUB/CBZ UI 截图产生于这些最后修正之前，未再次逐屏验收。 |
| Android 各格式真机 | 未验收，`adb devices` 无设备；host 单测和编译不作为真实排版效果证据。 |
| Web | Chromium 两项关键 E2E 通过；完整三引擎/移动浏览器/所有漫画 PDF 设置矩阵本轮未跑完。 |

iOS 首轮 EPUB 测试的加载断言误匹配了导航栈中隐藏的图书详情阅读进度条。改为检查可见进度指示器，并增加显式 Reader 打开标记不存在的断言；保留字号两次变化、控件框架和重开持久化断言。修正后单项真机重测通过，未通过删除正文或加载检查掩盖问题。

iOS `testExactProgressRoundTripsWithoutCreatingDurableSyncState` 仍要求 `reader_outbox` 和 `reader_sequence_counters` 表存在，与已有数据库实现不一致，产生两条断言失败。它不是偏好 v5 存储测试；本轮不改进度数据库或削弱该测试。完整 iOS 套件不能标为通过。

工具链另有现存 Android SDK XML 版本警告，以及 Xcode/固定依赖的签名剥离、API 弃用等警告。本轮不升级或修改 SDK 源码；这些不算“无警告全量通过”。

## 本机证据

- `/tmp/reader-settings-web-lint.log`、`/tmp/reader-settings-web-typecheck.log`、`/tmp/reader-settings-web-tests.log`、`/tmp/reader-settings-i18n.log`
- `/tmp/reader-settings-web-e2e.log`；`apps/web/test-results/reader-settings-publisher-master.png`
- `/tmp/reader-settings-android.log`；两个 Gradle 模块 `build/test-results` 的 JUnit XML
- `/tmp/reader-settings-ios-tests-20260828.xcresult`：首轮完整偏好套件和 EPUB/PDF/CBZ UI
- `/tmp/reader-settings-ios-epub-retest-20260828.xcresult`：EPUB 修正测试后的真机重测
- `/tmp/reader-settings-ios-preferences-final2-20260828.xcresult`：最终构建及 5 项偏好测试通过
- `/tmp/reader-settings-ios-attachments`、`/tmp/reader-settings-ios-epub-retest-attachments`：原生截图和界面层级，供本机复核，不纳入公开制品

后续验收所有者仍是 Reader 设置能力：连接 Android 真机后执行各格式两个面板；iOS PDF 打开问题定位后检查 fit 限制/缩放；补齐其余格式、本地入口和后台恢复矩阵。未在应用中保留临时替代引擎、排版补偿或迁移双份状态等待清理。
