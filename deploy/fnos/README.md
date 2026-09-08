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

产物生成在 `dist/fnos/`。版本默认读取根目录 `package.json`，包内镜像同步使用 `gamersgu/shuku-starship-web:<应用版本>`，例如版本 `0.2.0` 会引用 `gamersgu/shuku-starship-web:0.2.0`。构建脚本会检查版本化镜像引用、回调脚本语法、模板占位符、应用用户权限、共享书库目录、`/libraries/books` 挂载、独立端口入口、端口向导与范围校验、SQLite 持久化挂载和桌面图标资源。

GitHub Actions 会先构建并推送同版本的 Docker 镜像，再生成引用该镜像的 `.fpk`。正式发布版本时，同一次构建还会同步更新 `prod` 和 `latest` 镜像标签。Actions 页面中的 Artifact 会被 GitHub 固定包装成 ZIP，解压后是 `.fpk`。推送 `v*.*.*` 标签，或手动运行工作流并启用 `publish_release`，会把原始 `.fpk` 上传到 GitHub Releases，供 fnOS 直接下载和安装。

未安装 `fnpack` 时，可以只运行同步校验：

```bash
pnpm fnos:validate
```

fnOS 包声明为 `platform=all`，安装时会根据设备架构拉取对应的 `linux/amd64` 或 `linux/arm64` 生产镜像。

## 访问方式

安装向导要求选择 `1024-65535` 范围内的 Web 端口，默认是 `3000`。fnOS 会把该宿主端口映射到容器的 `3000` 端口，并将桌面入口注册为浏览器 URL。例如 NAS 地址为 `192.168.1.10`、端口为 `3000` 时，入口会打开：

```text
http://192.168.1.10:3000/
```

入口不经过 fnOS 统一网关，也不依赖 fnOS 的登录态；首次打开应用时由页面向导创建管理账户并添加书库根目录。安装后可以从 fnOS 应用设置修改端口。端口发生冲突时，应选择其他未占用端口后重新保存。

安装和升级向导均提供“全新安装 / Fresh install”和“更新 / Update”，默认选择更新，并保留独立访问端口设置。fnOS 根据实际安装或升级操作选择对应向导，单选框不会改变系统生命周期。

从 `0.x` 升级到 `1.x` 必须选择全新安装，不能自动升级旧配置。选择更新后提交，前置脚本会展示原因并终止；重新执行安装并选择全新安装后才能继续。判断只使用 fnOS 提供的 `TRIM_OLD_APPVER` 和 `TRIM_APPVER`，不检查数据库、残留目录或其他版本来源。旧的 `/app/ermao-books` 地址不再使用。

Both installation and upgrade offer **Fresh install** and **Update**, defaulting to Update. Upgrading from `0.x` to `1.x` requires Fresh install. Selecting Update displays an error and stops the operation after submission. Compatibility is checked only against the versions provided by fnOS.

应用本身支持 PWA，但浏览器只允许 Service Worker 在 HTTPS 或 localhost 安全上下文中运行。直接通过 NAS 局域网 HTTP 地址访问不影响普通 Web 使用；如需安装 PWA、离线缓存等能力，请自行配置带证书的 HTTPS 反向代理，并把它转发到这里选择的独立端口。

## 数据位置

- SQLite、封面、索引、日志和会话密钥：`TRIM_PKGVAR/storage`
- 原始读物：按所选组织方式放入 fnOS 创建的 `/shuku.library` 共享目录，该目录整体挂载到 `/libraries/books`

fnOS 会自动为专用应用用户授予共享目录所需的 ACL 权限。应用持久数据位于 `TRIM_PKGVAR/storage`，容器和生命周期脚本都使用同一个专用应用用户运行。

**全新安装会直接清空 `TRIM_PKGVAR/storage` 内的全部内容（包括隐藏文件），不备份。** 账户、书库配置、阅读进度、封面、索引、日志和会话密钥都会重新初始化。保留 `storage` 目录本身，不清空 fnOS 的 `TRIM_PKGETC`，也不删除 `/shuku.library` 原始书库文件。清空后复用现有目录初始化逻辑，首次打开应用需重新创建管理员并添加书库。

**Fresh install permanently erases all contents of `TRIM_PKGVAR/storage`, including hidden files, without a backup.** Accounts, library settings, reading progress, covers, indexes, logs and session secrets are reset. The storage directory itself, fnOS `TRIM_PKGETC`, and original files in `/shuku.library` are retained. Create an administrator and add the library again after installation. Update adds no cleanup or data migration; existing port validation and directory preparation remain in place.

安装、升级前置脚本共用 `cmd/install-policy.sh` 的校验；两个完成回调在端口检查通过后调用同一策略执行清空，再调用 `prepare-storage.sh`。应用状态与清空前检查共用 `cmd/docker-runtime.sh` 的只读容器发现逻辑。只有在确认无活动应用容器后才允许清空；查询失败、容器仍活动、路径不合法或清空失败都会终止。清空失败可能已删除部分配置，不提供自动恢复。应用设置、普通启动和重启不会执行清空。

Both lifecycle entry points reuse one installation policy and the existing storage preparation script. Container status and reset checks share one read-only discovery implementation. Active containers, failed Docker queries, invalid paths or removal failures stop fresh installation. A removal failure may leave partially erased settings; there is no automatic recovery. Changing settings, starting or restarting the application never repeats the reset.

`config/resource` 声明稳定的 `shuku.library` 共享书库目录，fnOS 安装时自动创建为 `/shuku.library`，并通过 `TRIM_DATA_SHARE_PATHS` 注入 Compose。`manifest` 设置 `disable_authorization_path=true`，不再额外申请任意 NAS 目录访问权限。

fnOS 根据 `config/resource` 中的 `docker-project` 统一管理 Compose 项目的创建、启动、停止、升级和配置变更。生命周期回调校验端口、按安装方式处理应用数据，并以应用用户预创建持久化目录；全新安装前只读查询容器状态，不执行 `sudo` 或 `docker compose`，也不动态重写 Compose 文件。`cmd/main` 的 `start/stop` 交给应用中心处理，`status` 则通过 Compose 项目和服务标签准确判断 `web` 容器是否正在运行。Docker 查询失败时返回错误，不将查询失败当作容器已停止。

应用的生命周期脚本通过 `config/privilege` 以 `run-as=package` 模式运行，不使用 root 权限。权限模型参考 fnOS 官方的[应用权限文档](https://developer.fnnas.com/docs/core-concepts/privilege/)，共享目录声明参考[应用资源文档](https://developer.fnnas.com/docs/core-concepts/resource/)。

fnOS 安装及升级向导通过 `wizard_install_mode` 收集 `fresh` 或 `update`，并通过 `wizard_port` 收集端口。端口注入 Compose 并用于宿主机端口映射和桌面 URL。安装模式不进入应用设置向导。管理账户在首次打开 Web 页面时创建，构建、安装和配置回调均不依赖管理员邮箱或密码变量。

`pnpm fnos:validate` 会执行隔离临时目录中的安装行为测试，覆盖版本拦截、清空范围、书库保留、容器检查和失败终止。它不能替代 fnOS 实机验收：发布前还需确认两个向导、错误展示、旧容器停止与清空顺序，以及全新安装后的管理员初始化页面。

使用登录页的“忘记密码”后，应用会在 fnOS 共享书库目录中创建 `reset-password.html`。在文件管理器中打开该文件并点击链接，即可设置新密码。

安装完成后，在二毛图书设置页添加 `/libraries/books` 作为书库根目录并选择组织方式。扫描器会把 `/shuku.library` 中的目录结构直接解释为 Work、Version 和 Volume。

## 原生 Docker Compose

fnOS 模板不替代根目录的 `docker-compose.prod.yml`。普通 Linux/NAS 仍可按 README 中的方式使用 `docker compose` 部署，并使用 `PUID`、`PGID`、`LIBRARY_HOST_PATH` 和 `STORAGE_PATH`。
