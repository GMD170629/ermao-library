# 移动 App 全局开发规范：当前原生边界

> 文件名沿用历史名称；本文只保留当前实现需要遵守的规则。代码、Accepted ADR、生成合同和 Reader v5 架构优先于旧计划与截图。

## 权威来源与复用

- 功能、会话、导航和内容身份以 shared KMP modules、两端 Shell 和 Accepted ADR 为准；Book、Resource、Asset 是当前内容关系。
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

页面必须明确 loading、empty、error、permission、unauthorized、pagination 和 retry；错误分支使用稳定 error code，不按本地化文本分支。请求、缓存和下载按当前 `serverIdentity + userId + authzVersion` namespace 隔离；Reader 进度按 Reader v5 合同的 server/user/client/book/resource 归属维护。无独立离线 Shell；只有完整校验并原子发布的本地工件可进入本地阅读或播放。

Reader 平台代码只能检测事实、调用生成 rule ID 并执行生成的 `ALLOW`、`SANITIZE`、`BLOCK_RESOURCE`、`REJECT_PUBLICATION` 决策。安全失败不得回退到旧解析器、旧过滤器、在线正文或派生持久化包；策略变更必须先改机器合同并重新生成绑定。

## 国际化、无障碍与测试

每个可见功能完成 `zh-CN`/`en-US`；用户标题、作者、系列、标签、路径和文件名不翻译。iOS 触控目标至少 44pt，Android 至少 48dp；支持 Dynamic Type/字体缩放、VoiceOver/TalkBack、键盘、焦点、Reduced Motion 和系统安全区。

Android 默认用真机做功能、Reader 和视觉验收，模拟器仅作补充；iOS 的 build、Reader、系统控件和视觉验收使用真机，不以 Simulator 代替。无网络视觉夹具在 `apps/mobile/androidApp/.../visual/VisualFixtureActivity.kt`，回归运行记录在 `apps/mobile/design-qa`。验证要覆盖成功、空态、失败、重试、未授权、切换命名空间和重新进入，不宣称仅编译通过即完成。

## Review 要求

变更说明应列出复用的 owner、受影响入口、状态/错误路径和真机证据。检查依赖方向、单一状态 owner、取消/清理、权限、locale、token 来源和安全策略生成状态；发现超出边界的重复实现或旧合同冲突时先记录并取得范围决定。
