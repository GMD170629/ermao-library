# 移动 App 全局开发规范：当前原生边界

> 文件名沿用历史名称；本文只保留当前实现需要遵守的规则。当前有效契约、已接受且未被取代的 ADR 和 Reader 架构规定目标行为；代码用于确认现状，不将既有缺陷视为要求，旧计划与截图不能覆盖当前契约。

## 权威来源与复用

- 功能、会话、导航和内容身份遵循当前有效契约与 Accepted ADR，shared KMP modules 和两端 Shell 是实现检索入口；Book、Resource、Asset 是当前内容关系。
- 视觉数值只来自 [`packages/design-contracts/visual-tokens.json`](../packages/design-contracts/visual-tokens.json) 及生成绑定。
- Reader 过滤、格式/MIME admission、资源预算和错误语义只来自 [`reader-safety-policy.json`](../packages/reader-contracts/reader-safety-policy.json) 及其生成绑定。
- 先复用已有 shared application/domain/adapter 和 feature public API；同一状态、下载管线、认证或规则只能有一个 owner。

## 组件所有权

| 类别 | 处理方式 |
|---|---|
| A：Navigation、Tab、Sheet、Menu、Dialog、Picker、权限、返回 | 使用平台 API；页面提供语义、内容和回调，不复制系统几何、阴影或手势。 |
| B：Search、输入、Switch、Slider、加载反馈 | 使用原生控件并以 token 做品牌着色；保留键盘、焦点、无障碍和取消行为。 |
| C：Cover、Book/Resource 身份、业务状态、内容列表、进度、Reader 内容 | 由 App 组件实现，使用生成 token；状态由错误码/枚举驱动。 |
| D：Reader controls、沉浸层和 determinate progress | 遵循 Reader v5 合同与平台手势；动效只表达可观察状态并支持 Reduced Motion。 |

不要把 Web CSS/DOM、截图颜色或自绘全屏 overlay 当作原生实现。新组件必须说明语义 owner、输入输出和状态，不能以 pass-through 包装或平行 feature 复制现有行为。

## 当前视觉与平台规则

App Shell 使用 light-only 主题；`actionAccent` 是全页唯一实心 CTA 与交互文字的品牌角色，按 v1.2.0 产品配色验收。Reader 另有 Day、Warm、Green、Night、Black 主题及 Reader System 模式。正文可读性、危险语义、Cover 2:3、进度分离和布局度量从生成合同读取；不要在文档或代码复制 token 数值。

Android 当前入口包括 `WarmPageTheme`、`WarmPageTokens`、`WarmPageScaffolds`、`WarmPageActions`、`WarmPageNavigation` 和 feature 内容组件；iOS 入口包括 `AppTheme`、`BrandedControls`、`ContentComponents` 和 feature views。Android `WarmPageNavigationSuite` 与 iOS 紧凑 `RootTabControls` 仍需保持系统 inset、返回、键盘和无障碍语义。

Android 操作按钮不得只呈现无样式文字：紧凑操作复用 `WarmPageIconAction`，需要可见说明的操作使用带图标的原生样式按钮；图标保留双语无障碍名称、禁用态及原有回调。导航列表、选项、分页编号和原生系统选择器保持各自控件语义。

个人资料头像只显示账户接口返回的 `avatarImageUrl` 对应图片，默认头像由服务端统一提供；`avatarUrl` 仅标识自定义头像，用于删除入口。旧接口未提供展示字段时仅兼容其自定义头像地址。图片无法加载时不生成首字母、默认插画或自定义头像；本地待上传照片不代替账户头像，上传和删除后重新读取响应指定的图片。

## 状态、身份与安全

页面明确实际适用的 loading、empty、error、permission、unauthorized、pagination 和 retry，不创建无业务意义的状态或 UI；错误分支使用稳定 error code，不按本地化文本分支。请求、缓存和下载按当前 `serverIdentity + userId + authzVersion` namespace 隔离；Reader 进度按 Reader v5 合同的 server/user/client/book/resource 归属维护。无独立离线 Shell；只有完整校验并原子发布的本地工件可进入本地阅读或播放。

Reader 平台代码只能检测事实、调用生成 rule ID 并执行生成的 `ALLOW`、`SANITIZE`、`BLOCK_RESOURCE`、`REJECT_PUBLICATION` 决策。安全失败不得回退到旧解析器、旧过滤器、在线正文或派生持久化包；策略变更必须先改机器合同并重新生成绑定。

## 国际化、无障碍与测试

每个可见功能完成 `zh-CN`/`en-US`；用户标题、作者、系列、标签、路径和文件名不翻译。iOS 触控目标至少 44pt，Android 至少 48dp；支持 Dynamic Type/字体缩放、VoiceOver/TalkBack、键盘、焦点、Reduced Motion 和系统安全区。

Android 默认用真机做功能、Reader 和视觉验收，模拟器仅作补充；iOS 的 build、Reader、系统控件和视觉验收使用真机，不以 Simulator 代替。无网络视觉夹具在 `apps/mobile/androidApp/.../visual/VisualFixtureActivity.kt`，回归运行记录在 `apps/mobile/design-qa`。从成功、空态、失败、重试、未授权、切换命名空间和重新进入中选择实际受影响路径；不宣称仅编译通过即界面或设备验收完成。

## Review 要求

变更说明简述实际修复、复用归属、有效证据与具体缺口；真机路径确有需要时报告对应证据，不为小补丁建立报告体系。检查依赖方向、单一状态 owner、取消/清理、权限、locale、token 来源和安全策略生成状态；范围外重复先记录；只有影响本次正确性、安全复用或必须突破边界时才取得范围决定。旧合同冲突按根规则的权威来源处理。


## 本地安装包目标与真机执行

构建前识别宿主操作系统：macOS 默认仅构建 iOS 真机测试安装包；Windows 默认仅构建 Android 测试 APK。用户明确指定其他目标时可覆盖默认，但必须具备工具链和设备条件，不能把覆盖请求当作工具链可用的证据。Linux 不自动选择移动安装包目标，按明确任务或既有 CI 配置执行。

KMP 共享修改选择受影响共享检查和直接消费者，在必要验证阶段构建当前主机对应安装包；同模块相关修复可共用一次验收构建，不因每次修改共享文件反复打包。另一平台实际未验证的路径须记录。此分工不修改 CI 矩阵，不删除跨平台测试。仅文档改动不触发安装包构建。验证范围由 [测试执行策略](testing/test-execution-policy.md) 决定。

本次验收构建需要安装、冷启动与相关运行检查；中间编译不必反复安装。以下真机检查清单按受影响能力选择，不要求每次执行全部设备交互回归。

### Android 真机步骤

Android 设备调试、安装、仪器测试、截图、性能与运行验收默认真机。以下步骤用于实际需要的设备操作，普通单元和静态检查不要求设备连接。

- 设备安装、仪器测试或运行验收前运行 `adb devices -l`，目标须为 `device` 状态，指定不以 `emulator-` 开头的准确序列号；多台设备时不得隐式选第一台。
- 对本次验收 APK 保留数据覆盖安装，随后 force-stop、冷启动；核对包与版本、前台 activity、启动后 crash/ANR 日志。正常部署不卸载或清空数据，中间编译不必安装。
- 按影响选择 Compose UI/仪器、TalkBack、键盘、旋转、分屏、返回、真实网络/存储、进程恢复、截图或核心路径检查；不为小修复强制执行完整清单。
- 有真机时不自动启动 AVD；仅用户明确要求补充设备/API 矩阵或 CI 无法接入硬件时使用模拟器。其证据不替代最终真机运行和视觉验收。
- 无合适、已授权且可用的设备时仅停止所需设备验证，报告缺口；可继续无设备依赖的工作，不静默降级模拟器或将编译当作运行通过。

### iOS 真机步骤

iOS 平台构建使用 `iphoneos`/`iosArm64` 工具链，设备测试和运行验收仅物理 iPhone/iPad。普通共享单元或静态检查不要求设备在线；不以 iOS Simulator 替代。

- 不创建、启动或选择 Simulator，不用 `simctl`、`iphonesimulator`、`iosSimulatorArm64`、`iosX64` 或模拟器 SwiftUI Preview 作为开发/测试路径。
- 从 `xcodebuild -showdestinations` 选择准确物理设备标识，不用 Simulator destination，不关闭签名绕过设备构建。验收构建安装后按相关路径冷启动验证，中间编译不必反复安装。
- 设备安装、设备测试或运行验收前确认连接/配对、Developer Mode、解锁可用性和有效签名 Team。需要服务器的场景确认设备可访问测试服务器，不使用设备自身的 `localhost` 代指开发主机。
- 按实际影响选择 XCTest、UI、Keychain/TLS/网络/进程恢复、无障碍、截图或运行冒烟，不为一个显示问题重演所有流程；仅设备目标编译不等于运行验收。
- 无合适设备时停止所需运行门禁并报告缺口，继续可独立进行的检查，不使用 Simulator、降低门禁或宣称运行通过。脚本、CI 和验收记录不得新增 Simulator 执行作为替代证据。
