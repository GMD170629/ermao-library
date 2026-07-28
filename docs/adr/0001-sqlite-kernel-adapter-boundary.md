# ADR 0001: SQLite kernel adapter boundary

## Status

Accepted.

## Decision

Runtime business persistence uses SQLAlchemy ORM models and typed expression
APIs. SQLite-specific operations that have no ORM equivalent are isolated to:

- `app/db/sqlite.py` for connection initialization PRAGMAs;
- `app/db/runner.py` for `user_version`, migration inspection and the SQLite
  online backup API;
- `app/db/timestamp_triggers.py` for timestamp-normalization trigger DDL.

These modules may use the SQLite DBAPI or dialect SQL only for the operations
listed above. They must not contain business queries or capability state
changes. Historical Alembic revisions remain immutable and are not runtime
application code.

## Consequences

Architecture tests reject textual SQL, raw cursors and runtime schema
reflection in capability code. New SQLite exceptions require a separate ADR,
focused database tests and an exact architecture-test allowlist change.

The timestamp triggers can be removed only after every supported writer uses
typed timestamp values and external/raw writers are no longer part of the
database contract. Online backup and connection PRAGMAs remain database-kernel
responsibilities.
