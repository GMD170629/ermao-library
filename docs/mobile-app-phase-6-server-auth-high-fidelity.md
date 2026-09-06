# 移动 App 第六阶段：当前服务器与认证流程

> 文件名沿用历史阶段编号；本文记录当前实现和可复用的高保真参考。状态、错误码和会话事实以 shared auth/servers 模块为准。

## 当前流程

`DefaultMobileRuntime` 的入口顺序是 profile 读取、服务器 probe、兼容性与 setup status、登录/首次设置、`/me` 验证，然后保存已验证会话并进入主 Shell。`AppSession` 区分无服务器、检查中、连接失败、TLS 风险、需要设置、设置失败、已登出、认证中、登录失败、账户停用、已认证和不兼容状态。

| 场景 | 当前行为 | 实现入口 |
|---|---|---|
| 首次使用 | 空服务器地址、账号和密码表单；点击登录时才探测并决定 Setup 或 Login | Android `bootstrap/ErmaoLibraryRoot.kt`、`features/auth`；iOS `Application/AppRootView.swift`、`Features/Auth/LoginView.swift` |
| 已保存 profile | 选择 profile 只回填地址和已保存账号；登录成功后更新 profile 名称为标准化 URL hostname | `MainViewModel`、iOS `SessionStore.swift`、`DefaultMobileRuntime` |
| 切换 | Server Center 的原生 Sheet 选择目标；只回填表单，不自动登录；成功切换激活目标并重置导航栈 | Android `features/servers`、iOS `Features/Server/ServerFlowView.swift` |
| 删除 | 当前 profile 通过确认 Dialog 删除；runtime 移除 profile、会话和 cookie，平台再清理本地凭据并清空表单 | `MainViewModel.deleteDisplayedServer`、`SessionStore.deleteSelectedLoginServer` |
| 登录失败 | 无效凭据、不可用、不兼容、TLS 风险、setup 冲突和账户停用分别显示稳定状态，保留可重试输入 | `AppSession`、两端 auth/server screens |
| 重新认证 | 服务端明确返回未授权时离开私有 Shell，进入带最近身份的重新认证表单；成功后按 namespace 恢复或重建 Shell | `DefaultMobileRuntime.refreshCurrentSession`、两端 root gate |

## TLS、错误与凭据

系统信任失败后才显示不安全 TLS 风险提示，用户选择取消或明确接受风险并连接。表单填写和切换不预先显示探测/证书配置。密码由平台安全存储管理；共享 runtime 负责 cookie 和 verified session。短暂网络错误不会把已认证用户当作登出，账户停用使用阻断页。

切换服务器只改变激活 profile 和导航；私有数据仍按 `serverIdentity + userId + authzVersion` 隔离。登出由平台协调器停止音频、等待下载取消并清理当前 namespace，再调用 runtime 移除会话/cookie；删除 profile 的合同只承诺移除 profile、会话和 cookie，不把它扩大为删除所有本地文件。

## 参考资产与平台边界

当前参考资产位于 `assets/mobile-app-hifi-v1`：[`server-login-empty-ios-app-light-v3.png`](assets/mobile-app-hifi-v1/server-login-empty-ios-app-light-v3.png)、[`server-login-saved-ios-app-light-v3.png`](assets/mobile-app-hifi-v1/server-login-saved-ios-app-light-v3.png)、[`server-switch-sheet-ios-app-light-v3.png`](assets/mobile-app-hifi-v1/server-switch-sheet-ios-app-light-v3.png)、[`server-delete-confirmation-ios-app-light-v3.png`](assets/mobile-app-hifi-v1/server-delete-confirmation-ios-app-light-v3.png)、[`server-unsafe-ssl-ios-app-light-v3.png`](assets/mobile-app-hifi-v1/server-unsafe-ssl-ios-app-light-v3.png) 及 Android saved/switch 图。PNG 只约束内容层级和操作语义；Sheet、Dialog、键盘、返回和系统错误样式使用原生 API。

首次设置、账户停用和重新认证资产同目录的 `auth-setup-app-light-v1.png`、`auth-account-disabled-app-light-v1.png`、`auth-reauthenticate-expired-app-light-v1.png` 可用于夹具。管理设置视觉板属于 `mobile-app-settings-native-v1`，只作能力分组参考；当前入口仍由 administrative settings capability 过滤。

所有文案支持 `zh-CN`/`en-US`，iOS/Android 共用状态语义但不强求系统控件同形。功能与视觉收口需覆盖真实设备的首次使用、已有 profile、切换、删除、TLS、Setup、重新认证和停用分支。
