# Android 最新版重新编译与真机测试 — 2026-08-27

## 结论

最新源码的 Debug APK 已重新生成，在指定物理 Android 设备上保留数据替换安装并成功冷启动。**测试存在失败项，不代表完整验收通过。** 本轮没有修改业务源码，也没有降低 lint 或测试规则。

## 源码、构建及设备身份

- 分支：`develop`，fetch 后与 `origin/develop` 一致。
- Commit：`fa5a879dbd35bab30d9134a1adaa635f00b8943c`。
- APK：`apps/mobile/androidApp/build/outputs/apk/debug/androidApp-debug.apk`。
- APK 大小：89,420,470 bytes。
- SHA-256：`5e1e2a265704be6a697471a410ccb72993c3a6dbd9883558e3e6b4adf24a0f4f`。
- 包名：`com.ermao.library`；版本：`1.0.0`，versionCode `1`。
- 物理设备：`9e896bbc`，Xiaomi `M2102K1AC`，product/device `mars`。
- 每次安装及 instrumentation 运行前均重新执行 `adb devices -l`，确认精确序列号处于 `device` 状态；未使用模拟器。
- App 和测试 APK 均使用 `adb -s 9e896bbc install -r`，返回 `Success`；未卸载、未清除应用数据。
- App `firstInstallTime`：2026-08-16 13:58:22；`lastUpdateTime`：2026-08-27 19:47:29（设备时间）。
- force-stop 后冷启动：`Status: ok`，`LaunchState: COLD`，初次耗时 1458ms。
- 启动后前台 Activity：`com.ermao.library/.MainActivity`；实际阅读时确认进入 `features.reader.presentation.ReaderActivity`。
- 启动及测试后 crash buffer 无输出，所检查 events 中没有 `am_anr` / `am_crash` 记录。

## 构建前置依赖恢复

首次构建在 archiveCore 的 CMake 配置阶段失败。`apps/mobile/.gitignore` 的 `**/build/` 规则忽略了 libarchive 上游源码所必需的 `build/version` 和 `build/cmake`，并非 Android 生成目录。

按仓库 `native/archive-core/UPSTREAM.md` 锁定的 libarchive 3.8.9 上游发布包恢复缺失的 `build/` 目录。下载包 SHA-256 已核对为 `888c934f9d95648ecb9163dc8e23ab80a476ecb81a8f1154704a227b5b676dde`；仅提取缺失目录并使用 `--keep-old-files`，没有升级依赖或覆盖已有源码。恢复文件仍受现有忽略规则影响，**全新检出环境仍可能遇到相同可复现构建问题**。

## 自动化检查

| 检查 | 本轮结果 |
| --- | --- |
| `:shared:testAndroidHostTest` | 282 通过，0 失败、错误或跳过 |
| `:androidApp:testDebugUnitTest` | 143 通过，0 失败、错误或跳过 |
| `:androidApp:assembleDebug` | 成功，生成本轮 APK |
| `:androidApp:assembleDebugAndroidTest` | 成功，生成本轮测试 APK |
| `:androidApp:lintDebug` | 失败，4 errors；联合 Gradle 命令因此返回构建失败 |
| 真机 instrumentation（3 个测试类） | 21 项，19 通过，2 失败 |
| 仅重跑上述两个失败方法 | 两项均再次失败，未忽略或降级 |

### Lint 失败项

1. `AndroidCoverSelectionReader.kt:9`：使用 `android.media.ExifInterface`，规则要求 AndroidX 实现。
2. 同文件第 82 行：相同 ExifInterface 问题。
3. `values/strings.xml:237`：未使用 `work_quick_remove_download`。
4. `values/strings.xml:590`：未使用 `management_regenerate_cover_message`。

此外构建输出有 SDK XML 版本兼容提示（旧命令行工具只理解至 v3，而 SDK 中有 v4）。未更改工具链或屏蔽提示。

### 真机测试范围与失败

- `AndroidShellSmokeTest`：6 项中 5 通过。
- `DirectoryContentPresentationTest`：12 项全部通过，覆盖根/子目录、0/1/3 资源数量与目录动作范围。
- `ReaderEpubInstrumentedTest`：3 项中 2 通过；真实 EPUB 的旋转、生命周期及精确位置保存恢复测试通过；已不存在资源的旧位置处理测试通过。
- 失败一：`eachRootTabOwnsAVisibleNavigationDestination` 断言 `tab-shelves` 可见。当前实现实际标签为 `shelves-root`（`ShelfCatalogScreen.kt:102`），测试仍引用旧标签；实际账号下书架入口与空页面可正常打开。
- 失败二：`opensRendersNavigatesAndAppliesPreferencesWithReadium` 等待 WebView 计算样式超时（第 118 行）。此前打开、目录切换、返回和 Readium settings 断言均已执行通过；不能据此宣称最终字体、行高、颜色及 WebView 样式完全正确。失败后面的安全检查断言未执行，不能计入通过范围。

## 实际账号交互证据

- `01-cold-start.png`：首页正常，原有登录会话和图书数据保留。
- `02-shelves.png`：书架入口可达，显示当前账号空状态。
- `03-resource-detail.png`：从首页进入现有 EPUB 资源详情，不自动启动 Reader；阅读和下载为独立动作。当前提交已移除旧封面氛围背景，本轮没有重新加入。
- `04-online-epub.png`：不点击下载，直接点击“开始阅读”，原始 EPUB 内容成功显示；此次未出现“文件发生变化”的阻塞提示。没有清除已有 Reader 缓存，不能据此声称完成首次无缓存网络读取测试。
- `05-epub-controls.png`：中心点击成功显示 Reader 顶部栏、进度、目录、笔记、外观及阅读设置。
- `reader-style-failure.png`：失败用例运行中的夜间 Reader 实际画面，仅作诊断证据，不能替代样式断言。
- 单次横向滑动后截图没有显示页面变化；后续设备页面发生其他导航，未完成隔离复核，**不将触摸翻页或返回恢复计为本轮手工通过项**。

## 未覆盖与交付边界

本轮未完成全部格式、无缓存在线读取、下载暂停/继续/取消、TalkBack、实体键盘、分屏、预测返回、完整中英文/主题/大字体组合及进程死亡恢复矩阵。不将单元测试、部分 instrumentation 或 APK 安装成功当作全量发布验收。

为了便于继续手动测试，收尾阶段停止屏幕输入，保留最新 APK 与原有应用数据。未替用户修改业务逻辑或提交/推送代码。本记录及相邻日志为本轮测试证据。

## 原始记录

- `build.log`：恢复依赖后重新构建的完整输出。
- `lint-results-debug.txt`：4 项 lint 错误。
- `instrumentation-recheck.txt`：两个失败方法的完整独立复跑输出。
