# 阅读三端直接接入与轻量能力统一 — 2026-08-29

## 实施范围

本轮保持偏好 schema v5、Reader v4 服务端接口和固定 SDK 不变。权威设置目录仍为
`packages/reader-contracts/reader-settings.json`，现同时拥有 43 项设置、稳定 control、
上下文规则和中英文禁用原因。Web 与 KMP 生成物共享 `可用 / 暂不可用 / 未实现 /
不适用` 四态语义；三端继续展示适用格式的全部目录项，不再维护平台隐藏清单。

## 已接通的消费链

| 能力 | 当前实现与约束 |
| --- | --- |
| Web 重排滚动 | 保存的 `textFlow` 原样映射到 Readium `scroll`；滚动时双页暂不可用，返回分页后保留原 spread。偏好提交和 viewport resize 不再主动导航；preferences 操作产生的位置事件不会上传进度。 |
| Web 出版方样式 | 开启时释放字体、字重、字距、行距、段落缩进/间距和对齐；主题、字号、页宽、滚动和 spread 继续生效。释放控件保留保存值并显示上下文原因。 |
| Android EPUB spread | 存储和 session 不再把 EPUB spread 覆盖为单页；`auto/single/double` 映射 Readium `ColumnCount.AUTO/ONE/TWO`。漫画仍由当前单页 Navigator 限制。 |
| 三端逻辑页宽 | 宽度大于 640 时只约束居中的 Navigator 容器，采用 `min(可用宽度, 保存宽度)`；窄屏全宽。外层工具栏和手势区域保持全屏。 |
| iOS 漫画/PDF 主题 | 根画布、空白区和错误/加载状态改用当前 `ReaderPalette`；PDF 页面与漫画像素不着色。 |
| 能力纠错 | Web 音量键、Android 漫画动画声明为未实现；Android 远程 PDF fit、iOS 分页 PDF fit、原生负字距继续保持禁用。Android 漫画 spread/封面独立等目录项恢复显示。 |

## 自动化证据

| 检查 | 结果 |
| --- | --- |
| 设置目录 | 43 个唯一设置；生成器 `--check` 通过。 |
| Web typecheck | 通过（Node 22.23.1 / pnpm 9.12.2）。 |
| Web Reader 聚焦测试 | Readium 映射、出版方 CSS、目录与四态规则共 12 项通过。 |
| Web 全量门禁 | lint、typecheck、i18n 2,067 条消息及 412 项单测全部通过。Windows 使用 `PYTHON_EXECUTABLE` 和 UTF-8 模式运行仓库同一提取器。 |
| Web Chromium E2E | 设置状态/分页→滚动→分页与主题重排不写进度共 2 项通过。 |
| KMP + Android 单测 | `:shared:testAndroidHostTest` 与 `:androidApp:testDebugUnitTest` 全部通过。 |
| Android 真机 | M2102K1AC / Android 12 上偏好持久化 3 项 instrumentation 通过；Debug APK 完整构建、安装并冷启动到 `MainActivity` 成功。 |

## 仍需现场验收

- Android 手机真机已完成自动化，但宽屏页宽和双页视觉验收需要平板、折叠屏展开态或大于
  640dp 的横屏可用区域；手机只能验证窄屏全宽及禁用原因。
- iOS 当前 Windows 主机不能执行 `iphoneos/arm64` 构建或 XCTest。必须在签名可用的
  macOS 主机完成 iPhone/iPad EPUB、漫画、PDF 打开与五主题画布检查；PDF 未成功进入
  Reader 前不得记为视觉通过。
- Web 真实 Chromium 已覆盖分页→滚动→分页和偏好重排不写进度；章节切换与关闭重开
  的滚动布局仍需补充现场矩阵，本页不把单测替代为该证据。
