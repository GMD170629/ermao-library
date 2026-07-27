# Python Backend Runtime

Shuku Starship now uses Python as the backend runtime. The Next.js app is only the React frontend and an internal `/api/*` rewrite target.

## Runtime Boundaries

- Frontend: `apps/web` renders pages and calls `/api/...`.
- API: `apps/api-python/app/main.py` serves all public API routes through FastAPI.
- Worker: `apps/api-python/app/worker` handles monitor-folder importing.
- Database schema initialization is owned by Python API/Worker startup via Alembic; there is no separate migrator container.
- Next.js API route handlers under `apps/web/app/api` have been removed.
- TypeScript scanner/import/organize backend code under `packages/scanner` has been removed.

```mermaid
flowchart LR
  Browser["Browser / PWA"] --> Web["Next.js frontend"]
  Web --> Api["Python FastAPI API"]
  Worker["Python worker"] --> DB["SQLite"]
  Api --> DB
  Api --> Storage["STORAGE_ROOT"]
  Worker --> Storage
  Worker --> Monitor["/monitor"]
```

## SQLite schema migrations (Alembic)

- Authority: Alembic revisions under `apps/api-python/app/db/alembic/versions/`. The squashed baseline is `28bd57c8f2a9` (`baseline_v14`), matching the former `PRAGMA user_version = 14` target schema.
- Startup path (`app/db/bootstrap.py` → `app/db/runner.py`):
  - empty DB → `alembic upgrade head`
  - existing DB with `alembic_version` → `upgrade head`
  - pre-Alembic DB with `user_version == 14` → stamp head (no DDL replay)
  - complete test DB created from `Base.metadata` → stamp head
  - any other populated DB, including `user_version < 14` → reject as unsupported
- `app/db/seed.py` only inserts missing baseline records: `systemName`, `language`, `workDetail.tabOrder`, and the three built-in metadata Sources. It never overwrites existing records, runs historical backfills, repairs business state, or writes migration markers.
- Timestamp normalization triggers are ensured after every schema apply (`app/db/timestamp_triggers.py`). Table and column discovery uses SQLAlchemy Inspector. SQLite has no SQLAlchemy schema construct for triggers, so the final `CREATE/DROP TRIGGER` DDL is a narrow dialect-specific exception owned by DB bootstrap; remove it once every non-legacy timestamp writer uses typed SQLAlchemy ORM/expression APIs.
- Backup archives remain format version 2 and include `databaseRevision`. Restore is allowed only when that value equals the current Alembic head; archives without the field and archives from another revision remain listable/downloadable but fail before clearing data with `BACKUP_DATABASE_REVISION_UNSUPPORTED`.
- The minimum supported pre-Alembic database is v14. Databases older than v14 must first be upgraded with an older application release.
- CLI: `python -m app.db.bootstrap` (same entry as before); Alembic config at `app/db/alembic.ini`.

## Verification

- `apps/api-python/tests/test_route_coverage.py` asserts that Next.js API routes are absent.
- `apps/web/lib/next-config-rewrites.test.ts` verifies that `/api/:path*` is rewritten to `http://127.0.0.1:8000`.
- `scripts/verify-python-backend-migration.mjs` runs Python tests, runtime smokes, frontend typecheck/tests, and Compose topology checks.

## Operational Notes

- The unified `web` container starts Next.js, FastAPI, and the Python worker with `scripts/start-unified-app.sh`.
- Production Compose exposes only `web`; SQLite lives in the mounted storage directory.
- The public `/api/...` contract is owned by Python. New backend behavior should be added under `apps/api-python`, not `apps/web`.
