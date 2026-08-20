# 二毛图书 Python API

二毛图书的 Python FastAPI backend and import worker. Docker deployments run this service together with the Next.js frontend in the unified `web` image.

SQLite is the only database. It is created automatically at `STORAGE_ROOT/database/shuku.sqlite3`; no database connection settings are required.

Text ebook imports preserve EPUB, MOBI, AZW, AZW3, PRC, FB2, and TXT in their source format. Supported source formats are parsed and opened directly; the import queue does not create a derived EPUB file.

Comic imports support CBZ/ZIP and single-volume, unencrypted CBR/RAR archives. The container images install `unar` automatically. For local CBR/RAR development, install a decompressor supported by `rarfile` (`unrar`, `unar`, `7z`, or `bsdtar`) and make sure it is available on `PATH`.

## Local setup

```bash
cd apps/api-python
uv sync --extra dev
cp .env.example .env
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/api/health
```

## 本地文件重置密码

在登录页申请重置密码后，应用会在第一个可写书库根目录创建 `reset-password.html`；如果没有配置可写书库根目录，则写入应用存储目录的 `password-reset` 子目录。打开文件并点击其中的链接即可设置新密码。重置令牌仅保存哈希，30 分钟失效且只能使用一次。

Backups are manual. Use the settings page or `POST /api/backups` to create a backup archive. Backup archives include system settings and database data, but exclude reader content files and cover image files.

SMTP and Kindle recipient settings are managed in the Web app under `/settings/email`. The Kindle sender runs as an API background queue and can be controlled with `KINDLE_SEND_QUEUE_ENABLED` and `KINDLE_SEND_QUEUE_INTERVAL_SECONDS`.

Run the Python import worker:

```bash
python -m app.worker.main
```

## Tests

```bash
uv run --extra dev pytest -q
```

Full migration gate from the repository root:

```bash
pnpm verify:python-backend
```

Runtime smoke from the repository root:

```bash
pnpm smoke:python-api
pnpm smoke:python-worker
pnpm smoke:python-worker-import
pnpm smoke:python-sample
PYTHON_REAL_LIBRARY_SAMPLE_DIR=/path/to/books pnpm smoke:python-real-library
```

## Unified Docker runtime

The Next.js app permanently rewrites `/api/:path*` to the local Python API process on `127.0.0.1:8000` inside the same container. The unified app startup script launches:

- `uvicorn app.main:app`
- `python -m app.worker.main`
- `node apps/web/server.js`

```bash
docker compose up --build
```

The public API and all database initialization are owned by the Python runtime.
