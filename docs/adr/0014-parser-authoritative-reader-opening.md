# ADR 0014: Parser-authoritative Reader opening

Status: Accepted; safety decisions are owned by [ADR 0026](0026-versioned-reader-safety-policy-contract.md),
delivery by [ADR 0025](0025-reflowable-original-download-before-reading.md) and
progress by [ADR 0028](0028-reader-v5-opaque-position-report.md).

## Decision

Reader v5 opens an authorized `bookId + resourceId + assetId` from the verified
original. The format-specific parser or engine is authoritative for whether that
original can be read. Transfer integrity, exact asset version and storage length
are still required before an artifact is published. Once that artifact is
verified, server fingerprints, diagnostic versions, page-count hints and
presentation percentages do not become a second parser gate.

Reflowable resources are downloaded in complete original form and parsed locally;
comic resources use their bounded manifest/page contract; PDF uses its selected
PDFium or web delivery adapter. A local or downloaded artifact is never repaired
by packaging a derived EPUB, ZIP or unpacked directory. The active safety policy
must run at the publication/container boundary, and an unavailable parser or
platform defense is an `ENGINE_*` or `PLATFORM_*` outcome rather than a private
content rule or fallback.

Progress, bookmarks and settings initialize best-effort after content selection.
Missing progress may start at the beginning; an SDK-invalid saved Locator is an
explicit `LOCATION_RESTORE_FAILED` result and is not silently rewritten. Progress
persistence failure cannot prevent opening or closing the Reader. [ADR 0028] owns
opaque Locator synchronization and validation.

## Current evidence

The public surface is `apps/api-python/app/modules/reader/presentation/v5.py` and
the Web adapter validates `/api/reader/v5`. Native and Web adapters invoke their
format engines through the shared safety contract; no Reader path invokes a
legacy importer or derived-publication repair path.

## Consequences

Changing server metadata cannot make a readable local original unavailable.
Remote-only content still requires its authorized delivery endpoint, and an
actual parser, integrity, capacity or platform failure remains visible with its
stable error category.
