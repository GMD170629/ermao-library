# iOS 滚动阅读状态错配：现场确认 — 2026-08-28

> **版本后续更新**：本页保留升级前的历史证据。用户随后批准 iOS Readium 3.9.0；当前版本、防回退规则与验收见 [3.9.0 升级记录](ios-readium-3.9.0-2026-08-28.md)。旧版“SDK 不变”描述不再构成回退依据。

## 结论与证据边界

**已在用户当前阅读会话中确认：保存的阅读方式、原生滚动容器和章节正文的排版状态不一致。** 这是真实的阅读器运行时缺陷，不只是代码推测或旧测试结果。

本次捕获时，第44、45章已经是正常纵向排版；同一 Navigator 预加载的第46章仍采用横向分页。不能把第46章的数据写成“已重现用户最初第45章的现场”。三个章节实测正文均为 18px，与当前保存值一致；**用户最初报告的字号不符，本轮没有复现。**

此状态符合固定 Readium 3.8.0 已知的 CSS 注入结果缓存失效缺陷。SDK 源码与官方修复说明支持这一机制；本次没有设置缓存命中断点或重放最初操作序列，因此不单独声称记录到了第45章当时的缓存命中过程。

## 设备、构建和方法

- 时间：2026-08-28 17:21–17:23，Asia/Shanghai。
- 设备：连接的 iPhone 17 Pro Max，iOS 26.6，Developer Mode enabled；未使用模拟器。
- App：既有运行进程 `37784`，没有重启、重装、清缓存或修改阅读偏好。
- 运行模块 UUID：`05CC8270-E7A9-3C56-A73D-44972279982A`，与本机最终 `Debug-iphoneos/ErmaoLibrary.app/ErmaoLibrary.debug.dylib` 一致。
- 固定 Readium：`f7d10d2bf5876408feae14d634416f69d1473fd8`（3.8.0）；SDK checkout 无修改。
- Safari 设备检查器未完成连接，改用 Xcode 随附 LLDB 附加当前进程。只遍历公开 UIView 子视图，并通过 WKWebView 公开 `evaluateJavaScript` 读取 DOM 样式/尺寸、正文字符数；通过 UIScrollView 公开属性读取容器模式/尺寸。没有调用 SDK 私有接口、注入修复样式或执行设置提交。
- 诊断 JSON 临时写入 App 的 tmp 后取回；取证完删除本次创建的六个临时文件，调试器已 detach，原进程继续运行。

## 现场数据

设备本地偏好：`flow=scrolled`、`fontSize=18`、`fontFamily=pingfang`、`lineHeight=1.7999999999999998`；出版方样式关闭。以下为真实 WKWebView 数据，尺寸单位为 CSS px/native point 对应视口尺寸，不是截图缩放像素。

| 项目 | 第044章 | 第045章 | 第046章 |
| --- | --- | --- | --- |
| 资源路径 | `text/chapter-0045.xhtml` | `text/chapter-0046.xhtml` | `text/chapter-0047.xhtml` |
| 捕获时位置 | 左侧预加载，x=-440 | 当前可见，x=0 | 右侧预加载，x=440 |
| 原生 `isPagingEnabled` | false | false | false |
| 正文 `--USER__view` | `readium-scroll-on` | `readium-scroll-on` | **`readium-paged-on`** |
| 正文计算字号 | 18px | 18px | 18px |
| 根元素 column-width | auto | auto | **810px** |
| 内容宽×高 | 440×6538 | 440×6012 | **2200×956** |
| 可见正文视口宽×高 | 440×894 | 440×894 | 440×894 |
| 正文字符数 | 3602 | 3254 | 2579 |
| JS 读取错误 | 无 | 无 | 无 |

第46章的原生容器已经关闭分页，但正文仍按横向多列排版，横向内容宽度达到视口的五倍，纵向高度则没有随整章正文增长。由这些尺寸可判断：后续正文位于横向屏幕之外，不能按正常纵向滚动读完。这能解释“只显示一部分”的机制；它不是本轮确认了原文件缺字或服务器截断。

两次独立读取均得到同样的三个章节状态，第二次不是重用第一次的输出。没有读取或导出正文内容，只记录标题、字符数和排版属性。

## 与 SDK 实现的对应关系

固定版本中：

1. `EPUBNavigatorViewModel.injectReadiumCSS` 用 `mapAsString` 包装章节，向 HTML 注入当时的偏好。
2. `TransformingResource` 的 `_data` 保存第一次转换后的结果。
3. `WebViewServer` 按章节 URL 复用这些 Resource；其 FIFO 缓存最多八项。
4. 偏好变化更新当前 WebView 的 CSS；阅读方式变化会令分页视图重载。该固定版本的 `updateCSS` 没有让 HTML 资源缓存失效，因此再次载入可能获得旧的注入结果。

[Readium 官方修复 #781](https://github.com/readium/swift-toolkit/pull/781)明确说明同一缓存机制，并在偏好更新时清除 HTML 缓存条目。项目当前固定版本早于该修复，未包含此处理。本轮没有升级 SDK 或制作补丁。

## 本机原始证据

- `/tmp/reader-live-chapter-0.json`、`reader-live-chapter-1.json`、`reader-live-chapter-2.json`：第一次三个 WebView 采样。
- `/tmp/reader-confirm-chapter-0045.json`、`reader-confirm-chapter-0046.json`、`reader-confirm-chapter-0047.json`：第二次现场采样。
- `/tmp/reader-confirm-preferences.plist`：设备偏好副本，仅本机诊断使用，不提交仓库。
- `/tmp/reader-live-device.json`、`/tmp/reader-live-processes.json`：设备与进程检查，仅本机使用。

本轮只增加诊断记录，没有修改应用代码、SDK、原文件、下载或阅读偏好；没有宣称缺陷已经修复。后续若要确认最初第45章字号不符，需要在该异常再次发生时、调整设置或重开之前重新采样。
