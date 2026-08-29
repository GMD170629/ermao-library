# ADR 0012: Publication owns reflowable navigation

- Status: Accepted for import/Library projections; Reader delivery amended by ADR 0025
- Date: 2026-08-14

## Context

Reflowable imports and Reader Publication adapters previously produced navigation
independently. `LibraryReadingUnit` could therefore contain titles, hrefs and sort
orders which did not match the Publication opened by Readium. Exact Reader
locations were persisted correctly, but Work Detail could project the same href as
the wrong chapter because it consulted the import-time rows.

The affected source formats are EPUB, MOBI, AZW, AZW3, PRC, FB2 and TXT. They remain
the immutable library sources. Reader delivery exposes their parser-backed
Publication directly and never creates a derived reading package.

## Decision

`NormalizedPublication.toc` is the only authoritative server-side chapter tree for
reflowable publications. Importers may inspect metadata and covers, but they do not
persist chapter navigation or chapter counts.

`LibraryReadingUnit` rows with `unitType = "chapter"` are a lazy projection of that
TOC. A successful projection is identified by the volume, selected source file,
original file hash, parser identifier and normalization identifier. A separate
cache-state row records successful empty TOCs. A changed source or generator
identity invalidates the projection.

The Work Detail navigation surface and the volume reading-units endpoint may each
populate a missing server-side projection. Parsing happens outside the write
transaction. Publication identity is rechecked before an atomic chapter-row
replacement so an obsolete parse cannot overwrite a newer file.

ADR 0025 removes this projection from the Reader delivery path. Reflowable Reader
v4 bootstrap no longer populates or returns server navigation, and there is no
reflowable Publication manifest/positions/chapter HTTP surface. Each client derives
its Reader TOC, reading order and positions from the fully validated local original.

The flat compatibility projection uses deterministic pre-order traversal and keeps
the TOC path and depth in metadata. Public reading-unit routes and response fields
remain unchanged. Exact chapter presentation continues to resolve by Publication
href and fragment, never by percentage or by assuming a TOC index is a spine index.

Comic and PDF `page` rows and audiobook `audio_chapter` rows are not Publication TOC
projections and remain eager format-specific indexes.

## Consequences

- Existing reflowable chapter rows are cleared by migration and rebuilt on demand.
- `LibraryVolume.chapterCount` is `null` until a successful projection and is `0`
  for a successfully parsed Publication with no TOC entries.
- A detail projection remains available when parsing fails, returns no chapters,
  records a structured failure and retries on a later Library access. It does not
  affect Reader startup or local parsing failures.
- EPUB Publication parsing must support both EPUB 3 Navigation Documents and EPUB 2
  NCX. FB2 receives a direct original-file Publication adapter; this decision does
  not add FB2 navigator support to Web, Android or iOS clients.
- The historical EPUB navigation repair worker and import-time chapter writers have
  no remaining ownership and are removed.
