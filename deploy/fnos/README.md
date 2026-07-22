# fnOS 应用包

这个目录是二毛图书的 fnOS Docker 应用模板。它与仓库根目录的原生 Docker Compose 部署相互独立，二者使用同一个生产镜像。fnOS 包通过独立宿主端口提供 Web 服务，不注册统一网关路径或 Unix Socket。

应用开发者与发布者均为“六面体”，项目主页为 [GMD170629/ermao-library](https://github.com/GMD170629/ermao-library)。二毛图书支持 EPUB、漫画、PDF、文本读物和有声书的导入、整理、检索与沉浸阅读，适合部署在家庭 NAS 上集中管理个人藏书并跨设备访问。

有声书支持单个 M4B、M4A、MP3 以及多分轨音频导入，提供章节与轨道切换、倍速、音量、睡眠定时、跨页面连续播放和独立进度同步。

- B 站使用视频：[BV1r2KA6FEfL](https://www.bilibili.com/video/BV1r2KA6FEfL/)
- QQ 交流群：`154560969`

## 构建

安装官方 `fnpack` 后，在仓库根目录运行：

```bash
pnpm fnos:build
```

产物生成在 `dist/fnos/`。版本默认读取根目录 `package.json`，包内镜像同步使用 `gamersgu/shuku-starship-web:<应用版本>`，例如版本 `0.2.0` 会引用 `gamersgu/shuku-starship-web:0.2.0`。构建脚本会检查版本化镜像引用、回调脚本语法、模板占位符、应用用户权限、共享数据目录、`/monitor` 挂载、独立端口入口、端口向导与范围校验、SQLite 持久化挂载和桌面图标资源。

GitHub Actions 会先构建并推送同版本的 Docker 镜像，再生成引用该镜像的 `.fpk`。正式发布版本时，同一次构建还会同步更新 `prod` 和 `latest` 镜像标签。Actions 页面中的 Artifact 会被 GitHub 固定包装成 ZIP，解压后是 `.fpk`。推送 `v*.*.*` 标签，或手动运行工作流并启用 `publish_release`，会把原始 `.fpk` 上传到 GitHub Releases，供 fnOS 直接下载和安装。

未安装 `fnpack` 时，可以只运行同步校验：

```bash
pnpm fnos:validate
```

第一版包声明为 `platform=x86`，因为当前生产镜像仅发布 `linux/amd64`。发布 ARM64 镜像并完成真机验证前，不应改为 `platform=all`。

## 访问方式

安装向导要求选择 `1024-65535` 范围内的 Web 端口，默认是 `3000`。fnOS 会把该宿主端口映射到容器的 `3000` 端口，并将桌面入口注册为浏览器 URL。例如 NAS 地址为 `192.168.1.10`、端口为 `3000` 时，入口会打开：

```text
http://192.168.1.10:3000/
```

入口不经过 fnOS 统一网关，也不依赖 fnOS 的登录态；首次打开应用时由页面向导创建管理账户并添加监控文件夹。安装后可以从 fnOS 应用设置修改端口。端口发生冲突时，应选择其他未占用端口后重新保存。

从旧的统一网关版本升级时，升级向导会要求确认独立访问端口。升级完成后，旧的 `/app/shuku-starship` 地址不再使用。

应用本身支持 PWA，但浏览器只允许 Service Worker 在 HTTPS 或 localhost 安全上下文中运行。直接通过 NAS 局域网 HTTP 地址访问不影响普通 Web 使用；如需安装 PWA、离线缓存等能力，请自行配置带证书的 HTTPS 反向代理，并把它转发到这里选择的独立端口。

## 数据位置

- SQLite、封面、索引、日志和会话密钥：`TRIM_PKGVAR/storage`
- 需要扫描的原始读物：放入 fnOS 创建的 `/shuku.monitor` 共享目录，该目录整体挂载到 `/monitor`

fnOS 会自动为专用应用用户授予共享目录所需的 ACL 权限。应用持久数据位于 `TRIM_PKGVAR/storage`，容器和生命周期脚本都使用同一个专用应用用户运行。

`config/resource` 声明稳定的 `shuku.monitor` 共享数据目录，fnOS 安装时自动创建为 `/shuku.monitor`，并通过 `TRIM_DATA_SHARE_PATHS` 注入 Compose。`manifest` 设置 `disable_authorization_path=true`，不再额外申请任意 NAS 目录访问权限。

fnOS 根据 `config/resource` 中的 `docker-project` 统一管理 Compose 项目的创建、启动、停止、升级和配置变更。生命周期回调只校验端口并以应用用户预创建持久化目录，不执行 `sudo` 或 `docker compose`，也不动态重写 Compose 文件。`cmd/main` 的 `start/stop` 交给应用中心处理，`status` 则通过 Compose 项目和服务标签准确判断 `web` 容器是否正在运行。

应用的生命周期脚本通过 `config/privilege` 以 `run-as=package` 模式运行，不使用 root 权限。权限模型参考 fnOS 官方的[应用权限文档](https://developer.fnnas.com/docs/core-concepts/privilege/)，共享目录声明参考[应用资源文档](https://developer.fnnas.com/docs/core-concepts/resource/)。

fnOS 安装向导只收集访问端口，端口通过 `wizard_port` 注入 Compose 并用于宿主机端口映射和桌面 URL。管理账户在首次打开 Web 页面时创建，构建、安装和配置回调均不依赖管理员邮箱或密码变量。

使用登录页的“忘记密码”后，应用会在 fnOS 共享书库目录中创建 `reset-password.html`。在文件管理器中打开该文件并点击链接，即可设置新密码。

安装完成后，在二毛图书设置页添加 `/monitor` 作为监控文件夹。应用会递归扫描放入 `/shuku.monitor` 共享目录的读物。

## 原生 Docker Compose

fnOS 模板不替代根目录的 `docker-compose.prod.yml`。普通 Linux/NAS 仍可按 README 中的方式使用 `docker compose` 部署，并继续使用 `PUID`、`PGID`、`MONITOR_HOST_PATH` 和 `STORAGE_PATH`。
