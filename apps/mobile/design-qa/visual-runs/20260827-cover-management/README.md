# 封面长按管理移植：实现与验收记录

日期：2026-08-27。范围：Mobile，共享网络传输及测试；未修改 Web、后端或数据库功能。

## 已实现

- 共享 `workmanagement` 三类显式目标（Book / Directory / Resource）、权限菜单、编辑、封面、识别、Kindle、阅读状态与删除流程。
- Android 封面锚定菜单；iOS 系统 context menu。首页、书库／搜索／分类、书架图书、详情主封面及子内容接入；拼图封面不提供单本操作。详情“更多”保留。
- 图书图片生成使用整书 covers multipart；目录使用自己的 source node；资源使用精确 resource ID。目录没有删除项，普通用户可切换图书阅读状态及发送允许的 Kindle 资源。
- 编辑清空字段、封面保留／替换／移除／撤销；图书按元数据、标签、封面顺序保存，并报告部分成功。识别保留完整字段集合及 appliedFields / skippedFields / coverStatus，结果在原生表单中展示。
- 删除需输入名称，资源删除携带可重试的 Idempotency-Key；不会离线排队执行破坏操作。Kindle 优先选择被长按资源的 PRIMARY 附件，保留整书合格 EPUB/PDF 附件和重复入队反馈。
- 操作防重复提交，过期结果拒绝，账号／服务器／授权变化销毁旧会话。刷新及封面失效；列表刷新保留查询、排序及已加载页窗口。删除当前对象后退出对应详情。
- 删除旧的占位编辑／识别 UI 和旧接口编排，双端共用共享应用流程。保留原有导航与书架工作区改动。

## 已通过的检查

验证副本：`/tmp/ermao-cover-management-20260827-goi5ayci`，基线 `fa5a879d`。

| 检查 | 结果 |
| --- | --- |
| `:shared:testAndroidHostTest` | 294 项，0 失败，0 跳过 |
| `:androidApp:testDebugUnitTest` | 144 项，0 失败，0 跳过 |
| `:androidApp:lintDebug` | 通过 |
| `verifyDesignTokens` | 通过 |
| `verifyMobileOfflineContract` | 通过 |
| Android 主包、交互测试包构建 | 通过 |
| Mobile 新增文案 | Android 资源无重复，iOS nativeManagement 键均有 en / zh-Hans |

共享新增测试覆盖三类权限矩阵、精确目录／资源身份、分页定位、multipart 无文件与有文件、字段清空与省略、永久删除确认与重试幂等键、保存顺序与部分失败、Kindle 默认附件／重复提交，以及识别默认字段和部分成功。

### 隔离验证原因

执行过程中，主工作区出现了并行 Reader 引导／下载及组合根改动，且同时修改了 `ApiClient.kt`。主工作区后续编译因此失败。没有修改、还原或覆盖这些并行改动。

隔离副本保留本次 Mobile 代码和已有导航／书架改动，Reader 和其 Android/iOS 组合根保持 HEAD；`ApiClient.kt` 仅应用本次 multipart 和 Idempotency-Key 四个变更块。libarchive 的既有 vendor/build 定义也已复制供原生构建使用。完整范围见 `validation-scope.txt`，通过日志见 `isolated-gates.txt`。这不是“当前并行工作区的全部改动已通过”的声明。

## 真机状态与待验

Android：物理设备 `9e896bbc`（M2102K1AC），每次安装／测试前均重新确认 ADB 状态。主包、测试包均使用 `install -r`，未卸载或清除数据。包 `com.ermao.library`，versionCode 1，versionName 1.0.0。前一轮冷启动 `LaunchState: COLD`、MainActivity resumed，未发现当次启动 crash；最终包安装后设备再次锁屏，最终冷启动与交互门禁尚待解锁验证。

首轮 5 项 Compose 交互测试在夹具初始化处失败：语言覆盖 Context 未保留 ActivityResultRegistryOwner，尚未进入手势断言。夹具已修正，测试包编译通过并已安装，**尚未取得修正后的物理设备通过结果**。原始失败证据为 `instrumentation.txt`，不得将其解释为通过。

待运行：长按不触发普通点击、滚动不打开菜单、普通用户资源 Kindle 权限、脏编辑退出确认、中文深色菜单；以及全入口实际网络操作、Web 回读、TalkBack／VoiceOver、键盘、大字体、旋转／分屏、返回及删除恢复。破坏性实际操作必须使用专用测试内容；本次没有修改或删除真实藏书。

iOS：当前环境为 Windows / WSL，无可用 Mac、签名或物理 iPhone/iPad。Swift 代码已接入，但没有 Xcode 编译、真机运行或 VoiceOver 证据。未使用模拟器。

Web `pnpm i18n:check` 已执行，因现有用户管理文案缺失和陈旧键失败，详情见 `web-i18n-existing-failures.txt`。没有改动 Web 文案，也没有降低门禁。

## 继续验证

1. 解锁 Android，确认 `adb devices -l` 精确序列号及 unlocked 状态。
2. 在已安装测试包上运行 `adb -s 9e896bbc shell am instrument -w -e class com.ermao.library.features.workmanagement.BookManagementCoverTest com.ermao.library.test/androidx.test.runner.AndroidJUnitRunner`，检查明确的 `OK (5 tests)`，不能只看命令退出码。
3. 测试后 force-stop 并冷启动主应用，检查 resumed activity 与当次 crash / ANR 日志，再做真实页面非破坏性冒烟。
4. 并行 Reader 改动稳定后，在主工作区重跑全部 Mobile 门禁；在 Mac 和物理 iOS 设备上完成 iOS 编译与运行验收。
