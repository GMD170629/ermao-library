# 移动 App 第五阶段：当前高保真视觉锚点

> 文件名沿用历史阶段编号；PNG 只冻结页面构图和密度，平台系统控件仍由原生实现。行为与身份分别以 Phase 1–3、Reader v5 架构和当前代码为准。

## 共同规则

- 主 Shell 参考画布为 `390 × 844`，Android 登录/服务器参考也有 `412 × 915`；设备外框、状态栏和系统控件不作为跨平台像素基准。
- 使用 `App Light` 和生成视觉 token；Reader 使用自己的主题。不要从 PNG 采样颜色、重绘系统图标或把演示数据当作服务端内容。
- 内容区严格复现信息层级；Navigation、Tab、Sheet、Menu、Dialog、Picker、Slider、权限与返回只复现语义和位置，细节由平台决定。

## 页面锚点与实现

| 页面 | 可复用参考资产 | 当前实现入口 |
|---|---|---|
| Home | [`home-app-light-v1.png`](assets/mobile-app-hifi-v1/home-app-light-v1.png) | Android `features/home`；iOS `Features/Home` |
| Library | [`library-app-light-v1.png`](assets/mobile-app-hifi-v1/library-app-light-v1.png) 与同目录的搜索、facet、空/错态图 | `modules/library/ContentModels.kt`；两端 `features/library` |
| Book detail | 以当前 feature 视觉夹具/真机图为准，不依赖缺失的历史组合图 | `modules/library` 与两端内容详情 UI；目录/资源由 `BookContentTarget` 决定 |
| Reader | [`reader-paper-v1.png`](assets/mobile-app-hifi-v1/reader-paper-v1.png) | Android `features/reader/presentation`；iOS `Features/Reader`；详细合同见 `mobile-reader-architecture.md` |
| Audio Now Playing | [`audio-now-playing-v1.png`](assets/mobile-app-hifi-v1/audio-now-playing-v1.png) | `modules/audio`、Android `features/audio`、iOS `Features/Audio` |
| Shelves | [`root-approved.png`](assets/mobile-shelves-v2/root-approved.png)、[`collection-approved.png`](assets/mobile-shelves-v2/collection-approved.png)；布局合同见 [`mobile-shelves-row-layout.md`](mobile-shelves-row-layout.md) | 两端 `features/shelves` |
| Me | [`me-app-light-v1.png`](assets/mobile-app-hifi-v1/me-app-light-v1.png) | 两端 `features/me` 与设置模块 |
| Downloads | [`downloads-app-light-v1.png`](assets/mobile-app-hifi-v1/downloads-app-light-v1.png) | `modules/downloads`、两端 `features/downloads` |

## 组合要点

- Home 以继续阅读为首要任务；Library 以搜索/范围/排序/视图/状态筛选为发现路径；Shelves 以范围和行式内容为组织路径；Me 以系统设置行为呈现身份和管理入口。
- Book 根页只显示一个当前封面、身份、进度、主要动作和内容浏览器；目录节点显示面包屑/排序/分页/子项；Resource detail 显示资源信息和相应 Reader/播放动作。不得根据数量猜测落点。
- Reader 是隐藏 Shell chrome 的沉浸层，正文为第一视觉层；Audio Now Playing 保留 Cover、时间轴和系统播放控制；Downloads 聚合任务状态与已验证本地内容。
- 阅读进度、下载进度和播放进度使用独立语义。空、加载、失败、权限和分页状态保持稳定布局并提供原位恢复。

## 证据边界

`docs/assets/mobile-app-hifi-v1` 是当前页面参考和 QA 输入；`apps/mobile/design-qa` 的 manifest/run 是验证证据，不是新的功能合同。Android `VisualFixtureActivity` 支持无网络页面夹具；Reader 与 iOS 系统控件需真机检查。服务器登录、Setup、重新认证及账户停用资产由 [`mobile-app-phase-6-server-auth-high-fidelity.md`](mobile-app-phase-6-server-auth-high-fidelity.md) 维护，Library 变体由 [`mobile-app-phase-7-library-discovery-high-fidelity.md`](mobile-app-phase-7-library-discovery-high-fidelity.md) 维护。
