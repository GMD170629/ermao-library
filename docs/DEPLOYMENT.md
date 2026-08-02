# 真实数据部署说明

数据库为空时，Dashboard 显示 0，书库、导入任务、移动端显示 empty state。

## 生产启动

```bash
curl -fsSL https://raw.githubusercontent.com/GMD170629/ermao-library/main/docker-compose.prod.yml | docker compose -f - up -d
```

生产发布后不需要在部署机下载代码，也不需要安装 Node.js / pnpm。远端 compose 会直接拉取 `gamersgu/shuku-starship-web:prod`；统一应用容器内同时运行 Next.js Web、Python FastAPI API 和 Python Worker，Python API 启动时自动初始化数据库 schema 和基础数据。

第一次试运行可以直接使用默认值启动；正式部署请通过 `.env` 或一行命令里的 `env ... sh -c 'curl ... | docker compose -f - up -d'` 覆盖：

- `MONITOR_HOST_PATH`
- `PUID` / `PGID`

`MONITOR_HOST_PATH` 是默认挂载到容器 `/monitor` 的宿主机或 NAS 读物目录，默认 `./monitor`。应用允许从路径树选择任意容器内可见且可读的目录；额外宿主机目录必须先通过 Compose `volumes` 映射，例如 `/srv/books:/libraries/books`、`/srv/comics:/libraries/comics`。只有保存到已启用监控文件夹范围内的文件才会自动识别入库，因此 `PUID` / `PGID` 需要对相应挂载拥有所需权限。会话密钥由容器首次启动时生成并保存在 `STORAGE_PATH` 下。

## 迁移与初始化

SQLite 固定保存在 `STORAGE_ROOT/database/shuku.sqlite3`。Python API 启动时自动创建数据库文件、完整表结构和基础 `SystemSetting`，但不会生成默认管理员或示例书。用户首次打开 Web 页面时由项目级向导创建唯一的初始管理账户并添加监控文件夹，不需要管理员环境变量。真实读物来自手动上传，或由 Worker 实时导入监控文件夹中的文件。

## 启动检查

统一应用容器会检查：

- `STORAGE_ROOT` 是否可写

`/api/system/health` 和 `/api/health` 会返回检查结果。数据库为空是合法状态。

## Mock 清理清单

- Dashboard 固定统计已改为 `/api/dashboard/summary`
- 继续阅读已改为 `/api/dashboard/continue-reading`
- 最近新增已改为 `/api/dashboard/recent-books`
- 系统状态已改为 `/api/dashboard/system-status` 和 `/api/system/health`
- 书库、书架、移动端列表已改为 `/api/works`
- 详情页已改为 `/api/works/[id]`
- 阅读器已改为 `/api/editions/[id]/file` 和 `/api/volumes/[id]/pages`
- 导入任务页使用真实 `ImportTask` 和 `ImportLog`
- 设置页使用 `MonitorFolder`、`SystemSetting`、真实 health 和真实阅读进度更新时间

## 验证结果

本次代码整理已完成静态 grep：

使用 `rg` 检查 mock 入口、固定统计和旧扫描入口。

运行时代码和部署配置中不再包含 mock 数据入口。

执行 `pnpm typecheck` 和 `pnpm acceptance` 完成最终验收。
