# ADR 0004: Media-version singleton and volume resources

## Status

Accepted. This is a coordinated, breaking schema and API change.

## Context

The former `Work -> Edition -> Volume -> File` model used an edition both as a
media category and as a container for publication, file, import, and reading
state. Importing two resources of the same media kind could therefore create
two editions, and a repeated volume number could incorrectly become an
identity conflict. Reader and task APIs then depended on edition-level format
and progress fields that could not describe heterogeneous resources.

## Decision

The library model is `Work -> MediaVersion -> Volume -> File`.

- A media version means exactly one of `EBOOK`, `COMIC`, or `AUDIOBOOK`.
  `(workId, mediaKind)` is unique. PDF belongs to `EBOOK`.
- Every independently readable resource is a volume. `volumeIndex` is optional
  and non-unique; `volumeId` is the only stable identity. `sortOrder` is the
  explicit order and may be manually changed after import.
- Format, publication metadata, narrator, import state, cover, statistics,
  files, reading units, progress, bookmarks, jobs, and resource authorization
  are volume-scoped.
- EPUB, MOBI, AZW, AZW3, PRC, FB2, TXT, PDF, CBZ/ZIP, M4B/M4A, and MP3 remain
  directly readable. A converted EPUB is a separate derived volume linked by
  `derivedFromVolumeId`; source and derived volumes keep independent progress.
- A work or media version stores no numeric reading progress. Completion is a
  query projection: every visible, authorized volume must be 100 percent.
  Adding a visible volume can therefore make the projection incomplete again.
- Continue-reading selects the most recently used media version containing an
  unfinished volume, then its first unfinished volume by stable order. When all
  volumes are complete it returns the most recently read volume.
- Reader v3 and structural APIs use `volumeId`. Reader v2 and edition resource
  routes return a uniform HTTP 410 response; no business compatibility layer
  or edition aliases are retained.
- Import directory grouping and natural filename ordering follow the project
  Wiki. Audiobook `Disc`, `CD`, and `Disk` directories affect track ordering
  only and never create volumes.

## Migration and release consequences

The schema change uses immutable expand, backfill, and contract revisions.
Backfill merges all old editions with the same work and media kind into one
media version while preserving volume IDs, duplicate volume indexes, files,
progress, bookmarks, metadata, and jobs. Ambiguous legacy ownership is recorded
rather than discarded.

Database upgrade requires a pre-migration SQLite snapshot. Application backup
format v3 represents media versions and volume resources. Older application
backups are rejected before any destructive restore action and must be restored
with an old application before upgrading.

API, Web, Mobile, and database migrations are deployed together during a
maintenance window. Old services must not run against the contracted schema.
Rollback restores the pre-migration snapshot and starts the previous release.

## Consequences

Repeated or missing volume indexes no longer cause new media containers.
Different formats under one media kind can coexist without sharing reader
state. Aggregated library views must filter authorized volumes before deriving
visibility and completion. Existing code that treats an edition as a concrete
resource must be removed or rewritten against a volume-oriented public API.
