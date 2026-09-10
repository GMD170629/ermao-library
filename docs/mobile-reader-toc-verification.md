# Mobile 目录与原生面板

执行范围遵循 [测试执行策略](testing/test-execution-policy.md)：以下清单是按实际影响选择的入口，不是每个补丁的必跑项。复用有效证据；局部修复完成与最终发布验收分别判断。历史结论及专项契约要求不因此改变。

## 当前实现

- KMP `ReaderNavigation.kt` 统一解析当前目录项；适配器提供 href、fragment 与 selector，标题和展示百分比不作为选择键。
- Android 用 `ReadiumLocatorMapper` 保留启动和目录目标的锚点，`LazyColumn` 在每次打开后对同一当前项定位一次。
- Android 使用一个 Material3 `BottomSheetScaffold`，紧凑态显示进度与四个 Tab；选择 Tab 后面板内容替换进度，关闭恢复进度。原生状态拥有拖动、停靠和嵌套滚动，测量阶段读取其 offset 保持底部控件位置。
- iOS 使用 `List`／`ScrollViewReader`，等待定位数据就绪后执行一次打开定位，使用原生 medium／large sheet。
- 两端保留原始标题、连续目录行与层级缩进；手动滚动及调整面板高度不会重复居中。

章节生成与键值规则见[统一章节解析](reader-chapter-consistency.md)，进度和面板边界见[Reader 架构](mobile-reader-architecture.md)。

## 验收状态

2026-09-05 的工作记录包含 Android 物理设备目录定位、章节跳转、原生面板拖动和冷启动验证。它不是本次工作区的重新验收证明。

iOS 构建、XCTest、物理设备交互及 VoiceOver 尚待执行；TalkBack 与键盘验收当次未运行。大字体与横屏适配验收当次被延期。共享测试和代码审查不能替代这些路径。

复验时覆盖异步目录加载、首次定位、手动滚动保留、重新打开、折叠／展开、Tab 切换、拖动不触发正文翻页与章节跳转后的高亮。设备序列号、APK 哈希和临时截图路径不在本页长期维护。
