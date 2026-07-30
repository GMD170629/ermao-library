# 二毛图书（ermao-books）

[English](README.en.md) | 简体中文

二毛图书是一套面向个人与家庭的自托管数字书库，用于整理 NAS、家庭服务器或本地硬盘中的电子书、PDF、漫画和有声书。它提供文件导入与自动转换、书库检索、元数据整理、在线阅读与音频播放、阅读进度同步、Kindle 发送和数据备份等能力。

书库数据库、账户、阅读进度和系统设置都保存在自己的设备上；原始读物继续保留在指定目录中，不依赖第三方云端托管。

## 交流与反馈

- QQ 交流群：`154560969`

## 功能介绍

### 书库管理

- 上传读物或监控指定文件夹，自动发现并导入新文件。
- 按标题、作者、类型、格式、标签、系列和阅读状态搜索筛选。
- 使用自定义书架、阅读状态和系列管理个人藏书。
- 自动识别书名、作者、封面、章节和卷册，也可手动修改或智能补全信息。

### 阅读与收听

- 在线阅读 EPUB、PDF 和漫画，支持目录跳转、显示设置及多种翻页方式。
- 播放单文件或分轨有声书，支持章节切换、倍速、快进、音量和睡眠定时。
- 自动保存阅读与收听进度，并在不同设备间同步。

### 导入与整理

- 支持电子书、PDF、漫画和有声书，常见文本电子书可自动转换后入库。
- 查看导入进度和失败原因，支持搜索、筛选、重试、重新扫描和批量清理。
- 自动识别重复文件、不同版本和连续卷册，提供待整理项目和元数据建议。

### Kindle

- 将 EPUB 或 PDF 发送到 Kindle，并查看发送状态。

### 账户与数据

- 支持账户资料与密码管理、数据库备份和恢复。
- 提供导入、Kindle 发送记录和系统日志。
- 适配桌面和移动设备，并可安装为 PWA。

## 支持格式

- 电子书：EPUB、MOBI、AZW、AZW3、PRC、FB2、TXT
- 文档：PDF
- 漫画：CBZ、ZIP 图片包
- 有声书：M4B、M4A、MP3

不支持带 DRM 的 Kindle 文件。

## Docker Compose 安装（推荐）

生产镜像同时支持 `linux/amd64` 和 `linux/arm64`，Docker 会根据设备架构自动拉取对应镜像。发布与根 `package.json` 匹配的最新版本标签时，会同步更新版本镜像、`gamersgu/shuku-starship-web:prod` 和 `gamersgu/shuku-starship-web:latest`。复制下面的完整内容，粘贴到 NAS 的 Docker Compose 管理器中，或保存为 `compose.yaml` 后部署：

```yaml
name: ermao-books

services:
  web:
    image: gamersgu/shuku-starship-web:prod
    pull_policy: always
    container_name: shuku-prod-web
    restart: unless-stopped
    user: "${PUID:-1000}:${PGID:-1000}"
    environment:
      STORAGE_ROOT: /app/storage
      MONITOR_ROOT: /monitor
      PORT: 3000
      HOSTNAME: 0.0.0.0
    ports:
      - "${WEB_PORT:-3000}:3000"
    volumes:
      - ${STORAGE_PATH:-./data/storage}:/app/storage
      - ${MONITOR_HOST_PATH:-./monitor}:/monitor
    command: ["./scripts/start-unified-app.sh"]
    healthcheck:
      test: ["CMD-SHELL", "node -e \"fetch('http://127.0.0.1:3000/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))\""]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 30s
```

命令行部署时，在 `compose.yaml` 所在目录执行：

```bash
docker compose up -d
```

安装完成后访问 `http://服务器地址:3000`。

默认情况下：

- 宿主机 `./monitor` 挂载到容器 `/monitor`，用于保存和监控原始读物。
- 宿主机 `./data/storage` 挂载到容器 `/app/storage`，用于保存 SQLite 数据库、派生 EPUB、封面缓存、日志和会话密钥。
- Web 端口为 `3000`，容器以宿主机用户 `1000:1000` 运行。

可通过 `MONITOR_HOST_PATH`、`STORAGE_PATH`、`WEB_PORT`、`PUID` 和 `PGID` 修改这些默认值。`PUID`/`PGID` 对应的宿主机用户必须能读写书库目录与数据目录。

更新生产镜像：

```bash
docker compose pull
docker compose up -d
```

更新或重建容器不会清空已挂载的书库和数据目录。

## 首次使用

1. 打开系统并根据向导创建初始管理账户。
2. 在向导中添加 `/monitor` 或其子目录作为监控文件夹，也可以稍后进入“设置 → 书库来源与导入”配置。
3. 将读物放入对应宿主机目录，或在“全部图书”页面上传电子书、漫画或有声书文件。
4. 在导入任务中查看解析或转换进度；完成后进入书库阅读或收听。
5. 按需在“智能整理”配置豆瓣、Bangumi 或 AI 元数据来源。
6. 如需发送到 Kindle，在“邮件与 Kindle”中配置 SMTP 与 Kindle 邮箱。

## 本地开发

运行时环境为 Node.js 20.20.2、pnpm 9.12.2 和 Python 3.11.15。Node 版本记录在 `.nvmrc`，后端 Python 版本记录在 `apps/api-python/.python-version`；`uv` 会自动安装或选择对应解释器。不要使用 Node 22 或 Python 3.12 运行项目测试。

```bash
pnpm install
cp .env.example .env
pnpm dev:test
```

默认访问地址为 `http://localhost:3000`。开发数据库为空时同样通过首次使用向导创建账户，不再提供默认账号和密码。

常用检查：

```bash
pnpm --filter @shuku/web typecheck
pnpm --filter @shuku/web build
cd apps/api-python && uv run --extra dev pytest -q
pnpm fnos:validate
```

## 运行架构

生产环境使用单个统一镜像，同时运行：

- Next.js Web（公开端口 `3000`）
- FastAPI API（容器内 `127.0.0.1:8000`）
- Python 导入/监控 Worker

Next.js 将 `/api/*` 转发到容器内的 FastAPI。SQLite 是当前唯一数据库，API 启动时负责 schema 初始化和升级。

## 技术栈

- Web：Next.js 14、React 18、TypeScript、Tailwind CSS
- API：Python、FastAPI、SQLAlchemy
- 数据库：SQLite
- 导入与转换：持久化 Python Worker、Watchdog、libmobi、EbookLib、lxml、Mutagen
- 阅读器与播放器：EPUB.js、PDF.js、自研漫画阅读适配器、HTML5 Audio
- 工程：pnpm Workspace、Turborepo、Playwright、Pytest
- 部署：Docker Compose、`linux/amd64` 与 `linux/arm64` 多架构镜像、PWA

## 更多文档

- [Python API、转换器与 Worker](apps/api-python/README.md)
- [fnOS 模板与本地构建](deploy/fnos/README.md)
