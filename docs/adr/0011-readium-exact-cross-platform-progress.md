# ADR 0011: Cross-format exact Reader progress

Status: Superseded by ADR 0028
Date: 2026-08-14
Superseded: 2026-09-04

ADR 0028 replaces this decision in full. The former Reader v4 model used
morphology-specific locations, exactness proofs, server-side percentage
derivation, `baseRevision` conflicts, and compatible local progress documents.
None of those rules apply to Reader v5.

Reader v5 treats the reading engine Locator as an opaque JSON object and stores
an independent presentation snapshot. It uses fresh server and client storage,
does not read or migrate v4 data, and restores a position only by handing the
opaque Locator back to the active reading engine.

See [ADR 0028](0028-reader-v5-opaque-position-report.md) for the authoritative
protocol, persistence, synchronization, and restoration decision.
