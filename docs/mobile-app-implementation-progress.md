# Mobile App 实施进度

> 更新时间：2026-08-08
>
> 当前阶段：B1 与 Mobile 视觉基线重构已完成；B2 登录与会话框架已完成，真实服务/真机生命周期验收待完成

## 本轮已完成

### 视觉与交互设计基线

- 已将 `docs/mobile-app-design-guidelines.md` 固定为 Mobile 权威规范，设计风格为 Apple HIG × 温暖编辑感（Warm Editorial Native）。
- 已建立 spacing、type、control、radius、elevation、motion、breakpoint 与浅/深色语义 token，并通过主按钮前景对比度测试。
- 已接入 iOS SF Symbols 与 Android 合法等义符号的穷尽式 `AppIcon`，移除数字、emoji 和临时字符图标。
- 已生成 iOS、Android legacy、adaptive foreground/background 与 Android 13+ monochrome 品牌资产；启动屏采用浅/深背景连续过渡，不制作广告式 Logo 闪屏。
- App Shell 已改为 Compact 底部标签和 Expanded 侧栏；布局切换同时考虑可用宽度与字体缩放。
- 旧服务器连接视觉已完全替换，连接首页、地址输入、服务器列表与 QR 全状态均使用同一共享组件和语义 token。

### 契约与数据模型

- 移动端内容身份已统一为 `work -> mediaVersion -> volume`，本地进度槽位包含 `workId`、`mediaVersionId`、`volumeId` 和 `contentFingerprint`。
- Reader 网络契约已切换为 Reader v3 volume-first 模型。
- 已加入 Reader v3 OpenAPI 生成物、确定性生成脚本、严格 wire decoder 和到移动端/`reader-core` 类型的 mapper。
- 已覆盖 bootstrap、位置联合类型、相对资源 URL、能力矩阵、`foliate` 边界和非法响应测试。
- 已明确 Reader v3 HTTP schema 3 与 `reader-core` schema 4 的边界，不使用类型断言把两个模型混为一体。

### B1：服务器连接

- 连接地址现明确定义为用户在浏览器中访问二毛图书时使用的 Web 根地址；移动端从该前台地址同源派生 `/api/*`，不要求用户填写独立后台地址或内部端口。
- 手工地址、QR 扫描、相机权限、扫描锁定/重试和错误恢复页面已接入同一个连接 application flow。
- 手工与 QR 输入共用地址解析、安全限制和 base path 规则；公网要求 HTTPS，受支持的局域网地址允许 HTTP。
- 健康检查、初始化状态、超时、取消、不兼容响应和持久化失败均映射为显式 outcome。
- server profile 使用原子 `ServerProfileCatalog`，提供 load、select、delete 和 reset-corrupt use case。
- 选择已有 profile 前执行健康复检；并发删除后，迟到的选择结果不能复活已删除 profile。
- 删除 active profile 会将 active 置为 `null`，不会自动选择另一条连接。
- 最新快照损坏但仍有有效旧快照时恢复并报告 warning；只有所有受管快照完全损坏时，才允许用户显式原子重置连接数据。
- 已覆盖手工/QR 地址边界、取消、并发、codec/schema 拒绝、旧有效快照恢复和完全损坏重置测试。
- 连接首页已改为内容优先的分组入口；地址页使用持久标签与就近错误；服务器列表使用单一分组列表；QR 页面覆盖权限、后台暂停、扫描、处理中、无效码、连接失败和相机失败。

B1 已完成：代码、自动化测试和 Android/iOS 双平台 export 的最终门禁均已通过。

### Expo Router 与 App flow

- 已切换为 Expo Router，并使用 `(connection)`、`(auth)`、`(main)` route group。
- 根布局通过 `Stack.Protected` 和 app-flow state 限制连接、身份和主界面访问，根 route 按状态导向 `/connect`、`/login` 或 `/library`。
- 启动时加载 active profile、重新健康检查并恢复 Cookie Session；回到前台时重新确认会话。
- app flow 对前序操作执行取消并拒绝陈旧结果，避免连接、profile 切换和会话恢复相互覆盖。
- 服务端确认注销成功后才进入 signed-out；注销失败时保持 authenticated/stale 状态并显示 warning。
- 已加入 Router 与 app-flow 的聚合测试入口。

### 共享 UI、布局与国际化

- 已加入 Safe Area、状态栏、系统明暗主题和完整语义设计 token。
- 已建立可复用的文字、按钮、正式图标、图标按钮、文本字段、卡片、通知、加载状态、页面脚手架和独立应用 surface。
- 已加入 compact 底部导航和 expanded 侧栏，按窗口宽度适配手机和平板。
- 已建立 Mobile 独立 `zh-CN` / `en-US` catalog、provider 和 catalog 完整性检查。
- 共享交互组件覆盖字体缩放、触控目标、loading/disabled 状态和 accessibility 属性。

### B2：登录与会话（实现完成，设备验收未完成）

- Cookie Session adapter 已覆盖 setup status、login、`/api/auth/me` 和 logout 契约。
- 启动/前台会话恢复、无会话状态、恢复失败 warning、操作取消和服务端确认注销框架已完成。
- 注销失败不会伪装成成功，也不会提前丢弃当前会话。
- 登录 route 已接入邮箱/密码表单、持久标签、自动填充语义、字段校验、密码显示切换、提交取消和稳定错误映射。
- 登录取消会中止当前请求并拒绝迟到结果；服务端拒绝会回到可恢复的 signed-out 状态。
- 账号停用真实服务验收、401 全链路导航、服务器切换后的会话/缓存清理验收，以及 iOS/Android 真机 Cookie 生命周期仍待完成。

### 工程与 CI

- Expo SDK 57 依赖已对齐当前兼容补丁版本。
- Mobile CI 监听 backend reader/auth/library/media、共享认证与 HTTP contracts、OpenAPI exporter、`reader-core` 和 Mobile 生成器变化。
- CI 显式运行 `reader-core` typecheck、`api:check`、Mobile `check`、聚合单元/UI/Expo Router 测试、`i18n:check`、`doctor` 和 Android/iOS `export:check`。

### 本轮最终验证结果

- `reader-core` typecheck：通过；
- Mobile `api:check` 和 lint：通过；
- production、unit、UI TypeScript typecheck：全部通过；
- Node 测试：117/117 通过；
- Jest 原生 UI/Expo Router 测试：13 个 suite、26/26 通过；
- i18n catalog 检查：5/5 通过；
- Expo Doctor：20/20 通过；
- Android 和 iOS export：全部通过。
- Android release APK 已构建并替换安装到 `Shuku_API_36`（API 36）模拟器；版本 `0.5.2`、冷启动和前台 Activity 已确认，崩溃日志为空。

当前环境已完成 Android API 36 模拟器 release 冷启动和服务器列表可见界面检查；仍未执行以下手工/真机场景：真机扫码、相机权限设置跳转、杀进程恢复、Cookie 前后台恢复、真实注销、LAN HTTP、HTTPS 和反向代理 base path 部署。相关实现与自动化边界测试通过不等于这些场景已完成真机或真实部署验证，后续仍须纳入设备与部署验收矩阵。

## 当前准确边界

- B1 已完成自动化质量门禁；上述真机、生命周期和真实部署场景仍未在当前环境执行。
- B2 登录表单、会话恢复、受保护路由和确认注销框架已完成；真实服务与真机 Cookie 生命周期仍待验收。
- 书库、搜索、筛选、书架、作品详情和 volume 选择尚未实现。
- Reader v3 只有生成契约、校验和 mapper，尚无 bootstrap client、Reader host 或实际渲染。
- 本地进度已完成，服务端 progress、reading-status、bookmarks 和持久 outbox 尚未接入。
- schema 4 偏好 model 已由 `reader-core` 提供，但移动端偏好 repository 和设置 UI 尚未实现。
- 漫画、可重排格式、PDF、下载和音频 runtime 尚未实现。
- TestFlight、Google Play Internal Testing 和真机矩阵尚未开始。

## 下一阶段

按一个垂直切片一个 PR 推进：

1. 完成 401、账号停用、服务器切换清理及 iOS/Android 真机 Cookie 生命周期验证；
2. 在设备与真实部署环境补充 B1 的扫码、权限跳转、杀进程恢复、Cookie 生命周期、注销、LAN HTTP、HTTPS 和反向代理 base path 验收；
3. 建立只读 library API adapter 和 work/mediaVersion/volume 页面链路；
4. 从 volume 进入 Reader v3 bootstrap，完成 Reader host 与漫画首个垂直切片；
5. 接入服务端进度、阅读状态和书签，再建设可重排格式与 PDF runtime。

每一步同时完成 `zh-CN`、`en-US`、横竖屏、手机/平板、取消、错误状态和无障碍，不新增另一套服务端业务接口或历史移动数据兼容层。

## 验收门禁

```bash
pnpm --filter @shuku/reader-core typecheck
pnpm --filter @shuku/mobile api:check
pnpm --filter @shuku/mobile check
pnpm --filter @shuku/mobile test
pnpm --filter @shuku/mobile i18n:check
pnpm --filter @shuku/mobile run doctor
pnpm --filter @shuku/mobile export:check
```

聚合 `test` 会运行单元测试和 Jest 原生 UI/Expo Router 测试。若 backend reader/auth/library/media、共享认证/授权、HTTP contract 或 OpenAPI exporter 发生变化，必须重新执行 Mobile 契约检查。B1 已依据本轮最终自动化结果关闭；真机与真实部署场景继续按上文边界单独验收。
