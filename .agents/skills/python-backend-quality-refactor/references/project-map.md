# Backend Project Map

Use this map as orientation, then verify it against the current repository before acting.

## Runtime

- `apps/api-python/app/main.py`: FastAPI application factory, lifespan, middleware, and router mounting.
- `app/api/routes/`: HTTP adapters. `compat.py` is the principal legacy compatibility surface and largest decomposition target.
- `app/services/`: domain rules, queues, conversion, metadata, library management, health, backup, and scheduling.
- `app/worker/`: persistent import queue, watcher, importer, path security, and worker entry point.
- `app/db/`: SQLAlchemy engine/session, SQLite schema, bootstrap migrations, and data backfills.
- `app/core/`: settings, authentication, authorization, localization, and time representation.
- `app/models/`: SQLAlchemy models.
- `app/schemas/`: Pydantic request/response models and response envelope helpers.

## Data and Process Boundaries

- SQLite is the only database and lives under the configured storage root.
- The API and import worker are separate processes that coordinate through persistent state.
- The unified container also runs the Next.js application; `/api` compatibility affects the Web client.
- Imports combine database writes, filesystem publication, format conversion, metadata parsing, cover generation, and system events.
- Reader, authorization, backup/restore, upload, and monitored-folder paths are high-risk compatibility surfaces.

## Current Hotspots

Recalculate with `scripts/quality_snapshot.py`; do not assume these numbers stay current.

- `app/api/routes/compat.py`: routes plus authorization, SQL, mapping, files, media responses, and domain orchestration.
- `app/worker/importer.py`: multi-format import pipeline and persistence.
- `app/db/bootstrap.py`: sequential schema migrations and data repair/backfills.
- `app/api/routes/reader_v2.py`: reader HTTP surface and navigation behavior.
- `app/services/organize_service.py` and `library_management.py`: dense domain workflows.

## Preferred Dependency Direction

Use this as a target, not a reason for a flag-day rewrite:

`routes -> application/domain services -> focused persistence/filesystem adapters`

Core policy and schemas may be shared inward. Workers may call application services but route modules must not become reusable service layers. Keep process lifecycle and retry containment at the worker boundary.

## Compatibility Constraints

- Preserve response envelopes from `app/schemas/responses.py`.
- Preserve API path/method/status behavior required by Web callers and tests.
- Preserve multi-user authorization and monitor-folder scoping.
- Preserve timestamps and active-locale formatting contracts.
- Cover fresh SQLite creation plus supported upgrades before changing migrations.
- Preserve import idempotency, source retention, conversion provenance, and persistent queue recovery.
