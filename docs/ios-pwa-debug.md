# iOS PWA 真机调试

本项目的 Web 端在 `apps/web` 下，PWA 的 service worker 只会在 production 环境注册。调试时按目标选择启动方式。

## 快速局域网调试

用于验证移动布局、触摸交互和普通页面日志：

```bash
pnpm dev:ios
```

这个命令会自动初始化 SQLite，并启动 Python API、Python Worker 和 Next Web，然后在终端打印 iPhone 可访问的局域网地址：

```text
http://<Mac局域网IP>:3000/?debug=1
```

## PWA / Service Worker 调试

用于验证添加到主屏幕、离线缓存、更新提示和 service worker 生命周期：

```bash
pnpm pwa:ios
```

这个命令会先构建 Web，再以 production 模式启动完整本地服务栈。这样 service worker 会注册，登录和其他 `/api/...` 请求也会被代理到本机 Python API。

iOS 真机访问局域网 HTTP 时，PWA 能力可能和真实安装场景不一致。推荐用 HTTPS 隧道把本机 3000 暴露出去：

```bash
cloudflared tunnel --url http://localhost:3000
```

在 iPhone Safari 打开隧道给出的 `https://...` 地址，加上调试参数：

```text
https://<tunnel-host>/?debug=1
```

再通过 Safari 分享菜单选择“添加到主屏幕”。从主屏幕启动后，调试面板会继续显示页面日志、网络状态、PWA 显示模式和 service worker 消息。

## 调试面板

打开方式：

```text
?debug=1
```

关闭方式：

```text
?debug=0
```

面板会持久记住开启状态。它会捕获：

- `console.log/info/warn/error`
- `window.error` 和未处理的 Promise rejection
- `online/offline` 与页面可见性变化
- service worker install、activate、skip waiting、缓存清理等消息

如果登录时看到“登录服务暂时不可用”，通常说明只启动了 Web，没有启动 Python API。请用根目录的 `pnpm dev:ios` 或 `pnpm pwa:ios`，不要只运行 `apps/web` 下的单独 Web 脚本。

## Safari Web Inspector

需要更完整的网络、存储和控制台信息时：

1. iPhone 打开 `设置 > Safari > 高级 > Web Inspector`。
2. Mac Safari 打开开发者功能。
3. 用 USB 连接 iPhone。
4. 在 Mac Safari 的 `Develop` 菜单中选择 iPhone 上的 Safari 页面或主屏幕 Web App。

如果只看到普通 Safari 页面，看不到主屏幕 Web App，先从主屏幕重新打开应用，再刷新 Mac Safari 的 `Develop` 菜单。
