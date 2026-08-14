# ADR 0012: Publication owns reflowable navigation

- Status: Accepted
- Date: 2026-08-14

## Context

Reflowable imports and Reader Publication adapters previously produced navigation
independently. `LibraryReadingUnit` could therefore contain titles, hrefs and sort
orders which did not match the Publication opened by Readium. Exact Reader
locations were persisted correctly, but Work Detail could project the same href as
the wrong chapter because it consulted the import-time rows.

The affected source formats are EPUB, MOBI, AZW, AZW3, PRC, FB2 and TXT. They remain
the immutable library sources. ADR 0013 subsequently permits disposable EPUB render
artifacts, but those artifacts never own or generate the navigation projection.

## Decision

`NormalizedPublication.toc` is the only authoritative server-side chapter tree for
reflowable publications. Importers may inspect metadata and covers, but they do not
persist chapter navigation or chapter counts.

`LibraryReadingUnit` rows with `unitType = "chapter"` are a lazy projection of that
TOC. A successful projection is identified by the volume, selected source file,
original file hash, parser identifier and normalization identifier. A separate
cache-state row records successful empty TOCs. A changed source or generator
identity invalidates the projection.

The Work Detail navigation surface, the volume reading-units endpoint, Reader v4
bootstrap and the Publication manifest may each populate a missing projection.
Parsing happens outside the write transaction. Publication identity is rechecked
before an atomic chapter-row replacement so an obsolete parse cannot overwrite a
newer file.

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
  records a structured failure and retries on a later access. Publication endpoints
  keep their explicit unavailable/corrupt failure contract.
- EPUB Publication parsing must support both EPUB 3 Navigation Documents and EPUB 2
  NCX. FB2 receives a direct original-file Publication adapter; this decision does
  not add FB2 navigator support to Web, Android or iOS clients.
- The historical EPUB navigation repair worker and import-time chapter writers have
  no remaining ownership and are removed.
