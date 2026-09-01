# ADR 0005: SQL-only write transaction boundaries

- Status: Accepted
- Date: 2026-08-11

## Context

SQLite WAL allows readers to continue while a writer is active, but it still has one
database-wide writer slot. Several application paths acquired that slot and then ran
JSON/XML parsing, metadata normalization, filesystem inspection, hashing, network-facing
or response-mapping work. The most severe case was the metadata OPF `before_commit`
observer, which expanded writeback targets with N+1 queries and filesystem calls after
the originating use case had already flushed. Authentication GET requests could also
refresh sessions, and Reader GET requests could repair EPUB navigation, causing unrelated
read surfaces to compete for the same writer slot.

## Decision

All ordinary write use cases follow this sequence:

1. Read an explicit projection DTO and close the read session/transaction.
2. Perform validation, parsing, normalization, sorting, deduplication, hashing, and
   filesystem/network preparation outside a write transaction.
3. Construct an immutable capability-specific `Prepared*` value.
4. Open a short write unit of work containing only typed SQLAlchemy reads/writes, simple
   assignments from SQL results, and bounded iteration over preconstructed SQL chunks.
5. Commit before response mapping or external publication.

Set-based writes use a 900-bind-parameter budget. Background maintenance uses a separate
connection with a 500ms SQLite busy timeout and a 500ms budget measured from its first
DML statement. Busy work is deferred without dropping its persistent intent. Foreground
write intervals longer than 100ms emit a structured duration/outcome log without SQL or
payload content.

Session authentication GET requests are read-only. Sliding renewal is explicit through
`POST /api/auth/session/refresh`; `/api/auth/me` only indicates when renewal is advisable.
Reader bootstrap GET requests never repair persistent navigation.

Metadata-to-OPF propagation uses a durable preparation intent and leased CAS claims. No
SQLAlchemy flush/commit observer may perform or infer metadata writeback work. Every
metadata mutation must enqueue an explicit prepared intent in its own atomic state change.

Backup restore is the single long-write exception. Parsing and validation happen against
a temporary database first; applying the validated rows to the live database occurs under
a cross-process maintenance barrier in one SQL-only transaction so partial restore cannot
be exposed.

## Consequences

- A write transaction remains atomic, but no business or filesystem work may extend the
  database-wide SQLite writer interval.
- Application commands own commit/rollback. Repositories may flush for generated values
  but may not hide commit/rollback, and presentation/bootstrap/worker adapters do not own
  transaction control.
- New metadata mutation paths must use the explicit preparation port; relying on ORM dirty
  tracking is a correctness defect because typed bulk updates are intentionally invisible
  to ORM observers.
- Queue workers require owner/lease CAS semantics and recover only expired claims, enabling
  safe multi-process operation and restart.
