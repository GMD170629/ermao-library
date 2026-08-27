# 手机端 Reader 全格式审计与修复（2026-08-27）

## 范围和判定

本轮检查项目定义的 13 种可读原始格式：EPUB、MOBI、AZW、AZW3、PRC、FB2、
TXT、PDF、CBZ、ZIP、CBR、RAR、IMAGE_DIR。音频属于独立播放器，不在本轮
Reader 范围；DRM、加密或损坏文件必须返回错误，不能绕过保护或伪装支持。

13 种格式原本都有入口和引擎装配，但不等于阅读能力完整。以下记录区分
代码实现、自动化测试、实际真机旅程和仍未完成的门禁，不沿用旧记录的
`ACCEPTED` 作为当前源码证据。保留了开始本轮前已有的目录导航等未提交修改。

## 审计发现与修复

### FB2 原文件阅读

原来的 Android/iOS FB2 适配器只抽取段落，未正确读取 `book-title`，丢失
嵌套目录、行内格式、插图、表格、诗歌和脚注/返回链接。它们使用未补零的
段落序号作为锚点，与服务端 `shuku-fb2-publication-v1` 不同。

现在由平台 XML 解析器读取原文件，KMP `Fb2PublicationDecoder` 统一生成
内存 Publication，使用与服务器相同的资源拆分、六位节点锚点及目标链接。
Android 使用有界 SAX 输入；iOS 使用 Foundation XMLParser，并显式拒绝
Foundation 自身可能接受的未声明属性前缀。保留 UTF-16/声明编码和已知的
`l:href`/`xmlns:xlink` 输入修复，拒绝 DTD、实体、非法结构、重复 ID、超限
内容和非法图片。图片先校验 Base64、大小与 MIME 签名，再放入内存资源。

`reader-contract.fb2` 是本项目自编语料，其正文 golden 来自现有服务端适配器。
Android、iOS 和 Python 同时比对实际正文、目录 href 和锚点；测试还检查原文件
字节不变。不存在生成 EPUB、ZIP 或解包出版物目录的生产路径。

### Android 可重排格式导航

TXT、FB2、MOBI/AZW/AZW3/PRC 的直接构造 Publication 缺少 positions service，
导致 `positions()` 为空，进度条跳转无法得到目标。三个适配器现在注册 Readium
`EpubPositionsService`。MOBI 使用原始解析器资源描述符长度建立位置索引，
不为索引预读或装饰整本正文。百分比仍仅用于用户主动跳转，不作为精确恢复或
同步位置。

新增 FB2 仪器化打开/目录/正文/位置测试，扩展 TXT 与 MOBI 的位置服务测试。
依赖 Android `Uri`/Readium 的测试放在真机仪器化层，没有为 JVM 构造伪平台或
禁用断言。

### iOS 错误隔离

TXT 规范化的 Kotlin 异常现在通过显式 `@Throws` 跨 Swift 边界，避免空白 TXT
触发未处理 Kotlin 异常。TXT/FB2 打开失败映射到 Reader 文件错误，不误报为
网络成功或输出空白出版物。真机负向测试验证该错误可捕获。

### KINDLE 在线入口与原始格式身份

真机全格式旅程发现 MOBI/AZW/AZW3/PRC 并未到达 Reader bootstrap，而是被旧
入口策略送进“尚未提供阅读器”的占位页面。Library 合同返回资源族 `KINDLE`，
旧策略却对在线入口套用了离线文件必须具有具体扩展名的限制。

Android 在线入口和 iOS remote handoff 现在接受可重排 `KINDLE` 资源，由既有
Reader bootstrap 校验并返回具体原始格式。下载校验、已验证本地文件以及引擎
仍只接受 MOBI/AZW/AZW3/PRC，不把 `KINDLE` 作为文件格式，不更改后端合同。
两端测试覆盖在线分流、拒绝模糊离线文件及音频/未知格式的边界。

### 旧版 MOBI6 正文渲染

初轮 UI 旅程虽然通过了容器存在与进度变化断言，人工截图检查仍发现
MOBI/AZW/PRC 显示 WebKit XML 错误。固定版本 libmobi 的旧格式输出缺少
XHTML 默认命名空间与 `mbp:pagebreak` 的前缀声明，Foundation XMLParser
接受该输入不代表 WebKit 能显示正文。

两端现在共享 `MobiMarkupEnvelope`，只在内存中补齐根元素缺失的命名空间，
之后仍执行原安全策略。原文件、正文、href 和定位投影不变；已有命名空间
不覆盖，处理可重复执行。共享层、Android 安全策略和 iOS 实际 libmobi
语料测试验证这一边界，UI 旅程增加 XML 错误页检测，避免同类假阳性。

### IMAGE_DIR 证据质量

旧真实书库样本的两张 PAGE 均为 1×1 PNG，Reader 黑色截图无法证明正常尺寸
图片显示。已将既有原始 PAGE 集合发布测试扩展为两张不同的 320×480 PNG：
经过真实本地发布、IMAGE_DIR Publication 打开、按序读取及 UIKit 解码，
逐页验证原字节和尺寸，保留图片附件。此证据验证原始图片资源链路，不冒充
正常尺寸图片的完整 Reader UI 截图验收。

### 真机测试入口与加载边界

原 live UI 测试把资源 ID 注入图书根页的临时选中态，与当前独立资源路由不符。
DEBUG 启动入口改为正式 `bookContent.resource` 路由，页面统一按目的地加载，
并显式选择目标首页标签，避免被持久化的书架标签遮住。防止重刷丢失目标。
测试等待加载边界，并断言中心点击能恢复控件；没有移除原有
翻页、进度变化、退出及重开断言。两个既有真机下载诊断测试也改用当前开发网关
3000 端口，原来的 8000 端口仅监听主机 loopback，真机无法连接。

### iOS PDF 中心点击

PDF 正文和精确页码已恢复，但含可选文字的部分页面会由 PDFKit 的文本手势
拦截 Readium 的低优先级点击，造成工具栏无法唤回。Session 现在拥有原生容器
点击识别器及清理生命周期；单击导航与文本交互同时识别，双击缩放仍优先，
选区清除和注释链接不转化成翻页。Readium 委托不再重复处理同一点击。
真机旅程额外断言中心点击隐藏/唤回控件，防止重复切换或控件困住用户。

## 格式实现矩阵

| 原始格式 | Android | iOS | 本轮重点 |
| --- | --- | --- | --- |
| EPUB | Readium Kotlin | Readium Swift | 现有原始 EPUB 打开、导航、恢复路径回归 |
| MOBI / AZW / AZW3 / PRC | libmobi 内存 Publication → Readium | libmobi 内存 Publication → Readium | KINDLE 在线入口、旧 MOBI6 命名空间、Android positions；有界惰性读取 |
| FB2 | SAX → KMP FB2 → Readium | XMLParser → KMP FB2 → Readium | 富内容、目录、图片、脚注、精确锚点、安全边界 |
| TXT | 严格解码 → KMP TXT → Readium | 严格解码 → KMP TXT → Readium | Android positions；iOS 异常隔离 |
| PDF | 原生 PDFium/Readium，支持在线 Range | PDFKit/Readium，支持在线 Range | 页码/进度合同与现有打开路径回归 |
| CBZ / ZIP | 原始 ZIP 漫画/在线页面流 | 原始 ZIP 漫画/在线页面流 | 现有打开、分页和重开路径回归 |
| CBR / RAR | archive-core 原始 RAR/在线页面流 | archive-core 原始 RAR/在线页面流 | 现有打开、分页和重开路径回归 |
| IMAGE_DIR | 原始 PAGE 集合/在线页面流 | 原始 PAGE 集合/在线页面流 | 现有页面读取及重开路径回归 |

## 当前自动化证据

- Android/KMP：当前工作区共享层 278、Android 应用 143、MOBI 模块 1，共 **422 项 JVM
  测试通过**，0 failure、0 error、0 skip。
- Android Debug APK、androidTest APK、MOBI androidTest Kotlin 编译、
  `verifyDesignTokens`、`verifyMobileOfflineContract` 通过。
- Python Reader/Publication 聚焦套件：**98 passed**；新增 FB2 golden 合同通过。
  修改的 Python 测试文件 Ruff format/check 通过。保留 1 条已有 Starlette/httpx
  弃用警告，没有改动依赖或降低检查。
- iOS：签名 `iphoneos` 构建，物理 iPhone 17 Pro Max，iOS 26.6，
  destination `00008150-0011112211A0C01C`。首轮 **44 项 Reader 单元/集成测试通过**，
  包括 libmobi 语料、PDF Range、精确进度、本地持久化、FB2 正文与安全、空白 TXT。
- Kindle 入口修复后，18 项 DownloadStore 测试（含原始 AZW3/EPUB 真机下载）和
  6 项 PDF 测试全部通过。
  PDF 控件隐藏/唤回、导航和重开旅程也通过，结果包为
  `Test-ErmaoLibrary-2026.08.27_16-05-38-+0800.xcresult`（24+1，0 失败）。
- iOS FB2 真实书库详情 → Reader → 下一页/滑动 → 进度跳转 → 关闭重开通过，
  已人工查看正文与重开截图；44 项测试与该旅程合计 45 项、0 失败。
  结果包：`Test-ErmaoLibrary-2026.08.27_15-48-55-+0800.xcresult`。
- 后续 41 项 ReaderSecurity/MobiCore/MobiPublicationFactory/DownloadStore 测试
  在同一物理 iPhone 通过，包含新增旧 MOBI6 正文合同及两张真实尺寸 IMAGE_DIR
  资源。加上 PDF 6、持久化 19、进度合同 5，去重后 **71 项 iOS 单元/集成测试通过**。
  该次结果包 `Test-ErmaoLibrary-2026.08.27_16-33-16-+0800.xcresult` 的 UI 部分失败于
  上述启动标签恢复问题，不把整个结果包写成通过。
- Android 最新构建与 JVM 日志：`/tmp/ermao-reader-android-final.log`；
  Python 聚焦结果：`/tmp/ermao-reader-api-tests.log`。
- 最终设备检查确认 `com.ermao.library` 1.0.0 (1) 已安装，保留数据冷启动成功。
  2026-08-27 16:39 查询设备应用崩溃记录，仅存在 08-25 的旧记录，未发现本轮
  应用崩溃记录；这不代替完整 ANR/性能/系统矩阵验证。

## 真机旅程与尚未完成的门禁

本轮 iPhone 在线旅程分批执行，入口、下一页/滑动、进度跳转、退出重开均保留
断言。进度断言验证数值变化及重开后的有效位置，并不等价于逐字验证保存和
恢复完全相同；精确位置由独立合同/持久化测试覆盖。

| 格式 | 当前证据 |
| --- | --- |
| EPUB / FB2 / TXT | 真实书库旅程通过，人工查看正文与重开截图 |
| PDF | 旅程及控件隐藏/唤回通过，人工查看重开后第 31/43 页 |
| AZW3 | 真实书库旅程通过，原始 KF8 正文可见 |
| MOBI / AZW / PRC | 命名空间修复后重新执行的 3 项真机旅程全部通过；人工确认重开截图显示中英文正文，无 XML 错误页 |
| CBZ / ZIP / CBR / RAR | 旅程通过，人工查看实际漫画页面与重开截图 |
| IMAGE_DIR | 1×1 样本在线旅程通过；两张 320×480 原始 PAGE 资源/解码测试通过并查看图片附件；正常尺寸完整 Reader UI 尚待补验 |

EPUB/FB2/TXT/CBZ/ZIP/RAR/IMAGE_DIR 的结果来自
`Test-ErmaoLibrary-2026.08.27_16-07-01-+0800.xcresult`；该包中旧 MOBI/AZW/PRC
虽然 UI 自动化通过，截图出现 XML 错误，已明确排除为渲染通过证据。
AZW3/CBR 个别通过用例来自 `Test-ErmaoLibrary-2026.08.27_16-00-11-+0800.xcresult`，
该包整体因当时的 PDF 点击与旧网关诊断测试失败，不标记为整体通过。
MOBI/AZW/PRC 最终复测包为
`Test-ErmaoLibrary-2026.08.27_16-36-19-+0800.xcresult`（3 项、0 失败）；正文截图
导出至 `/tmp/ermao-reader-mobi-visual-final`。这批语料正文很短，重开截图显示
0% 不作为长篇书籍精确恢复的证据，也不使用进度百分比替代 locator。

- Android：使用 SDK 的 `platform-tools/adb devices -l` 多次检查，均无物理设备。
  因而未安装、未运行仪器化，未启动 AVD。构建通过不能代替 Android 真机验收。
- Android `lintDebug` 当前工作区为 **7 个非 Reader 错误**：封面选择器两处旧
  `android.media.ExifInterface`，并行改动的书架页 `NonObservableLocale`，以及
  `shelves_scope`、`shelves_inaccessible`、`work_quick_remove_download`、
  `management_regenerate_cover_message` 四个未使用资源。本轮没有关闭 lint。
- 全仓 Web `pnpm i18n:check` 被既有用户管理文案目录问题阻断（4 个缺失键、
  6 个失效键，无占位符不匹配）。本轮未新增 UI
  文案；FB2 测试中的中英文是书籍内容，保持原文。
- iOS 构建保留非本轮代码的 onChange、旧 CBZNavigator、工作管理类型转换、
  方向配置和 AppIntents metadata 警告；未通过屏蔽警告声明全量质量门禁通过。
- 两端完整 VoiceOver/TalkBack、大字、横屏/分屏、系统返回、弱网与断网、
  进程死亡精确恢复的当前组合矩阵仍未全部执行。旧日期的离线验收不作为
  当前修复版本的完整验收替代。

本轮状态：格式实现缺口已修复；双平台最终验收仍需 Android 真机及剩余门禁。
