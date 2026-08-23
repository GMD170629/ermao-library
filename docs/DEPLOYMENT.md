# 真实数据部署说明

数据库为空时，Dashboard 显示 0，书库、导入任务和移动端显示 empty state。

## 生产启动

```bash
curl -fsSL https://raw.githubusercontent.com/GMD170629/ermao-library/main/docker-compose.prod.yml | docker compose -f - up -d
```

远端 Compose 直接拉取 `gamersgu/shuku-starship-web:prod`。统一容器内同时运行
Next.js Web、Python FastAPI API 和 Python Worker，不要求部署机安装 Node.js 或
pnpm。

默认把宿主机 `./library` 挂载到容器 `/libraries/books`。正式部署可通过 `.env`
覆盖：

- `LIBRARY_HOST_PATH`：默认书库根目录，默认 `./library`；
- `STORAGE_PATH`：SQLite、封面、日志与会话密钥，默认 `./data/storage`；
- `PUID` / `PGID`：容器进程使用的宿主机用户和用户组。

其他宿主机书库必须分别映射到独立容器路径，例如
`/srv/comics:/libraries/comics`。首次打开 Web 页面后，在路径树中添加
`/libraries/books` 或其他映射路径作为书库根目录，并为每个根目录选择平铺、卷册或
有声书组织方式。目录结构规则见[书库根目录结构](library-root-layout.md)。

## 数据库基线与初始化

SQLite 固定保存在 `STORAGE_ROOT/database/shuku.sqlite3`。Python API 启动时只创建或
验证当前数据库基线和基础 `SystemSetting`，不会生成默认管理员或示例书。本次目录拓扑
重构不提供旧数据库升级路径；部署时必须使用新的数据库文件，原始读物继续保留在书库根
目录中并重新扫描。

用户首次打开 Web 页面时通过向导创建唯一的初始管理账户并添加书库根目录，不需要管理员
环境变量。扫描器先按路径创建 Work、Version 与 Volume，再由导入队列解析元数据、封面、
章节和阅读资源。

## 权限与启动检查

`PUID` / `PGID` 必须能读写应用存储。只扫描和阅读的书库根目录可以只读；浏览器上传目标
必须可写。统一容器会检查 `STORAGE_ROOT` 和已配置书库根目录，`/api/system/health` 与
`/api/health` 返回结果。空数据库和空书库都是合法状态。
