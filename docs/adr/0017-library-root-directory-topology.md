# ADR 0017: Library-root directory topology owns library structure

- Status: Accepted
- Date: 2026-08-20

## Context

The former import flow discovered files first and then inferred database structure from
titles, metadata, media kinds, duplicate candidates, and user-driven merge or transfer
operations. That made the database the structural source of truth and allowed filesystem
layout and Work/Version/Volume identity to diverge.

This refactor deliberately targets a fresh database. It does not migrate historical
library rows, preserve old import configuration, or retain compatibility aliases for the
retired grouping model.

## Decision

Each configured `Library` is a filesystem root with one organization mode. Its relative
paths are the sole structural input:

- `FLAT`: every supported publication file directly under the root is one Work with an
  implicit Version and one Volume;
- `VOLUMES`: `root/Work/Version/Volume.ext` maps each directory and file directly to the
  corresponding Work, Version, and Volume;
- `AUDIOBOOK`: a root audio file is a single Work/Volume; `root/Work/tracks...` is one
  multi-track Volume; `root/Work/Volume/tracks...` creates multiple Volumes under one
  implicit Version.

The topology scanner materializes Work, Version, and Volume rows before it enqueues import
tasks. Import use cases may inspect original files, populate metadata and reading units,
and publish covers, but they may not create alternative structural identity, infer sibling
membership, merge works, or move files. Format and media kind are Volume facts, not Version
identity.

All Reader and download paths use the original publication format. The system does not
create a derived EPUB, ZIP, or unpacked publication as a persisted fallback.

Watcher, periodic, and manual requests submit one deduplicated scan job for an entire enabled library
root. Persisted system settings control watching and the periodic interval;
`LIBRARY_SCAN_INTERVAL_MS` is only a compatibility fallback when no interval has been saved.
The bounded scanner handles
currently discovered candidates. Reconciliation for vanished,
unreadable, or user-renamed files and directories is outside this refactor. A future
capability must define those state transitions explicitly rather than adding them to import
heuristics.

## Consequences

- Users change structural identity by changing directory layout and rescanning a fresh
  library, not through database merge/split/transfer controls.
- Natural path ordering controls deterministic Work, Version, Volume, and audiobook-track
  order.
- An upload must land inside an enabled library root at a path valid for its organization
  mode; scanning, not upload metadata, binds it to topology.
- Database initialization uses the current linear Alembic head. Explicit supported revisions
  are upgraded; unversioned or unknown database layouts remain rejected.
- Internal names retained by stable external contracts do not grant the old grouping model
  any authority over library structure.
