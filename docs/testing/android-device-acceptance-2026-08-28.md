# Android 更新安装与当日待补真机验收 — 2026-08-28

## 结论

当前代码的 App / instrumentation APK 已构建并保留数据安装到物理 Android。**验收未通过**：53 项仪器测试中 43 通过、10 失败；失败相关测试类复跑 21 项，原 10 项全部再次失败。实际账号打开 EPUB 还触发一次系统 ANR。没有修改业务代码、放宽断言或跳过失败测试。

本轮补验依据：当日的 `mobile-reader-online-first`、`reader-settings-unification`、`reader-parser-implementation`、`mobile-library-controls`、`mobile-cover-menu-localization` 记录。`reader-online-errors` 中已被后续实现覆盖的旧规则不作为验收标准。

## 构建、设备及安装

- 基础提交：`79a27828ccc09970e5965844fdf6a602c17a0622`；开始时工作区干净。
- 本轮唯一构建代码修改：`apps/mobile/androidApp/build.gradle.kts` 中的测试资产同步，见下节。
- APK（Windows 绝对路径）：`\\wsl.localhost\Ubuntu-24.04\home\liumianti\ermao-library\apps\mobile\androidApp\build\outputs\apk\debug\androidApp-debug.apk`。
- APK（WSL 绝对路径）：`/home/liumianti/ermao-library/apps/mobile/androidApp/build/outputs/apk/debug/androidApp-debug.apk`。
- 大小：103,166,282 字节；SHA-256：`0fbfebb917841039658505d992352e22c144fc3dc2ce259c145d92a2f35b5a55`。已在设备端对已安装 `base.apk` 再次计算并核对一致。
- 包名：`com.ermao.library`；版本：`1.0.0 (1)`，不是版本发布。
- 物理设备：`9e896bbc`，Xiaomi `M2102K1AC` / `mars`，Android 12，arm64；未使用模拟器。
- 每次安装和测试批次前检查 `adb devices -l`；App 和测试 APK 均使用精确序列号 `install -r`，返回 `Success`。
- App 首次安装时间仍为 2026-08-16 13:58:22；更新为 2026-08-28 20:20:06。无卸载、无清数据、无更换账号或服务器。
- 首次更新后冷启动：`Status: ok`，`LaunchState: COLD`，1419ms；前台为 `.MainActivity`。
- 收尾重新 force-stop / 冷启动：409ms，`.MainActivity` 在前台，已返回正常首页；收尾这个新时间窗口未发现 crash / ANR。**这不抹去此前 EPUB 的 ANR。**

## 解除测试包阻塞：复用而非绕过

首次构建复现当日已记录的 `mergeDebugAndroidTestAssets` 失败：MOBI 与漫画语料都有根级 `CORPUS.md`。

复用现有 `syncReaderTestFb2Assets`，将其扩展并更名为 `syncReaderTestAssets`，集中同步 EPUB / MOBI / Comic / PDF / FB2 语料；删除四个旧的直接资产目录接线。仅排除会重名的根级 `CORPUS.md` 说明文档，FB2 子目录结构保持原样。没有删除原始语料文件、引擎依赖或测试。

打包完成后对 APK 内 **40 个语料/支持文件**与源文件逐一校验 SHA-256，全部相同。证据：`test-assets-verification.txt`。

## 自动检查

| 检查 | 本轮结果 |
| --- | --- |
| `:androidApp:assembleDebug` | 成功 |
| `:androidApp:assembleDebugAndroidTest` | 成功 |
| `:shared:testAndroidHostTest` | 349 通过，0 失败/错误/跳过 |
| `:androidApp:testDebugUnitTest` | 171 通过，0 失败/错误/跳过 |
| `:androidApp:lintDebug` | **失败：58 个 UnusedResources**，均为阅读器旧字符串；未新增 baseline 或关闭规则 |
| `pnpm i18n:check`（apps/web） | 2,066 个 zh-CN / en-US 消息通过 |
| `git diff --check` | 通过 |

联合 Gradle 命令最终因 lint 返回失败；不能将其写成“所有构建门禁通过”。已有 SDK XML v3/v4 工具兼容警告仍存在。没有执行无关后端全量门禁、iOS 测试或发布。

## 真机 instrumentation

| 测试类 | 通过 | 失败 |
| --- | ---: | ---: |
| AndroidShellSmokeTest | 9 | 0 |
| LibraryFilterSheetTest | 3 | 0 |
| DirectoryContentPresentationTest | 9 | 3 |
| BookManagementCoverTest | 2 | 5 |
| ReaderPreferencesInstrumentedTest | 1 | 0 |
| ReaderTxtInstrumentedTest | 2 | 1 |
| ReaderFb2InstrumentedTest | 2 | 0 |
| ReaderMobiInstrumentedTest | 1 | 0 |
| ReaderPdfInstrumentedTest | 2 | 0 |
| ReaderCbzInstrumentedTest | 1 | 0 |
| ReaderRarInstrumentedTest | 1 | 0 |
| ReaderR4PersistenceInstrumentedTest | 7 | 0 |
| ReaderEpubInstrumentedTest | 2 | 1 |
| EpubContentSecurityPolicyInstrumentedTest | 1 | 0 |
| **总计** | **43** | **10** |

通过范围包括书库菜单→筛选→取消/应用/清除、四 Tab、不同图书导航身份、筛选英文/窄屏大字、中文深色管理菜单、偏好账户隔离、TXT/FB2/MOBI 的产品 Reader、PDF 原生引擎及适配设置/重建、漫画原件、进度存储与迁移，以及 EPUB 后台/旋转/重开位置恢复。它们主要使用隔离 fixture，不是每种格式的真实网络验收。

失败及复跑结论：

1. **封面管理 5 项**：英文 `Edit` / `Send to Kindle` 找不到或不可见，脏草稿测试未能进入编辑；按压位置测试预期偏移 60，实际为 0。中文深色与滚动不误开两项通过。不能据此把英文失败全部归为业务操作失效，也不能以中文手工通过代替英文验收。
2. **子目录 3 项**：0 / 1 / 3 资源的非根目录测试中，展开菜单后 `work-directory-download` 不可见。独立目录菜单及根目录用例通过；完整子目录路径仍失败。
3. **TXT metadata 原因传播 1 项**：第 128 行将完整 `ReaderError` 与 `cause=null` 的期望比较，但实际已保留 `IllegalArgumentException`。错误码/阶段与期望一致，此处是旧对象相等断言与新增 cause 契约冲突。没有为过关删除 cause 或改弱断言；失败之后的 positions 变体不能算已验证。
4. **EPUB 样式 1 项**：`computed WebView preferences` 超时；此前 Reader、目录和 SDK preferences 检查已走到，最终字体/行高/颜色综合断言未通过，后续安全章节断言未执行。与 8 月 27 日记录的失败相同，但仍需定位。

复跑 `BookManagementCoverTest`、`DirectoryContentPresentationTest` 及上述 TXT/EPUB 两个方法：21 项中 11 通过、同样 10 项失败。原始记录为 `instrumentation.txt`、`instrumentation-recheck.txt`。

## 真实账号手工检查

- 冷启动恢复现有账号首页，服务器内容正常显示；初始启动瞬间的登录过渡截图不是最终页面。
- “继续阅读”打开 TXT `7--影子女孩`，显示服务端测试文本。它不是当日含 NUL 的问题原件，也不能替代那份原件的验收。
- 中心点击显示控制栏；可进入中文外观、阅读设置及高级设置。可见出版方样式总开关、固定开启滑动翻页说明，以及暂不支持选项的限制说明。
- 字号从 18 连续调为 20，关闭 Reader 并重新打开，外观面板仍显示 20；随后恢复原值 18。截图只能证明捕获时状态，不能证明整个设置过程中绝无瞬时加载、Navigator 重建或网络请求。
- 书库菜单提供筛选/排序/视图；实际选择未读、应用后 47 部变为 46 部并出现“未读”条件标签，移除标签恢复 47 部。取消/清除的自动化回归亦通过。
- 实际长按封面显示中文管理动作；编辑表单中文正常。未修改/保存书目、未删除、未重扫、未再生成封面、未发送 Kindle。阅读操作可能按既有逻辑记录进度。

### 实际 EPUB ANR：阻止验收通过

从首页封面进入《末日生存方案供应商》独立 EPUB 详情，点“开始阅读”，未点下载。打开期间点击阅读区域，出现系统“二毛图书没有响应”。

- 时间：2026-08-28 20:29:30；PID 5205。
- 系统 `am_anr` 原因：`ReaderActivity` 的 `MotionEvent(action=DOWN)` 等待 **5005ms**。
- ANR 采样主线程栈：`ReadiumEpubSession.prepare(ReadiumEpubSession.kt:315)` → `Publication.locatorFromLink` → `Manifest.linkWithHref` → `Url.equals` / Android URI 编码。
- 当前应用第 315 行位于遍历 `canonicalUnits` 建立目录并逐项调用 locator 的循环。证据指向应用在主线程准备目录/定位信息的热点；尚未进行独立性能剖析，不能声称已证明全部耗时来源或归咎于 SDK 缺陷。
- 正文随后出现在 ANR 弹窗后方；不把“最终出正文”当作可用性通过。记录弹窗后回到了 Shell，没有把该次称为无损 Reader 恢复。
- force-stop 后再次进入相同详情并开始阅读，15 秒后的截图显示正文；之后横向滑动有正文翻页证据。第二次成功不撤销首次失败。
- ADB 左方向键注入后的截图未变化；后续 PageUp/反向滑动有捕获，但未完成隔离断言，不声称物理键盘矩阵通过。

关键证据：`23-live-epub.png`（打开中）、`23-live-epub-controls.xml`（ANR 文案）、`24-live-epub-after-wait.png`（正文及系统 ANR）、`anr-events.txt`、`epub-anr-main-thread.txt`、`28-epub-retry-15s.png`、`29-live-epub-swipe.png`。

## 仍未完成的当日验收

以下保持“待验收”，不以主机单测、fixture 仪器测试或已缓存重开替代：

- 空缓存时阻断原文件及非当前章请求，证明首屏/内存界限与无完整文件任务；本轮没有清除用户缓存、替换服务器或部署受控网络故障代理。
- 真实在线限额/不支持 Range → 可见下载过渡、真实进度、独立任务复用、取消归属、账户切换后迟到完成不打开、目标章节/进度恢复、下载后解析失败不循环、离线重开完整链路。
- 存储不足、断网/鉴权/损坏/版本变化等故障矩阵；不能为制造失败填满用户手机或破坏现有下载。
- 当日含 NUL TXT 原件、全格式真实网络及本地入口、每项设置效果、全格式重置与坏记录恢复的逐项原生交互。
- Reader 英文完整面板、TalkBack、物理键盘、分屏、全 App 深色/大字矩阵。已跑的英文筛选/窄屏大字/中文深色 fixture 仅覆盖对应组件。
- 当前物理设备为 Android 12，无法提供 Android 13+ predictive-back 的系统验收证据。
- 未测试真实 2 GiB 文件打开成功率或流畅度；349 项共享测试中的准入边界不等于大文件设备能力。

本任务是构建和验收，未擅自修复 ANR、设置实现、菜单行为或扩大为 Reader 架构迁移。继续修复及受控端到端故障测试需要后续明确范围。

## 证据目录与命令

证据统一在 [2026-08-28 Android 验收目录](../verification/2026-08-28-android-acceptance/)。`build.log` 是首轮资产冲突；`build-final.log` 是完成 APK/单测但 lint 失败的完整日志。安装、最终前台、设备 APK hash 与收尾日志也在同一目录。

```sh
# WSL，apps/mobile
ANDROID_HOME=/home/liumianti/Android/Sdk ./gradlew \
  :androidApp:assembleDebug :androidApp:assembleDebugAndroidTest \
  :shared:testAndroidHostTest :androidApp:testDebugUnitTest :androidApp:lintDebug --console=plain

# Windows，每次安装/测试前检查并指定物理设备
adb devices -l
adb -s 9e896bbc install -r <app-or-test-apk>
adb -s 9e896bbc shell am instrument -w -r -e class <上表测试类列表> \
  com.ermao.library.test/androidx.test.runner.AndroidJUnitRunner
```
