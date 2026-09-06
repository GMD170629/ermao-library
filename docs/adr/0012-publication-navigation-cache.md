# ADR 0012: Publication navigation projection

Status: Accepted for Library/detail projections; Reader delivery uses the local
Publication rules in [ADR 0025](0025-reflowable-original-download-before-reading.md)
and [ADR 0028](0028-reader-v5-opaque-position-report.md).

## Decision

`NormalizedPublication.toc` is the authoritative source for server-side
reflowable chapter projections. Import may read parser metadata, but it does not
invent chapter rows. `EnsurePublicationNavigation` parses the selected verified
asset and writes `ReadableResourceNavigationUnit` rows plus a
`LibraryResourceAssetNavigation` marker. The marker is keyed by `assetId` and
stores the successful chapter count, including zero for an empty TOC.

The projection is lazy and belongs only to the selected asset. A changed or
deleted asset invalidates its rows and marker; another asset cannot reuse them.
The Library/detail request resolves the current authorized resource, returns a
valid marker immediately, or parses and atomically replaces the projection. It
does not add a queue, polling contract, lock or publish-time version protocol.

Reader v5 does not use these rows to construct a reflowable Publication. It opens
the complete original through the client parser and derives its own reading order,
TOC and positions. Comic page and audio chapter rows are format-specific indexes,
not reflowable Publication projections.

## Current evidence

The application owner is
`apps/api-python/app/modules/publications/application/ensure_navigation.py`; the
cache and invalidation adapters are under
`apps/api-python/app/modules/library/infrastructure/`. Reader v5's
`ResourceReaderV5Service` returns no server units for reflowable resources, and
`docs/reader-chapter-consistency.md` records the shared chapter-core contract.

## Consequences

Library detail can provide deterministic chapter metadata without creating a
derived publication. Empty or failed parses remain distinguishable, and Reader
opening does not depend on server navigation availability.
