# 网络与代理设置方案

状态：已实现并完成定向验证。最终镜像已在 NAS 隔离容器中验证，生产发布另行进行。

[「数据和系统 → 网络与代理」桌面设计稿](../design/outbound-proxy/desktop-v2.png)

## 功能范围

在 Web「设置 → 系统设置 → 数据和系统 → 网络与代理」新增服务器代理配置。系统管理员配置一条代理连接，协议可选 HTTP 或 SOCKS5，填写服务器地址、端口及可选用户名和密码。HTTP 代理支持通过 CONNECT 访问 HTTPS 目标。密码保存后仅显示是否已配置，支持保留、替换或清除。

系统通过域名匹配决定哪些服务器出站 HTTP/HTTPS 请求使用代理。版本更新、GitHub 和 Bangumi 是便于选择的域名预设，与自定义域名使用同一套匹配逻辑。浏览器打开外部网站时使用设备自己的网络，Docker 镜像拉取使用 Docker 的网络配置。

## 域名规则

| 界面选项 | 匹配范围 |
| --- | --- |
| 版本更新 | 覆盖 `raw.githubusercontent.com`、`github.com`、`ghcr.io`、`pkg-containers.githubusercontent.com`、`release-assets.githubusercontent.com`、`objects.githubusercontent.com` 等现有更新链路实际使用的域名。 |
| GitHub | `github.com`、`githubusercontent.com` 及其子域名。 |
| Bangumi | `bgm.tv`、`bangumi.tv`、`chii.in` 及其子域名。 |
| 自定义域名 | 每行一个域名。允许任意域名，包括自建服务和内网域名。 |

- 已选预设与自定义域名取并集，重复规则合并。关闭一个预设后，同一域名仍可能由其他规则命中。页面支持展开查看预设包含的域名。
- 规则匹配 URL 的目标主机名。输入 `example.com` 时匹配它本身及 `api.example.com`，不匹配 `notexample.com`。统一处理大小写、末尾根域点和国际化域名。
- 命中时使用应用内配置的代理，代理连接失败时返回对应错误。未命中时沿用部署原有的连接行为。
- 重定向经业务原有规则校验后，按新目标主机名重新匹配。同一请求链使用同一份配置，保存后的新请求读取新配置。

## 页面与操作

侧边栏使用现有「数据和系统」入口。页面标题下依次显示「备份与恢复」「空间管理」「网络与代理」，默认打开现有「备份与恢复」。三项复用与「智能整理」同款的 `SettingsTabs`，选中项用主题橙色文字与细下划线表示。空间管理与网络代理在各自页签显示内容。

1. 管理员打开「数据和系统」的「网络与代理」页签，选择 HTTP 或 SOCKS5，填写代理地址、端口及可选认证信息。
2. 勾选「版本更新」「GitHub」「Bangumi」，在「自定义域名」多行输入框中添加其他域名。表单提示域名及其子域名都会匹配。
3. 点击「测试连接」。服务器用当前表单配置测试，显示目标域名、命中的规则和连接结果。版本更新分别测试版本源和下载源。测试不会下载完整更新包、写入元数据或保存设置。
4. 点击「保存设置」。测试结果用于诊断，测试通过不是保存条件。API 和 Worker 的新请求无需重启即可使用新配置。

页面沿用现有设置中心、表单和按钮样式。桌面使用左侧导航，小屏表单纵向排列，页签沿用共用组件的换行行为。提供简体中文和英文文案，覆盖表单、测试进度、成功和错误状态。代理地址填服务器运行环境能访问的地址，Docker 中的 `127.0.0.1` 指容器自身。

## 实现思路与影响范围

- 系统设置保存代理连接与域名规则，复用既有系统管理权限。API 和 Worker 从同一来源按需读取代理配置，只读取出站请求所需的字段。代理凭据不由配置读取接口返回。
- 为项目自有服务器出站请求提供统一 HTTP 发送器，集中处理目标域名、连接方式和代理认证。业务调用方继续拥有请求内容、授权、超时、重试及错误处理。HTTP 和 SOCKS5 共用同一发送入口，若采用 HTTPX，将 SOCKS 支持纳入生产锁定依赖和离线安装包。
- 将 Web 版本列表与更新说明接入后端现有更新能力。官方列表、说明、发布附件、GHCR 认证与下载重定向都经统一发送器。保留现有更新源验证、流式读包及摘要校验。
- 迁移 Web API 和 Worker 的现有出站调用，包括元数据查询、数据源连接测试、远程封面预览与保存、HTTP 下载和反馈。自建元数据服务同样依其实际请求域名匹配。保留各调用已有的凭据、响应和重定向语义。
- 基于当前调用点粗估实现与定向验证约 6～10 个工作日。主要工作量在迁移存量 HTTP 请求，以及验证更新的多主机下载链路和后台任务。

## 验收重点

- 使用真实 HTTP 和 SOCKS5 测试代理验证命中、未命中、认证、连接失败及跨域重定向。确认预设叠加、自定义域名、子域名边界和保存后生效。
- 验证 Web 版更新列表和说明通过后端获取，GHCR 的认证及重定向后下载正确匹配。用慢响应验证更新包可提前消费并有界缓冲，保留既有校验。
- 验证 Bangumi 手动查询、Worker 自动查询、连接测试、封面预览与保存。选择受迁移影响的既有 HTTP 调用做定向回归。
- 检查系统管理权限、登录用户原有的版本信息读取能力、代理密码不回读、测试未保存草稿及双语界面。完成本地验证后，在 NAS 的实际容器网络中确认代理可达、更新准备和 Bangumi 链路。

NAS 隔离验收已通过 GitHub 版本列表和说明读取、GHCR 官方清单摘要校验及重定向后首块读取，以及 Bangumi 真实查询、封面预览和保存。候选镜像与官方最新版本均为 `1.6.3`，本次没有可从产品入口准备的更高版本。完整更新准备由本地集成测试覆盖。

## 现有代码入口

- [设置中心与导航](../../apps/web/features/settings/center/settings-secondary-nav.tsx)
- [数据和系统页面](../../apps/web/features/settings/center/data-system-settings-page.tsx)与[共用设置页签](../../apps/web/features/settings/center/settings-tabs.tsx)
- [Web 版本列表与说明请求](../../apps/web/features/updates/api/client.ts)
- [官方更新源](../../apps/api-python/app/modules/updates/infrastructure/official_source.py)与 [GHCR 下载](../../apps/api-python/app/modules/updates/infrastructure/ghcr_source.py)
- [Bangumi 查询](../../apps/api-python/app/services/organize_service.py)与[数据源连接测试](../../apps/api-python/app/services/metadata_provider_registry.py)
