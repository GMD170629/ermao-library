# Mobile App 实施进度

> 更新时间：2026-07-30
> 当前阶段：基础设施初版完成，前端页面尚未开始

## 已完成

- 新增独立的 `apps/mobile` Expo SDK 57 工程，使用 Node.js 22、React Native 0.86、React 19 和严格 TypeScript。
- 新增独立 Mobile CI，在相关 PR 和 `develop` 推送中执行 reader-core 类型检查、Mobile 质量门禁及 Android/iOS bundle 导出。
- 配置 iOS、Android、iPhone、iPad 与 Android 平板目标，启用自动明暗主题、相机二维码权限和本地网络访问能力。
- 建立 capability-first 分层：`server-connection`、`reader-progress`、共享网络/文件边界和组合根。
- 支持手工输入或二维码载荷共用的服务器地址解析：
  - 远程地址要求 HTTPS；
  - HTTP 仅允许局域网、链路本地、mDNS 或无点本地主机名；
  - 拒绝设备回环、URL 凭据、查询参数、片段和不支持的 scheme；
  - 保留反向代理 base path。
- 使用现有 `GET /api/health` 验证后端身份和健康状态，并区分取消、超时、网络故障、不兼容响应、服务异常和本地保存失败。
- 将服务器配置与阅读进度写入 App 私有文档目录：
  - 临时文件写入；
  - 回读和运行时 schema 校验；
  - 原子移动发布；
  - 保留最新和上一份有效快照；
  - 最新快照损坏时回退；
  - 按目录串行化并发读写。
- 阅读进度覆盖 EPUB、漫画和 PDF 位置，按服务器配置、用户、作品、版本、分卷、内容指纹和阅读器类型隔离；本地恢复缓存按最近更新时间保留 128 个槽位，并通过最坏字段长度的 8 MiB 文件预算测试。
- 保留 Mobile 独立 React 类型解析门禁。Web 已升级到 Next.js 16 / React 19，Mobile 使用 Expo 对应的 React 19；两端不通过根 override 或兼容层强制依赖版本。

## 当前验证结果

- Mobile lint、严格类型检查与 React 类型隔离：通过。
- Mobile 单元测试：41 项通过。
- Expo SDK 依赖检查：通过。
- iOS 与 Android Metro/Hermes 导出：通过。
- 全仓 lint 与 typecheck：通过。
- Web 单元测试：213 项通过。
- Web `zh-CN` / `en-US` 消息校验：2777 条通过。
- Web Next.js 生产构建：通过。
- pnpm frozen-lockfile 安装：通过。

## 尚未开始

- 扫码相机页面和手工地址输入页面。
- 手机/平板自适应导航与视觉组件。
- 登录、书库、详情和阅读器页面。
- 服务端进度同步、离线 outbox、下载和音频能力。
- TestFlight、Google Play Internal Testing 与真机验收。

## 下一阶段

在不改变上述领域、应用和基础设施边界的前提下，先实现“连接服务器”手机/平板界面，再接入登录和书库只读页面。视觉层需同时完成 `zh-CN`、`en-US`、深色模式、动态字体、VoiceOver/TalkBack 和横竖屏适配。
