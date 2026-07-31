# ADR 0002: Bounded persistent import work queue

## Status

Accepted.

## Context

Monitor folders may contain 1.8 million directory entries. Building a complete
candidate list, retaining paths in process memory, or creating one timer per
filesystem event makes memory consumption proportional to the source tree and
loses scheduling state when the worker exits.

Import history and directory-scan progress also have different lifecycle and
API requirements. Treating a directory scan as an import task would break the
existing import-task list and detail contracts.

## Decision

All executable import work is represented by `ImportWorkItem`. It is the single
persistent queue consumed by one worker and contains either a scan-job target
or an import-task target. Import work has higher priority than scan work.
Completed work items are deleted; business history remains in `ImportTask` and
`ImportScanJob`.

Directory discovery uses `os.scandir()` and a bounded iterator stack. A slice
stops after 5,000 entries, 500 candidates, or 250 milliseconds. It persists the
result in one short transaction, then yields to the queue. Scanning pauses when
2,000 import work items are active. A process restart discards iterator state
and idempotently rescans from the job root instead of persisting a directory
snapshot.

Filesystem events create or update persistent import work directly.
`availableAt` implements stability delay and debounce. When event volume reaches
the active-work high-water mark, events collapse into one scan job for the
monitor root.

Canonical absolute paths are hashed with SHA-256 for indexed deduplication.
Existing rows are backfilled in restart-safe pages; exact-path lookup remains
the compatibility path while a hash is absent.

## Consequences

Memory and active queue size remain bounded independently of total directory
size. Scans are observable, cancellable, recoverable, and asynchronous through
their own API contract. A crash may repeat filesystem reads and aggregate scan
counts restart from zero, but cannot require a 1.8-million-row scan snapshot.

Manual scan and rescan endpoints return `202 Accepted`. Clients must poll scan
jobs. Per-file discovery events are intentionally removed; only scan start,
bounded aggregate progress, completion, and sampled failures are recorded.
