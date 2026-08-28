# Android 图书入口与目录页顶部修复验收

日期：2026-08-27。范围：书库/书架图书入口、详情状态隔离、两页搜索及原生 Tab。未修改后端、Web、Reader、iOS，也未提交代码或改动真实书架数据。

## 结果与根因

- 原详情栈的 `BookContentRoute` 只有节点目标，各本书的根节点均为 `Root`。导航条目的 ViewModelStore 留存在父 Activity，单独改变 Compose `key` 未能隔离这些同名条目，导致点击 ID 正确但展示上一条目的详情。
- 路由身份现在包含书籍、服务器、用户、权限版本、来源 Tab 和节点，详情及管理 ViewModel 使用路由内的书籍 ID。连续打开不同书籍以及跨 Tab 的详情栈不再串用。
- 书库/书架根页共用 `WarmPageCatalogHeader`：原生搜索框、Material 3 `SecondaryScrollableTabRow` / `Tab`，保留已有主题、页边距、名称、筛选和搜索状态。Tab 最小高度取原生文本框的 56dp 最小高度，常规字体下实测相等；不固定文字高度，允许无障碍字体增长。

## 构建、安装与测试

| 项目 | 结果 |
| --- | --- |
| Android debug APK | 构建成功；真机 `install -r` 保留数据覆盖安装 |
| Android 单元测试 | 144 通过，0 失败、0 跳过 |
| Shared Android host 测试 | 282 通过，0 失败、0 跳过；共享代码未修改，Gradle 复用有效结果 |
| 真机 instrumentation | 26 通过：Shell 8、搜索/原生 Tab 3、筛选 Sheet 3、目录呈现 12 |
| 冷启动复查 | `MainActivity` 正常 resumed，最终冷启动 429ms；crash buffer 与 am_crash/am_anr 事件无记录 |
| diff 空白检查 | `git diff --check` 通过 |
| Android lint | 未通过：4 个现有错误，见下文 |
| Web 国际化检查 | 未通过：现有管理员文案目录漂移，见下文 |

主要命令：`./gradlew :androidApp:assembleDebug`；`./gradlew :androidApp:testDebugUnitTest :shared:testAndroidHostTest :androidApp:assembleDebugAndroidTest :androidApp:lintDebug`；`pnpm i18n:check`（apps/web）。instrumentation 通过指定物理设备上的 `am instrument` 运行上述四个测试类。

测试覆盖：书库 Alpha→Beta→Alpha 详情、Home/Library 各自详情恢复、书架行分别传出自己的图书 ID、路由各身份字段及序列化、中文/英文搜索和 Tab、搜索清空/保留、控件等高、2 倍字体的筛选选项可滚动到达。原有筛选测试修正为滚动到屏幕外选项后断言，不删除断言或降低字体倍率；原 Shell 测试更新到现有书架根标签。

最新测试依据为 [instrumentation-acceptance.txt](instrumentation-acceptance.txt) 和 [unit-results.json](unit-results.json)。早期失败日志保留作诊断，不代表最终结果；最新测试 APK 构建日志为 `test-build-final.log`。

## 真机与视觉证据

物理设备：Xiaomi M2102K1AC，序列号 `9e896bbc`，Android 12，1440×3200、560dpi、zh-CN。每次安装/测试前检查 ADB `device` 状态并指定序列号。账号已有 47 本图书、书架为空；未向服务器写测试数据。界面主验收为浅色、字体 1.0；深色和字体 1.5 另行检查后已恢复。

- 修复前：书库点击“战锤40K合集”，详情却为“什么叫你看一遍就会了？！”；见 `baseline-library.png`、`baseline-wrong-book.png`。
- 修复后：真机连续打开“东京复仇者全彩31卷 PDF格式”（31 项）与“小屁孩日记”（2 项），标题/目录各自正确；见 `candidate-detail-a.png`、`candidate-detail-b-ready.png`。
- 两页顶部：`baseline-library.png` / `candidate-library.png`、`baseline-shelves.png` / `candidate-shelves.png`。书籍排序因真实服务数据而变化，不将不同封面位置当作视觉差异。
- 搜索 PDF 后 14 项，进入详情返回及切换书架再返回，搜索词和书库 Tab 保持；书架全部/书架/合集切换与筛选弹层正常。见 `flow-library-search.png`、`flow-library-filter.png`。
- `risk-library-dark.png`、`risk-library-large.png`：深色及放大字体未观察到文字重叠或遮挡。
- `candidate-detail-b.png` 是返回动画期间过早点击后截取的书库图，不作为详情验收证据，已从有效截图清单排除。

目标在修改前冻结于 [target-contract.md](target-contract.md)。[run-manifest.json](run-manifest.json) 记录 APK/截图哈希、环境、各视觉比较维度和未验证项。Native Tab 替换过矮 chips 带来的顶部高度增加属于用户要求的控件高度修正，图书网格密度、原生外壳及底部导航保留。

独立视觉复核第一阶段仅查看最终主场景截图，未提供改动说明；结论为未发现可行动的布局问题，搜索/Tab 几何一致、无截字、原生外壳保留。截图无法单独证明原生控件实现、交互语义或相对基线回归，因此该阶段不构成最终视觉 PASS。相对基线及代码的第二阶段独立复核尚未完成；主执行者已完成对应差异检查和真机测试。

## APK 身份

- 路径：`androidApp/build/outputs/apk/debug/androidApp-debug.apk`（相对 apps/mobile）。
- 包名：`com.ermao.library`；versionName `1.0.0`，versionCode `1`。
- SHA-256：`480380e7e88997a3af40f72e7eed44a4d1118f9f3413f7b61c641ee711db88f2`。
- 测试 APK SHA-256：`1008e048b29d9117a02df539a300f8f58b0d845f64fed6ff4149248ded978fbc`。
- 基于 `fa5a879dbd35bab30d9134a1adaa635f00b8943c` 加本次工作区改动；保留此前不相关的工作区变更。

## 全量门禁仍未通过

Android lint 的 4 个错误来自未修改的 `AndroidCoverSelectionReader.kt` 两处平台 ExifInterface，以及 `work_quick_remove_download`、`management_regenerate_cover_message` 两条未使用资源。详见 [lint.txt](lint.txt)。未关闭规则或添加豁免。

Web `pnpm i18n:check` 报告管理员创建/更新/删除/重置密码的 4 条新文案缺失中英目录，以及 6 条旧文案残留。详见 [i18n.txt](i18n.txt)。本次 Android UI 复用已有中英文资源，无新增应用文案。

本轮指定修复已有真机功能及视觉证据，但不宣称全产品最终验收通过。真实非空书架完整详情流程（仅有 fixture 行点击和共同详情栈证据）、TalkBack、外接键盘、分屏、新 Android 预测返回、进程死亡恢复及完整英文产品截图尚未验证；iOS 不在范围内。

## 技术参考

Android 官方 [Navigation 3 状态保存](https://developer.android.com/guide/navigation/navigation-3/save-state) 与 [Material 3 SecondaryScrollableTabRow](https://developer.android.com/reference/kotlin/androidx/compose/material3/SecondaryScrollableTabRow.composable)。
