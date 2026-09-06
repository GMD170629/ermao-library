# ADR 0001: SQLite kernel adapter boundary

Status: Accepted

## Decision

Application persistence uses SQLAlchemy mapped models and typed SQLAlchemy
expression APIs. SQLite-specific work is confined to the database adapters:

- `apps/api-python/app/db/sqlite.py` owns connection PRAGMAs and SQLite engine setup;
- `apps/api-python/app/db/runner.py` owns Alembic inspection, schema prestart checks
  and the supported linear upgrade operation;
- `apps/api-python/app/db/alembic/versions/` owns immutable schema operations through
  SQLAlchemy/Alembic schema objects.

Capability code must not use the SQLite DBAPI, raw cursors, textual SQL or runtime
schema reflection. Database-kernel adapters must not contain business queries or
capability state changes. New exceptions require focused ADR and architecture-test
coverage.

## Current evidence

`app/db/sqlite.py` contains the connection PRAGMAs; `app/db/runner.py` performs
schema verification and upgrades; backup is an independent `backup` capability.
`tests/test_capability_architecture.py` guards the boundary. The runtime revision chain currently ends at
`0009_reader_v5_opaque_progress`.

## Consequences

SQLite tuning, backup and schema inspection remain explicit infrastructure
responsibilities. Business persistence stays portable at the application boundary,
while the small set of unavoidable SQLite operations remains visible and testable.
