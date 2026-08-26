# ADR 0014: Parser-authoritative Reader opening

- Status: Accepted
- Date: 2026-08-15
- Scope: Authoritative Reader-opening eligibility and startup-conflict handling

## Context

Reader bootstrap is the online authorization and content-access entry point. It
also supplies EPUB navigation, remote comic pages, PDF title hints, and optional
progress. Clients had incorrectly turned its diagnostic fingerprint, artifact
version, declared byte length, comic page list, PDF page count, and progress state
into gates for opening an already downloaded file. A valid local publication could
therefore become unreadable even though the native parser could open it.

## Decision

Every authenticated online entry still requests Reader v4 bootstrap. Bootstrap
content access remains mandatory when bytes are not already local: remote comics
require their manifest and page API; remote PDF requires usable Range metadata or a
complete-file URL; reflowable content requires a file URL.

A completed local artifact is selected only by server/user/authorization namespace and
`bookId + resourceId + assetId`.
The native parser is authoritative for whether it can be read:

- EPUB uses Bootstrap navigation when available, locally retained navigation when the
  network request is unavailable,
  and fills gaps from the publication TOC.
- A local CBZ/ZIP is security-checked and indexed from its actual entries. Remote
  comics use only the Bootstrap page API and never synthesize a local archive.
- A local or fully downloaded PDF uses its parsed page count. Bootstrap page titles
  are optional index-based hints.

Content fingerprints, artifact versions, declared byte counts, and server/local
page-count equality remain diagnostics. They do not gate opening. Progress,
bookmarks, preferences, and synchronization initialize best-effort after content;
invalid progress starts at the beginning, and persistence failures never block the
Reader or its close action. Startup progress conflicts are resolved deterministically
without a blocking dialog.

For a damaged downloaded EPUB, CBZ/ZIP, or PDF, “download again and open” performs a
fresh Bootstrap and full-file request. Security and parser validation occur on a
temporary file. Publication succeeds before the old file is atomically replaced;
failure preserves the old download. Retrying a streamed comic refreshes Bootstrap,
the page manifest, and failed pages without downloading an archive. PDF Range retry
refreshes Bootstrap metadata and may fall back to a full-file download.

## Consequences

- Server metadata can evolve without taking a readable local book away from its user.
- A Bootstrap failure prevents remote-only reading but not an already downloaded
  publication.
- Navigation caches are scoped by server identity, user, Book, and ReadableResource; they are hints,
  never a substitute for parser safety checks.
- Download completion may still verify transfer integrity before publication. That
  transfer check is distinct from later Reader-entry eligibility.
