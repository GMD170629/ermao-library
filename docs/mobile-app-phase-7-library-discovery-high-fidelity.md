# 移动 App 第七阶段：当前书库发现流程

> 文件名沿用历史阶段编号；本文保留当前查询、页面构图和状态约束，PNG 只作视觉证据。

## 查询合同

共享 [`ContentModels.kt`](../apps/mobile/shared/src/commonMain/kotlin/com/ermao/library/shared/modules/library/ContentModels.kt) 提供 Books、Series、Authors 三个 `LibraryScope`。Books 使用 `LibrarySort`、`LibraryViewMode`、`ReadingStatus` 和服务端分页；Series/Authors 使用 `GroupingQuery`，facet 使用 `FacetQuery`。两端均通过 `ContentRepository` 加载，不在 UI 推断总数或内容身份。

| 页面 | 当前交互与视觉锚点 | 代码 |
|---|---|---|
| Books | 搜索、范围、排序、Grid/List、阅读状态；结果区显示数量和可移除的已应用筛选 | Android `features/library/ui/LibraryScreen.kt`；iOS `Features/Library/LibraryView.swift` |
| Series / Authors | 分组搜索和分页；选择条目进入 facet | `LibraryScope`、`GroupingQuery`、两端 Library UI |
| Facet | 系列按 `SeriesIndex`，作者按 `RecentlyRead`；返回保留来源和查询上下文 | Android `FacetScreen.kt`；iOS `Features/Library/FacetView.swift` |

## 当前控件行为

Android 使用页面搜索字段；iOS 使用系统 `.searchable`。阅读状态筛选位于右上角 overflow menu，结果区保留活动筛选摘要和移除入口；应用筛选、取消、清除和重试由 ViewModel/Store 负责，关闭 Sheet 后焦点返回菜单。排序和 Grid/List 选择使用平台原生 Menu/Picker 语义，不自绘跨平台 overlay。

Books 默认以三列 Cover Grid 呈现，空间不足或用户选择时转为 List；封面、标题、作者和阅读进度使用共享内容组件，用户内容保持原样。Series/Authors 结果是平面分组列表，facet 页面按对应排序展示内容。页面保持四个根 Tab 和当前导航返回上下文。

## 状态与安全

查询至少覆盖 loading、首屏 empty、搜索 empty、普通网络失败、分页失败、无权限/未授权和成功追加。失败状态在原位显示重试，不以空结果伪装。分页使用共享模型的有界 page size，并以稳定顺序请求下一页。

服务端返回未授权时进入当前会话的重新认证路径；`authzVersion` 改变时先隔离旧封面、标题、作者、进度和筛选摘要，再按新命名空间重新请求。搜索只针对当前服务器/用户命名空间，不读取其他 profile 的本地内容。

## 当前视觉参考

有效的页面与状态资产位于 [`assets/mobile-app-hifi-v1`](assets/mobile-app-hifi-v1)：

- [`library-app-light-v1.png`](assets/mobile-app-hifi-v1/library-app-light-v1.png)、`library-series-scope-app-light-v1.png`、`library-authors-scope-app-light-v1.png`；
- `library-series-facet-app-light-v1.png`、`library-author-facet-app-light-v1.png`、`library-filter-sheet-app-light-v1.png`；
- `library-sort-menu-app-light-v1.png`、`library-view-menu-app-light-v1.png`、`library-search-empty-app-light-v1.png`；
- `library-network-error-app-light-v1.png`、`library-pagination-error-app-light-v1.png`、`library-permission-revalidation-app-light-v1.png`。

这些图像冻结内容顺序和密度，不冻结系统搜索、Picker、Menu、Sheet、字体度量或安全区。Android `design-qa/android-warm-page-v2/reference-manifest.json` 和 `VisualFixtureActivity` 是当前回归入口；iOS 搜索、动态字体、返回和权限状态必须在真机验证。视觉 token 以 [`visual-tokens.json`](../packages/design-contracts/visual-tokens.json) 为准。
