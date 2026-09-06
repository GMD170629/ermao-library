# v2 工程与真机检查

范围：本轮五项细节反馈及其直接共享消费者。颜色契约仍为 1.2.0；没有修改业务 API、持久化行为、依赖、Reader、后端、iOS 或 Web 代码。

## 构建与静态检查

- 增量 Gradle：`verifyDesignTokens :androidApp:testDebugUnitTest :androidApp:assembleDebug :androidApp:assembleDebugAndroidTest` 成功，见 `build-3.log`。
- 最终仅修正测试观测方式后，`:androidApp:assembleDebugAndroidTest` 成功，见 `build-test-4.log`；应用 APK 未发生变化。
- `git diff --check` 通过；Git 的 CRLF→LF 提示不是新增编译或 lint 警告。
- 47 个 JUnit suite / 204 个 testcase：失败 0、错误 0、跳过 0。
- 三条新文案键 `work_contents_path_title`、`work_contents_current_directory`、`work_contents_sort` 均存在于中英文 XML，XML 可解析。
- lint 未通过：46 项既有错误，按 issueId + 文件聚合与 v1 分类一致：UnsafeOptInUsageError 34（Audio 两文件）、UnusedResources 9、PluralsCandidate 2、ExportedService 1。v1 原始 XML 未保存，不宣称字节相同；本轮没有新增分类、文件或计数，没有新增 baseline 或放宽检查。

初次构建暴露的 `semantics.role` 缺失 import 和测试 DpRect 的 `height` 访问已修正。旧失败日志保留，最终构建结果见上，不以失败旧日志代替当前状态。

## 真机组件测试

设备 `9e896bbc`，安装测试 APK 后直接执行 AndroidJUnitRunner；没有运行会卸载主应用的 connectedAndroidTest，也没有清空数据。

25 个不同用例最终通过：WarmPageMenusTest 3、WarmPageNavigationTest 3、WarmPageSearchFieldTest 3、SettingsComponentsTest 选定默认字号用例 3、WarmPageScaffoldTest 安全区用例 1、HomeScreenTest 3、WorkContentsPathSheetTest 1、AdministrativeSettingsUiTest 3、DownloadScreensTest 5。

首轮 `device-tests-1.log` 为 24 通过 / 1 失败：路径测试读取了合并语义行的触控矩形，短标题与两行标题都受到 48dp 最小行高约束，无法判断文本换行。最终测试改为读取实际 TextLayoutResult，要求 lineCount > 1 且没有 visualOverflow，并继续验证当前项选中、根目录 null ID 和祖先原 ID 回调。`device-tests-path-final.log` 为 OK (1 test)。没有放宽产品尺寸、删除断言目标或跳过测试。

这些是组件 fixture，证明布局和回调；完整 Shell 以另存的产品真机原图为准。

## 产品烟测

| 路径 | 结果 / 证据 |
| --- | --- |
| 冷启动首页 → 书库 → 书架 → 我的 | 四个选中位置均无底色断层、相同外距；01 / 14 / 20 / 21 |
| 首页最近入库 → 鸡皮疙瘩系列 | 主封面与阅读区域保持位置，工具栏同排；02 |
| 第一子目录 → 左侧路径 → 根目录 | 完整名称和当前勾选可见，点击根目录返回；03 / 05 / 06 |
| 目录网格 → 列表 → 排序 Z–A → A–Z → 网格 | 排序结果实际改变、恢复默认；07 / 08 / 09 / 10 |
| 卷册封面长按、目录更多、资源更多、书库更多、图书长按 | 菜单可展开和返回关闭；08 / 10 / 11 / 13 / 22 / 23 |
| 我的 → Kindle 队列 → 全部 / 进行中 / 失败 | 选中状态和文字轴线稳定，空态说明正确；15 / 16 / 17 |
| 账户、日志、用户筛选页 | 共享 Tab 排版、输入形状与固定顶部位置一致；18 / 19 / 28 / 29 |
| 根目录 → 下载卷册 → 展开目录 → 取消 | 保留 Sheet 与选择树行为，未提交下载；24 / 25。状态相关下载菜单只做源码与共享菜单组件检查 |

`26-users-tabs` / `27-users-disabled` 是操作中 Sheet 先折叠后关闭形成的误命名捕获，未作为用户页证据；正确证据为 28 / 29。它们保留在私有目录供追溯。

最终 APK SHA-256 `d905267a8db41ba174f6bde5874b668204bb671cdf684e5043b625982ca339bd`，设备安装的 base.apk SHA 相同。`adb install -r` 保留数据，MainActivity 冷启动成功并处于前台；crash buffer 未发现应用崩溃。

没有发送邮件、提交账户或配置、读取密码、触发下载、删除或修改任何图书。默认字号之外的测试没有运行。Web 本轮没有变更，不把 v1 的 Web 结果包装成本轮新验证。

## 复用与边界

- 颜色与半径：既有 WarmPageThemeValues，未建立第二套颜色或跨平台 schema。
- 菜单：WarmPagePopup / WarmPageMenuItem 为唯一外壳与行默认值 owner；ManagementAnchor 消除 280dp 私有宽度，MultiDownloadSheet 移除直接 DropdownMenuItem 实现。浮动菜单仍保留原交互，没有恢复已退役的调用方。
- 设置列表过滤：SettingsTabRow 为唯一 Tab owner；WarmSettingsFilterBar 提供既有类型化选项映射，移除重复 QueueFilterChips；局部筛选状态、枚举与回调保留。SMTP 加密等表单字段继续使用分段控件。
- 目录路径：workContentBreadcrumbs 提供路径数据，既有 onOpenSourceNode 执行导航；新增展示面板没有解析书名或推导资源格式。
- 只读代码审查指出 selected 不属于 options 时的潜在兜底边界；当前所有真实消费者均使用完整固定枚举并包含 selected，未形成可复现缺陷。未扩展为异步选项组件或修改业务状态。
