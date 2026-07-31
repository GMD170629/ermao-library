# Ermao Books (ermao-books)

English | [简体中文](README.md)

Ermao Books is a self-hosted digital library for individuals and families. It helps organize ebooks, PDFs, comics, and audiobooks stored on a NAS, home server, or local drive. It provides file importing and automatic conversion, library search, metadata management, online reading and audio playback, reading progress synchronization, Send to Kindle, and data backup.

The library database, accounts, reading progress, and system settings remain on your own device. Original books stay in the directories you specify, with no dependency on third-party cloud hosting.

## Community and Feedback

- QQ group: `154560969`

## Features

### Library Management

- Upload books or monitor selected folders to discover and import new files automatically.
- Search and filter by title, author, media type, format, tag, series, and reading status.
- Organize your collection with custom shelves, reading statuses, and series.
- Automatically identify titles, authors, covers, chapters, and volumes, with support for manual editing and intelligent metadata completion.

### Reading and Listening

- Read EPUBs, PDFs, and comics online, with table-of-contents navigation, display settings, and multiple page-turning modes.
- Play single-file or multi-track audiobooks, with chapter navigation, playback speed, seeking, volume, and a sleep timer.
- Save reading and listening progress automatically and synchronize it across devices.

### Importing and Organization

- Support ebooks, PDFs, comics, and audiobooks, with automatic conversion of common text-based ebook formats during import.
- View import progress and failure reasons, and search, filter, retry, rescan, or clean up tasks in bulk.
- Automatically identify duplicate files, alternate editions, and consecutive volumes, with items requiring attention and metadata suggestions.

### Kindle

- Send EPUB or PDF files to Kindle and view delivery status.

### Accounts and Data

- Manage account profiles and passwords, and back up or restore the database.
- Review import activity, Kindle delivery history, and system logs.
- Use the responsive interface on desktop and mobile devices, or install it as a PWA.

## Supported Formats

- Ebooks: EPUB, MOBI, AZW, AZW3, PRC, FB2, TXT
- Documents: PDF
- Comics: CBZ, ZIP image archives
- Audiobooks: M4B, M4A, MP3

DRM-protected Kindle files are not supported.

## Docker Compose Installation (Recommended)

The production image supports both `linux/amd64` and `linux/arm64`. Docker automatically pulls the image for your device architecture. When the latest release tag matching the root `package.json` is published, the versioned image, `gamersgu/shuku-starship-web:prod`, and `gamersgu/shuku-starship-web:latest` are updated together. Copy the complete configuration below into your NAS Docker Compose manager, or save it as `compose.yaml` and deploy it:

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

For command-line deployment, run this in the directory containing `compose.yaml`:

```bash
docker compose up -d
```

When the installation is complete, open `http://your-server-address:3000`.

By default:

- The host directory `./monitor` is mounted at `/monitor` in the container for storing and monitoring original books.
- The host directory `./data/storage` is mounted at `/app/storage` in the container for the SQLite database, derived EPUB files, cover cache, logs, and session keys.
- The web port is `3000`, and the container runs as host user `1000:1000`.

You can change these defaults with `MONITOR_HOST_PATH`, `STORAGE_PATH`, `WEB_PORT`, `PUID`, and `PGID`. The host user represented by `PUID` and `PGID` must have read and write access to both the library and data directories.

To update the production image:

```bash
docker compose pull
docker compose up -d
```

Updating or rebuilding the container does not clear the mounted library and data directories.

## First-Time Setup

1. Open the application and follow the setup wizard to create the initial administrator account.
2. Add `/monitor` or one of its subdirectories as a watched folder in the wizard, or configure it later under **Settings → Library Sources and Import**.
3. Place books in the corresponding host directory, or upload ebook, comic, or audiobook files from the **All Books** page.
4. Track parsing or conversion progress in the import tasks. When processing is complete, open the library to read or listen.
5. Configure Douban, Bangumi, or AI metadata sources under **Smart Organization** as needed.
6. To send books to Kindle, configure SMTP and your Kindle email address under **Email and Kindle**.

## Local Development

The required runtimes are Node.js 22.23.1, pnpm 9.12.2, and Python 3.11.15. The Node.js version is recorded in `.nvmrc`, and the backend Python version is recorded in `apps/api-python/.python-version`; `uv` installs or selects the appropriate interpreter automatically. Do not run the project tests with another Node.js version or with Python 3.12.

```bash
pnpm install
cp .env.example .env
pnpm dev:test
```

The default URL is `http://localhost:3000`. When the development database is empty, create an account through the first-time setup wizard. Default credentials are no longer provided.

Common checks:

```bash
pnpm --filter @shuku/web typecheck
pnpm --filter @shuku/web build
cd apps/api-python && uv run --extra dev pytest -q
pnpm fnos:validate
```

## Runtime Architecture

Production uses a single unified image that runs:

- Next.js Web (public port `3000`)
- FastAPI API (container-internal address `127.0.0.1:8000`)
- Python import and monitoring worker

Next.js proxies `/api/*` to FastAPI inside the container. SQLite is currently the only supported database, and the API initializes and upgrades the schema at startup.

## Technology Stack

- Web: Next.js 14, React 18, TypeScript, Tailwind CSS
- API: Python, FastAPI, SQLAlchemy
- Database: SQLite
- Import and conversion: persistent Python worker, Watchdog, libmobi, EbookLib, lxml, Mutagen
- Readers and players: EPUB.js, PDF.js, custom comic reader adapter, HTML5 Audio
- Tooling: pnpm Workspace, Turborepo, Playwright, Pytest
- Deployment: Docker Compose, multi-architecture `linux/amd64` and `linux/arm64` images, PWA

## More Documentation

- [Python API, converters, and worker](apps/api-python/README.md)
- [fnOS template and local build](deploy/fnos/README.md)
