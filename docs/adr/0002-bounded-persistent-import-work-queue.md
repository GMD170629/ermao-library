# ADR 0002: Bounded persistent import work queue

## Status

Accepted — **scoped to the legacy production importer**.

Scope revision (2026-08-21, see [ADR 0018](0018-physical-source-tree-book-readable-resource-overlay.md)):

- This ADR’s complex persistent queue (lease, heartbeat, recovery, cancellation,
  priority, and the `ImportWorkItem` bridge) applies only to the current legacy
  production importer.
- The ADR 0018 target importer does **not** inherit lease, heartbeat, recovery,
  cancellation, priority, or WorkItem bridge semantics. It uses a single-consumer
  `LibraryImportTask` queue and ContinueImport only.
- After production switches to the target importer, the legacy queue is deleted
  with the legacy importer.

Historical decision text below is retained for the legacy system; it is not the
target-state import queue contract.

## Context

Library roots may contain 1.8 million directory entries. Building a complete
candidate list, retaining paths in process memory, or creating one timer per
candidate makes memory consumption proportional to the source tree and loses
scheduling state when the worker exits.

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

Periodic and manual requests create one deduplicated scan job for a complete
library root. The scanner does not consume per-file filesystem events and does
not reconcile vanished, inaccessible, or renamed paths.

Canonical absolute paths are hashed with SHA-256 for indexed deduplication.
The fresh database baseline writes those keys directly and has no historical
backfill or exact-path compatibility path.

## Consequences

Memory and active queue size remain bounded independently of total directory
size. Scans are observable, cancellable, recoverable, and asynchronous through
their own API contract. A crash may repeat filesystem reads and aggregate scan
counts restart from zero, but cannot require a 1.8-million-row scan snapshot.

Manual scan and rescan endpoints return `202 Accepted`. Clients must poll scan
jobs. Per-file discovery events are intentionally removed; only scan start,
bounded aggregate progress, completion, and sampled failures are recorded.
