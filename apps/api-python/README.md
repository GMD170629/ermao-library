# 二毛图书 appv2 Python API

v0.4.0 后端只运行 `appv2`。它是基于 FastAPI、同步 SQLAlchemy 2、psycopg 3、Alembic 和 PostgreSQL 18 的全新实现，不导入旧 `app`，不提供旧 API，也不读取或迁移旧 SQLite。

生产 API 统一位于 `/api/v2`。OpenAPI 文档和健康检查分别为：

```text
/api/v2/docs
/api/v2/openapi.json
/api/v2/operations/health
```

## 本地运行

准备一个隔离的 PostgreSQL 18.x 数据库，然后执行：

```bash
cd apps/api-python
uv sync --extra dev --locked

export DATABASE_URL='postgresql+psycopg://shuku:password@127.0.0.1:5432/shuku_v2'
export SESSION_SECRET='replace-with-at-least-32-random-characters'
export STORAGE_ROOT="$PWD/.local-storage"
export MONITOR_ROOT="$PWD/.local-monitor"

uv run python -m appv2.entrypoints.migrate
uv run uvicorn appv2.entrypoints.api:app --host 0.0.0.0 --port 8000
```

另一个终端启动单实例调度 worker：

```bash
cd apps/api-python
uv run python -m appv2.entrypoints.worker
```

迁移入口会拒绝非 PostgreSQL 18.x 数据库。worker 使用 PostgreSQL advisory lock，第二个调度实例不会并行领取任务。

## 数据与文件

appv2 使用独立的 `${STORAGE_ROOT}/v2`：

```text
v2/
├── covers/
├── conversions/
├── temp/
├── backups/
├── control/
├── logs/
└── secrets/
```

旧 `storage/database/shuku.sqlite3` 和旧缓存不会被读取或修改。`MONITOR_ROOT` 可以指向已有读物目录，用户通过重新扫描建立全新的 PostgreSQL 书库。

本地密码重置通知写入 `v2/control`。重置令牌仅存哈希、限时有效且只能使用一次。

## 备份与恢复

备份由 worker 使用 PostgreSQL 18 `pg_dump --format=custom --no-owner --no-acl` 创建，并在 `v2/backups` 写入包含应用版本、PostgreSQL major、Alembic revision 和 SHA-256 的清单。

恢复只接受 v0.4.0 / PostgreSQL 18 的 appv2 归档。统一运行时的 supervisor 会停止 API 和 worker，执行单事务 `pg_restore`、运行 Alembic，再重启服务。Web 使用恢复任务 ID 跨越维护期轮询文件系统结果。数据库密码不会出现在 `pg_dump`/`pg_restore` 命令参数或持久化错误中。

## 质量与验收

```bash
cd apps/api-python
uv run ruff format --check appv2 tests
uv run ruff check appv2 tests
uv run mypy appv2
uv run pytest -q
```

仓库根目录可运行完整迁移门禁和运行时 smoke：

```bash
pnpm verify:python-backend
pnpm smoke:python-api
pnpm smoke:python-worker
pnpm smoke:python-worker-import
pnpm smoke:python-sample
```

设置 `APPV2_TEST_DATABASE_URL` 后，smoke 必须指向可清空的隔离 PostgreSQL 18 数据库。

## Docker

- `docker-compose.yml` / `docker-compose.prod.yml` 使用内置 `postgres:18.4-alpine3.23`，数据库不暴露宿主机端口。
- `docker-compose.external-db.yml` 不创建内置数据库，要求提供外部 PostgreSQL 18.x `DATABASE_URL`。
- 统一镜像只复制和安装 `appv2`，启动 Alembic、appv2 API、appv2 worker 和 Next.js Web。

```bash
POSTGRES_PASSWORD='replace-with-a-strong-password' docker compose up
```
