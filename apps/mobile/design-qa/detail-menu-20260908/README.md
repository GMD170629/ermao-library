# 手机端详情管理能力收敛

## 实现

- KMP `managementActions` 继续作为 Android/iOS 菜单的唯一 owner；Book、Directory、Resource 不提供 Recognize，识别提供方加载、搜索、应用也按同一规则阻断。
- 编辑流程复用 `BookManagementSession`：删除 CoverEdit、封面草稿、setCover 和封面保存阶段；Book 保存元数据/标签，Directory 保存标题/简介，Resource 保存元数据。目录 multipart 仍使用既有 PUT，固定 removeCover=false 且没有文件部分。
- Android 编辑控件和 iOS 残留选图编辑分支均已清理。独立资源上传继续复用 uploadResourceCover，并要求当前上传阶段、权限和 interactionId；已关闭、切换目标及过期回调不上传。
- 独立上传、重新生成及管理设置的识别能力保持原范围。无后端、数据库或 Web/PWA 功能修改。

## 验证

| 检查 | 结果 |
|---|---|
| KMP workmanagement | 36 passed：会话 18、封面类型 2、Ktor repository 16 |
| Android 详情相关 JVM 测试 | 34 passed：详情 ViewModel 2、详情布局 30、相关 mapper/metrics 各 1 |
| Android 真机管理交互 | 10 passed；补充表单底部取证后两项中英文测试复验 passed |
| 普通 Android APK 与 instrumentation APK | 独立目录构建成功，真机 replace-install 成功 |
| Web 目录一致性 | 实际 i18n 检查脚本验证 2,106 条 zh-CN/en-US 文案通过 |
| iOS | 已更新 Swift 调用与菜单 XCTest；当前 Windows 环境没有 Xcode/iOS 真机，编译与设备验收待完成 |

请求与会话测试覆盖三类编辑保存、失败重试、不修改封面、识别直接调用/重试/重新打开不请求、独立上传重试及迟到回调。设备测试运行生产管理组件与 fake repository，不写真实书库；尚无 iOS 设备或真实服务器写入验收证据。

测试在 `D:/www/ermao-menu-check` 验证目录执行，基于 `76202adf` 带入本次改动。主工作区同期存在其他 Android 按钮修改与编译错误；未将这些无关改动带入验证。重叠 BookManagement 文件保留同期描边按钮修改，运行时正文与主工作区一致（仅 import 排序不同）。不据此宣称包含所有并行改动的整包验收完成。

标准 `pnpm i18n:check` 因环境提供 pnpm 11/Node 24、仓库要求 pnpm 9.12.2/Node 22.23.1 而未运行成功；随后直接执行相同 `generate-i18n-catalog.mjs` 并设置现有 PYTHON_EXECUTABLE，通过目录检查。没有修改或降低项目 engines。

## 真机与产物

- 设备：`9e896bbc`，Xiaomi M2102K1AC，Android 真机。
- 包：`com.ermao.library`，versionName `1.0.0`，versionCode `1`。
- APK：`D:/www/ermao-menu-check/apps/mobile/androidApp/build/outputs/apk/debug/androidApp-debug.apk`。
- SHA-256：`B128724C4E4676CC9685E89E0965B6B04A77FC62AD630FA4BFA853B352099AB5`。
- 普通 APK 保留数据安装成功；force-stop 后启动 MainActivity 返回 COLD / Status ok。取证后恢复到普通 MainActivity。
- crash buffer 中同期出现的是另一 `uiautomator DumpCommand` 注册 UiAutomationService 冲突，没有发现本次普通 App 冷启动的崩溃；本次 instrumentation 返回 OK。

## 证据与首次失败

- `android-build.txt`、`shared-tests.txt`、`android-instrumentation.txt` 保存成功构建/测试输出。
- `screenshots/` 保存中英文 Book 菜单、编辑表单与底部，以及英文 Resource 菜单；截图使用明确的测试标题/作者。
- `android-editor-bottom.txt` 保留最初两项失败：只调用 performScrollTo 时原生 Sheet 尚在半展开位置，保存按钮未进入可见区域。测试补上用户正常上滑展开 Sheet 后，保留同一可见性断言并通过，见 `android-editor-bottom-retest.txt`。没有修改产品 Sheet 布局或放宽断言。
