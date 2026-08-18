# ADR 0017: Filesystem-authoritative library topology

- Status: Proposed
- Date: 2026-08-17
- Owner: Catalog capability

When accepted for the current release, this ADR changes earlier decisions as follows:

| Earlier authority | Generation-2 treatment |
| --- | --- |
| ADR 0002 | Supersede the singleton `ImportWorkItem`, old import-history API, absolute-path deduplication, and queue stability-delay/debounce semantics. Preserve the 5,000-entry, 500-candidate, 250-ms slice limits, high-water backpressure, lease recovery, and restart-from-subtree-root behavior. |
| ADR 0003 | Supersede watcher debounce. Preserve one 10,000-track budget across an entire `AUDIOBOOK` Work, including all of its Volumes and transparent disc directories. |
| ADR 0004 and `docs/media-version-volume-upgrade.md` | Supersede the media-version topology and structural mutation decisions. |
| ADR 0008 and ADR 0015 | Preserve authorization-version invalidation, verified-session behavior, and the rule that transient network failure is not explicit revocation. Replace monitor-folder authorization with Library grants. |
| ADR 0010 | Supersede the single-file download manifest and Reader-v4 identity. Preserve private authorization namespaces, validated temporary storage, atomic publication, and bounded revocation for already stored bytes. |
| ADR 0011 | Preserve exact locator morphologies, `baseRevision`, idempotent `mutationId`, durable pending writes, conflict handling, and post-navigation verification. Replace `workId + volumeId` ownership with Volume ownership and bind mutations to `contentRevision`; audio file identity becomes `assetId`. |
| ADR 0016 | Preserve original source formats. A local multi-track publication is a set of unchanged original assets, never a derived archive or unpacked conversion artifact. |

The current Reader authority will replace the previous Reader identity,
bootstrap, storage-key, and single-file download sections of
`docs/mobile-reader-architecture.md` before cutover. Its security, parser,
source-preservation, exact-location, and physical-device requirements remain in
force unless this ADR explicitly changes them.

## Context

The current system treats a monitor folder as an import source and then infers a
catalog structure from filenames, parent directories, embedded metadata, media
classification, and optional recognition results. A media version is a singleton
`EBOOK`, `COMIC`, or `AUDIOBOOK` bucket, and structural commands may merge, split,
reclassify, reorder, or move volumes without making the corresponding source-tree
change.

The target product has a different invariant: a user creates a **library** and
chooses one filesystem organization mode. The source tree, not recognition, is
the authority for work, version, and volume membership. Metadata may describe a
node but must never regroup it. The system no longer exposes catalog-only
structural mutations.

This is a greenfield data generation. In-place upgrade from a previous
installation is `UNSUPPORTED/UNSPECIFIED`: it is not implemented, tested, or
promised to return an error, migrate data, or happen to work. Server, Web,
Android, and iOS start with current empty state. Source directories are external
inputs and are not managed by the installation flow.

## Decision

### 1. Separate topology from reading capability

The canonical catalog is:

```text
CatalogLibrary -> LibraryWork -> WorkVersion -> LibraryVolume -> VolumeAsset[]
```

- `CatalogLibrary.organizationMode` is exactly `FLAT`, `VOLUMES`, or
  `AUDIOBOOK`. It only selects a directory grammar.
- `WorkVersion` is an implicit node or a user-named second-level directory. It
  is never a media-kind bucket.
- `LibraryVolume` is the smallest independently opened, downloaded, and
  progress-scoped catalog resource. It can contain one source file or an ordered
  set of original audio assets.
- `VolumeAsset.sourceFormat`, and the volume's derived `readingMorphology` and
  delivery capabilities, are technical facts required by parsers and clients.
  They do not classify the work and do not affect its parentage. Platform engine
  capability remains a client-side decision.
- No catalog table or public contract contains `mediaKind`, `organized`,
  `organizeStatus`, or a recognition-derived merge key.

`AUDIOBOOK` therefore means “apply the multi-file audio directory grammar”; it
does not mean that the work belongs to an audiobook product category. Audio
files are also legal in `FLAT` and `VOLUMES` when they satisfy those modes'
grammar.

### 2. Use a versioned, strict directory grammar

Every library records `topologyVersion = 1`. Changing a grammar later requires
a new topology version and an explicit decision; scanners never silently change
interpretation after an application update.

Common rules:

1. The root is resolved and canonicalized during preflight. Two library roots
   may not be equal, nested, or overlap after resolution. Create and relocate
   acquire one cross-process database root-registry lease with a monotonic
   fencing token and repeat the overlap check while holding it; an in-process
   mutex is not sufficient.
2. Traversal does not follow child symlinks or junctions. A link is a diagnostic,
   not a second route into the source tree. Hard-linked files at two relative
   paths are two catalog resources because topology is path-authored.
3. Relative paths are normalized to `/` separators and Unicode NFC for
   comparison. Original names are preserved for display. Each library records
   an explicitly confirmed `SENSITIVE` or `INSENSITIVE` path-comparison policy;
   case folding is applied only for an insensitive library. The system may use
   non-destructive mount evidence but never writes probe files to a read-only
   root. An ambiguous mount requires administrator confirmation.
4. A normalized-path collision is a hard error for the smallest affected
   topology unit. The scanner never picks one entry nondeterministically.
5. Ordering tokenizes ASCII digit runs and compares them as base-10 integers,
   then compares NFC Unicode code points and finally the UTF-8 encoding of the
   preserved name. It never uses the host locale. Undecodable path names produce
   `PATH_NAME_UNSUPPORTED`. There is no persisted manual structural order.
6. Known operating-system noise is ignored by an explicit allowlist. Other
   hidden files are not ignored merely because they are hidden. User ignore
   rules are root-relative, validated, and evaluated before descent.
7. Unsupported ordinary files do not create catalog nodes. Recognized sidecars
   may attach metadata or artwork but cannot create or regroup works, versions,
   or volumes.
8. A stable layout violation creates a structured diagnostic. There is no
   fallback to filename, sibling, metadata, or AI grouping.
9. `topologyVersion` freezes the admitted primary formats, sidecar roles,
   bundle adapters, transparent-disc grammar, and ordering policy. Adding a
   format or adapter that would turn an existing ignored path into a structural
   node requires a new topology version.
10. Empty or sidecar-only directories do not create catalog Works, Versions, or
    Volumes. A newly discovered invalid unit creates diagnostics and source
    observations, not an empty catalog shell. A previously valid node that
    becomes invalid retains its opaque ID in an invalid, normally hidden state.

#### `FLAT`

```text
<library>/
  book-a.epub
  book-b.pdf
  recording.m4b
```

- Every supported root-level file creates one work, one implicit version, one
  volume, and one primary asset.
- Every non-ignored root-level directory is invalid with
  `FLAT_NESTING_NOT_ALLOWED`; the scanner does not need to inspect its contents
  before reaching that deterministic result.
- Files with the same stem and different extensions are distinct works. The
  mode has no structural evidence that they are versions or renditions of one
  work.
- A root-level audio file is one single-file volume. Multi-track audio must use
  `AUDIOBOOK`, or an explicit audio bundle directory under `VOLUMES`.

#### `VOLUMES`

```text
<library>/
  <work>/
    <version>/
      volume-01.epub
      volume-02.pdf
      <audio-volume>/
        track-01.mp3
        track-02.mp3
```

- The first-level directory is a work.
- The second-level directory is a required, explicit version.
- Every supported file directly below a version is one single-file volume.
- A directory directly below a version is one bundled-volume boundary only if
  a registered bundle adapter validates the complete directory. Topology
  version 1 initially permits ordered audio bundles; it does not treat an
  arbitrary directory as a comic or publication.
- The audio bundle adapter permits direct tracks plus the same transparent
  `Disc|CD|Disk` directories defined below; any other nested directory or
  readable non-audio publication makes the bundle ambiguous/invalid.
- One `VOLUMES` audio bundle may contain at most 10,000 tracks.
- Each publication file directly below a work is rejected with
  `VERSION_DIRECTORY_REQUIRED`; it creates no Volume and does not invalidate
  otherwise valid sibling Version directories. Recognized Work-level sidecars
  are not publication files and are exempt.
- A directory with multiple independent publications that no bundle adapter can
  own fails as that one prospective Volume with `BUNDLE_LAYOUT_AMBIGUOUS`; valid
  sibling Volumes remain publishable.
- One version may contain EPUB, PDF, comic archives, and audio volumes together.
  Their formats do not create additional versions.
- Same-stem, different-format files are distinct volumes. Supporting alternate
  renditions of one volume would require a future explicit manifest; the system
  does not guess this relationship.

#### `AUDIOBOOK`

```text
# Root-level single-file work
<library>/single-book.m4b

# One multi-track volume
<library>/<work>/track-01.mp3
<library>/<work>/track-02.mp3

# Multiple volumes
<library>/<work>/<volume-01>/track-01.mp3
<library>/<work>/<volume-02>/Disc 01/track-01.mp3
```

- A supported root-level audio file creates one work, one implicit version, and
  one single-file volume.
- A first-level work directory containing direct audio tracks creates one
  implicit version and one multi-asset volume.
- Non-disc directories immediately below a work each create a volume. Direct
  tracks, transparent disc directories, and non-disc volume directories may not
  coexist with the latter; the work fails with `AUDIO_LAYOUT_MIXED`.
- A Work containing only direct tracks, only transparent disc directories, or a
  combination of direct tracks and transparent disc directories is one Volume.
- A transparent disc directory matches
  `(?i)^(disc|cd|disk)[ _.-]?([1-9][0-9]*)$`. Inside a selected non-disc Volume
  directory, only direct tracks and transparent disc directories are legal;
  any other nested directory fails with `AUDIO_DEPTH_EXCEEDED`.
- Direct tracks use the reserved disc group `0` and therefore sort before every
  explicit Disc directory. Asset order is disc group followed by locale-neutral
  natural relative-path order. Embedded disc/track tags are descriptive metadata
  only and never reorder assets.
- A readable non-audio publication inside the work fails the affected work with
  `AUDIO_NON_AUDIO_RESOURCE`. Descriptive sidecars are allowed.
- `AUDIOBOOK` has no named-version layer. A user who needs named audiobook
  versions selects `VOLUMES` and places each multi-track volume in a bundle
  directory.
- The ADR 0003 limit of 10,000 tracks applies across one entire `AUDIOBOOK`
  Work, including every Volume and transparent disc directory.
- A supported non-audio root file also fails with
  `AUDIO_NON_AUDIO_RESOURCE`; it is never interpreted as a Work in this mode.

#### Sidecars and structural names

- A physical source entry is stored once. A typed attachment may point from a
  Work, Version, or Volume to that entry; a Volume Asset points to it when the
  Reader consumes its bytes. The implementation never duplicates a path to
  simulate multiple ownership.
- A sidecar is attached only when the owning scope is unambiguous: an exact
  basename match, or a bundle-local role recognized by the format adapter. If
  same-stem publications make an exact match ambiguous, none is selected and
  `SIDECAR_OWNER_AMBIGUOUS` is emitted.
- A generic cover inside a work/version/volume directory attaches to that
  directory's node according to a fixed precedence. A generic root-level cover
  in `FLAT` is ambiguous and remains unattached.
- OPF, embedded tags, covers, CUE/LRC files, and provider metadata can change
  display metadata, navigation, or asset description. They cannot change a
  structural name, structure key, parent, or order.
- `sourceName` preserves the filename stem or directory name. A separate
  metadata projection owns editable `displayTitle`, authors, series, tags,
  narrator, and similar descriptive fields.

### 3. Keep opaque IDs; do not make paths primary keys

Paths author topology but do not become public identity. Every work, version,
volume, and asset receives an opaque ID on first discovery. Reading progress,
bookmarks, history, downloads, and deep links use those IDs.

For idempotent reconciliation, each node has a local structure key:

```text
SHA-256(parentOpaqueId | topologyVersion | nodeRole | comparison-normalized localName)
```

The absolute library root, ancestor names, and descriptive metadata are excluded.
A file-backed node's `localName` includes its extension; `sourceName` may expose
the stem for display. Directory-backed nodes use the complete directory name;
an implicit Version uses the reserved, non-user-visible `$implicit` token, and
the sole Volume under an implicit one-volume Work uses `$single`. A Volume Asset
does not derive identity from a bundle-relative path. Its active key is
`(libraryId, volumeId, sourceEntryId, role)`; path and playback order are
projections of the SourceEntry ancestor chain and topology policy. A proven
track or Disc-directory rename therefore does not cascade asset identities.
A full relative path is a bounded ancestor-chain projection, not a denormalized
identity column on every descendant. A proven Work/Version directory rename
therefore changes one node rather than rewriting hundreds of thousands of child
keys. A repeated scan of the same structure reuses the row and ID.

A source change in the same Volume slot keeps the Volume ID. The aggregate owns
four monotonic revisions:

- `contentRevision` changes when Reader-visible text/pages/audio essence,
  required membership/order, source format, or Reader-relevant sidecar changes;
- `requiredManifestRevision` changes whenever any required source byte,
  membership, order, digest, or delivery fact changes;
- `optionalManifestRevision` changes only for optional artwork/sidecar delivery;
- `metadataRevision` changes for descriptive metadata or artwork that cannot
  affect reading/restoration.

An unknown external required-byte change conservatively increments both content
and required-manifest revisions. Topology version 1 never rewrites embedded
metadata, OPF, CUE/LRC, or other source bytes. User and provider metadata edits
are database projections, so there is no privileged source-write path that can
bypass this conservative rule.

The Volume `requiredManifestDigest` is SHA-256 over a canonical manifest containing
`topologyVersion` and every required asset's order, source format, byte length,
and full content digest. File size and mtime only trigger re-evaluation; they
never prove content equality. Reader `PublicationFingerprint` remains the
parser/normalization projection used by exact locators; it is distinct from this
source-byte manifest digest and from the monotonic revision. An old Reader
session, index job, or download may not publish against a different revision.

A one-to-one rename or reparent within the same library may preserve IDs when it
is proven by a filesystem move cookie, a stable filesystem identity, or a unique
full-content identity within the bounded reconciliation window. Content equality
never merges two simultaneously present copies. An ambiguous delete/create pair
becomes a missing old node plus a new node and emits
`IDENTITY_MATCH_AMBIGUOUS`.

`LibrarySourceEntry` represents one admitted active name slot, not every raw
directory observation. A scan-scoped `PathCollisionObservation` stores the
preserved names and evidence for entries that collide after normalization, so
the active-slot unique constraint never forces the scanner to discard the second
physical name. Retired tombstones are excluded from that partial unique key.
When a proven move targets a slot occupied by a missing tombstone, matching
content identity reactivates the tombstone ID; proven-different content retires
the tombstone and lets the moved node claim the slot; ambiguous evidence leaves
the slot invalid and preserves both histories without guessing.

Stable identity rows and current topology projections are separate. Work,
Version, Volume, and Asset identity rows contain their opaque ID, immutable
`libraryId`, and non-structural/user state; they do not own a globally unique
current path slot. A `TopologyUnit` owns `activeRevisionId`, and each
`TopologyUnitRevision` owns revision-specific `WorkProjection`,
`VersionProjection`, `VolumeProjection`, and `AssetMembership` rows containing
parent edges, root SourceEntry, structural key, source name, order, role, and
manifest membership. Queries reach projections only through the owning unit's
active pointer. Old or abandoned revisions therefore cannot occupy an active
structure slot, and one pointer compare-and-set can replace membership without
rewriting stable IDs or exposing a half-written graph.

`TopologyUnit` uses typed nullable `workOwnerId`, `versionOwnerId`, and
`volumeOwnerId` composite foreign keys with `libraryId`, plus exactly-one and
unit-kind checks. Each non-null typed owner has a partial unique constraint, so
one owner has one unit. `activeRevisionId` is nullable before first activation;
there is then at most one ACTIVE revision and exactly one after first success.
The pointer uses a composite foreign key `(libraryId, unitId, revisionId)` so it
cannot select another Library's or another unit's revision. The model never
stores an unconstrained polymorphic owner ID.

`FLAT` and each single-file `VOLUMES` Volume can create and activate their small
projection in one transaction. `VOLUMES` Work and Version containers each have a
bounded one-row container unit; the first valid child may activate newly staged
containers in the same transaction, and later child units reference those active
containers. Every `VOLUMES` multi-asset Volume has its own staged Volume unit.
`AUDIOBOOK` instead uses exactly one Work-owned unit whose revision contains the
implicit Version, all Volumes, and all Asset memberships; those contained
Volumes never own a second unit. Projection uniqueness is scoped to
`(unitRevisionId, parentStableId, sourceEntryId, role)` and active SourceEntry
slots; historical projection rows never block a new proven move.

Progress, bookmarks, mutation receipts, and deep links are owned by
`userId + volumeId`; Work and Version are current authorized query context, not
part of resource identity. An external, proven reparent can therefore preserve
the Volume ID without creating a second progress slot. Observing that user-made
filesystem move is reconciliation, not a system-provided transfer command.

Cross-library movement always creates new catalog IDs because a library is also
an authorization boundary. Changing a library root is allowed only through an
explicit, paused `RelocateLibraryRoot` use case; it claims that the new root is
the same library and then reconciles relative paths. Equal relative paths alone
do not prove identity: every currently PRESENT Volume must have a unique matching
content/manifest identity at the new root. Any missing, ambiguous, or mismatched
current Volume rejects the whole relocation with `LIBRARY_RELOCATION_MISMATCH`;
the command never partially rebinds progress. An unrelated root must be registered
as a new Library. The scanner never infers a cross-root relocation.

Topology version 1 does not write hidden identity manifests such as `.shuku-id`
into user directories. It therefore does not infer an offline/full-scan rename
from a filesystem identity: the old slot becomes missing and the new slot gets
new opaque IDs. Identity is preserved only for a trusted watcher MOVE whose
execution-time no-follow evidence proves the old path absent, the new identity
equal to one current ACTIVE-slot, PRESENT, layout-valid source's unique persisted
identity, the same Library scope, and no collision or newer successor. Any failed proof degrades to ordinary targeted
reconciliation rather than guessing.

### 4. Reconcile generations; do not treat discovery as one-time import

A full scan owns a monotonically increasing generation and snapshots the
library's `organizationMode`, `topologyVersion`, `pathComparison`,
`configRevision`, and canonical root identity.

1. Preflight validates accessibility, root identity, overlap, and configuration.
2. Bounded `scandir` discovery yields work without retaining the complete tree in
   memory.
3. A cheap, bounded `SourceAdmissionProbe` uses extension, MIME, file/container
   signatures, and only the minimum parser evidence needed to type supported
   sources, sidecars, and bundles. It produces typed `ProbedEntry` values.
4. A pure topology interpreter consumes those typed values and produces
   candidates or stable diagnostics.
5. Publication units are deliberately bounded. `FLAT` uses one root entry;
   `VOLUMES` uses one direct file or one validated bundle Volume, while an
   illegal file directly under a Work produces its own
   `VERSION_DIRECTORY_REQUIRED` diagnostic and cannot invalidate valid sibling
   Versions. A Version directory is never accumulated as one transaction.
   `AUDIOBOOK` keeps the whole Work as the fault/publication unit because mixing
   rules and the 10,000-track budget cross its Volumes, but writes a hidden
   `TopologyUnitRevision` in batches of at most 500 rows or 250 ms. Every
   standalone multi-asset Volume, including a `VOLUMES` audio bundle, uses the
   same staged batching. AUDIOBOOK Volumes are batched only inside their one Work
   unit. One fenced compare-and-set changes the
   owning `TopologyUnit.activeRevisionId` only after complete validation;
   incomplete staging is invisible and the previous active revision remains.
   Revision-keyed index jobs and outbox records are published with activation.
6. The PR 5 generation scan passes recognized sidecars to the source-observation
   port so their source entry is recorded as seen, but its schema does not yet
   persist `SidecarRole`. They are not topology candidates and do not create a
   `SourceAttachment` during structural reconciliation. PR 6 extends the same
   fenced observation flush to enqueue an idempotent, policy-versioned typed
   sidecar-resolution intent; it must use the admission evidence already in
   memory and must not infer a role in the repository from a filename. The
   post-commit `SidecarOwnerResolver` uses only that typed intent, the frozen
   source topology, and filename scope to select one unambiguous owner for
   OPF/artwork/LRC/CUE. Ambiguous candidates remain unattached with
   `SIDECAR_OWNER_AMBIGUOUS`; neither sidecar bytes nor descriptive metadata may
   change grouping, parentage, or order.
7. Expensive parsing, navigation, metadata, cover, and search indexing run after
   structural commit. A parse failure changes content readiness, not parentage.
8. Only a fully successful scan of the still-accessible root may advance the
   successful generation from which unseen nodes project as `MISSING`.

A layout diagnostic means discovery completed with an invalid unit; it is not an
infrastructure scan failure. A seen invalid node is `INVALID`, never `MISSING`.
A failed, cancelled, timed-out, permission-denied, or unavailable-root scan never
advances the successful generation. `MISSING` nodes are hidden from normal
catalog queries but retained with their IDs and user state until Library removal.
Effective availability walks the complete SourceEntry and Work/Version/Volume
ancestor chain: any missing ancestor makes the descendant `MISSING`; otherwise
any invalid ancestor makes it `INVALID`. Reappearance restores an existing file
node when identity is unambiguous. A reappearing directory keeps its absence
marker, and therefore all descendants hidden, until a successful full subtree
enumeration reaches a terminal valid, invalid, or empty observation. Each
directory has published `childrenPresenceEpoch` and monotonic
`nextChildrenPresenceEpoch`. Every directory attempt atomically advances `next`
and stamps seen children with that unique proposed value in
`pendingObservedParentPresenceEpoch`, without replacing their old observed
snapshot. Natural iterator exhaustion plus directory/root/fence revalidation
performs an O(1) parent flip to proposed. A child is effectively present only
when its observed epoch or pending epoch equals the parent's current epoch.
After the flip, pending rows are folded by SourceEntry-ID keyset in batches of
at most 5,000; the intent is deleted only after FOLD completes. A crash before
the flip leaves the old snapshot visible, and a retry allocates a new proposed
epoch so an orphan from the old attempt cannot become seen. The marker may clear
after a terminal empty or invalid enumeration, while unstamped old descendants
remain `MISSING`. A single create event never revives stale descendants.

Single-pass targeted materialization may bind a not-yet-visible child only under
the live reconcile fence and only when its explicit binding carries the same
pending epoch as the row and the parent's monotonic `next` value. Every non-root
physical ancestor referenced by the topology plan, including transparent Disc
directories, needs its own binding/proof; a leaf cannot authorize an arbitrary
future-pending ancestor. Query visibility remains based on current, not next. A
physically present top-level path excluded by an ignore/noise rule refreshes an
existing row and marks layout invalid without setting `absenceConfirmedAt`;
only an explicit absent stat may set that marker.

A full scan is incrementally visible, not a database-wide point-in-time snapshot.
Each verified topology unit may become visible before the run ends; an eventual
failure leaves those verified changes in place but cannot make unseen nodes
missing. This avoids a second 1.8-million-row staging catalog.

One Library has exactly one topology-writer lease. `CatalogLibrary` stores a
monotonic `topologyWriterFence`, incremented on every acquisition or takeover.
Every topology upsert, seen/absence update, unit activation, journal replay, and
finalization compare-and-sets that fence together with run state,
`configRevision`, and an allowed Library control state; a stale or removing
writer that affects zero rows rolls back. The global
root registry uses the same cross-process lease/fence discipline.

A separate short-lived cross-process `LibrarySourceMutationGate` serializes only
the final source publish/relocation window with pause, removal, relevant grant
revocation, and write-policy downgrade. It is never held during upload staging
or a full scan. The gate is a crash-released OS/database lock, not a TTL lease
that can expire while rename/fsync is executing. Control commands can therefore invalidate a topology writer by
incrementing its fence without waiting for a long scan, while a revocation waits
at most for an already-linearized atomic publish window rather than racing it.

Delivery is intentionally split without changing this terminal design. PR 5A
implements dormant bounded full-generation scanning, topology materialization,
and generation finalization only. The watcher journal, overflow fence, replay,
and targeted subtree reconciliation described below are the separate dormant
PR 5B/12; PR 5A does not expose or imply watcher behavior, and PR 5B does not
register a production worker or router.

While a full scan is running or finalizing, watcher events are durably journaled
after a scan-start watermark and do not write topology. One per-Library watcher
state plus coalesced/leased reconcile intents is sufficient; there is no third
generic event store. Intents coalesce by at most two raw top-level scopes and
are capped at 2,000 PENDING rows per Library. The 2,001st event enters one
constant-size full-rescan fence before appending another intent. If a reconcile
worker is RUNNING, that same transaction invalidates its topology writer,
abandons its origin STAGING, and deletes all intents; it does not invalidate a
RUNNING/FINALIZING full scan. The fence is cleared only by a successful full
scan whose start watermark covers the through sequence and saw no later event.

Finalization uses one compare-and-set transaction to verify the writer fence,
run state, generation, configuration, root identity, mode, and topology version,
advance `lastSuccessfulGeneration`, and mark the run successful. Missing is initially projected by
`lastSeenGeneration < lastSuccessfulGeneration`, backed by an index, rather than
updated across millions of rows in that transaction. Covered intents are
discarded in that transaction; a remaining PENDING row emits one Library-level
reconcile wake, while an uncovered fence emits one full-scan-required wake.
Workers claim by `firstSequence,id`; this first sequence is ordering only. An
overlapping successor is newer when its `throughSequence` exceeds the running
intent fence's through sequence, including a coalesced row whose first sequence
is older. Outbox payloads never promise a transient intent-row ID. Subtree
reconciliation never advances a full-scan generation.
A targeted delete reconcile uses fresh no-follow observations before it may mark
one observed entry as explicitly absent; descendants inherit that ancestor
absence without row-by-row updates. A file reappearance or proven move may
clear/replace its marker; a directory follows the full-subtree rule above.

Filesystem watchers are accelerators, not the source of truth. Create, modify,
delete, file move, and directory move events enqueue idempotent subtree
reconciliation. Journaling remains active while a Library is ACTIVATING, ACTIVE,
or PAUSED; Pause stops scans/publication/source writes, not lightweight event
capture. Only ACTIVE with a successful generation can claim reconcile work.
The existing transactional `LIBRARY_RESUMED` outbox event is also a
Library-level reconcile wake: PR 11 workers always claim the next durable
PENDING intent by Library and never depend on an intent-row ID or an older wake
that may have been consumed while the Library was paused.
After Pause/Resume, a pending or running intent whose root/mode/comparison/
topology/root identity still match may atomically restamp the current control-only
configuration and restart; a structural mismatch requires a full scan. Periodic
and manual full scans repair missed events.

The application exposes explicit trust-loss inputs for DISCONNECTED,
BACKEND_OVERFLOW, and UNTRUSTED observations (plus root binding loss), all of
which require a full scan. The default watchdog `Observer` cannot prove kernel
queue overflow or root disconnect/unmount, and directory moves can produce
synthetic descendant events. Therefore PR 11 may connect only a backend that
reports health/overflow explicitly and guarantees the trusted parent directory
MOVE precedes ignorable synthetic descendants; otherwise the observation is
UNTRUSTED. Exact root directory MODIFY is only redundant parent-mtime noise,
whereas root DELETE/MOVE loses trust. The database 2,000-row capacity fence is
not evidence that a backend queue did or did not overflow.

An `scandir` iterator is never serialized. While its lease and process remain
alive, the runtime retains a bounded ephemeral iterator/frontier across
cooperative slices and persists only results, counters, and heartbeat. A lease
loss or process restart re-enumerates the WorkItem's subtree root; generation +
local structure keys make every upsert, diagnostic, index job, and outbox record
idempotent. Backpressure prevents one persistent row per source entry.

Post-commit jobs use a processor-specific revision vector rather than one
universal revision key: opening/navigation depend on content and required
manifest revisions; artwork depends on optional-manifest and metadata revisions;
search depends on its indexed descriptive/content projection; provider enrichment
depends on metadata policy and explicit request revision. Only failure of a
required format/opening validator can set the Volume `UNREADABLE`. Artwork,
provider, and search failures keep independent processor states and cannot make
an otherwise readable Volume disappear.

### 5. Remove catalog-only structural mutation

The new product has no commands for:

- media reclassification;
- work merge or duplicate merge;
- volume split;
- moving a volume between works or versions;
- manual structural reorder;
- marking a work organized;
- database-only deletion of a work or volume;
- undoing any of the preceding database projections.

Shelves, tags, editable display metadata, reading state, bookmarks, and metadata
enrichment remain because they do not change source topology. Topology version 1
stores edits and provider results only in database projections and never writes
metadata back into user source files or sidecars.

Topology version 1 exposes no source delete or restore command. Users delete
source topology with their filesystem tools, and reconciliation observes it.
This avoids pretending that an application-data quarantine can atomically move
files from arbitrary local/NAS filesystems. Removing a Library registration is a
different, asynchronous administrative operation: it removes the complete
catalog aggregate, grants, metadata overrides, shelf links, progress, bookmarks,
and history in bounded batches; invalidates client authorization scopes and emits
download-cleanup events; and never reuses IDs. It never modifies user-authored
source entries or the root itself; the only filesystem cleanup is an exact,
identity-verified app-owned staging sibling from a cancelled source operation.
Ambiguous bytes are preserved.

Uploads name a mode-specific structural destination explicitly with `libraryId`
and `configRevision`. Directory segments and file names are separate validated
fields. A multi-file request contains typed assets with `fileName`, `role`,
declared size/MIME, and optional `discDirectoryNumber >= 1`; it never contains a
free relative or absolute path. One active operation is unique by
`(libraryId, targetSlotKey)`.

Uploads are create-only in topology version 1. Before changing bytes, the use
case persists a `PREPARED` operation and idempotency key, then writes and
validates an ignored temporary sibling. Each operation has a durable monotonic
`stagingFence`, `cancelRequestedAt`, and a crash-released
`OperationStagingLock`. A writer holds that lock for a staging write session and
compare-and-sets `PREPARED + stagingFence + no cancellation` at bounded chunk
and state boundaries. A canceller increments the fence and prevents renewal;
cleanup waits to acquire the lock, so it can never delete while an old writer is
still appending. Immediately before publication the writer again validates the
operation fence/state, then
acquires `LibrarySourceMutationGate`, captures the current topology fence, and
revalidates
`controlState=ACTIVE`, the current actor's `ADMIN` grant,
`writePolicy=READ_WRITE`, root, configuration, target parent
SourceEntry/identity, grammar, symlink containment, and the AUDIOBOOK Work-wide
10,000-track total including existing and staged tracks. The gate remains held
through atomic publication and the `FILESYSTEM_APPLIED` transaction. Pause,
removal, relevant grant revocation, and write-policy downgrade acquire the same
gate before committing, so none can race that short final publish window.
`LibraryFilesystem.publishNoReplace` must provide an atomic no-replace
primitive such as `renameat2(RENAME_NOREPLACE)` or a demonstrably equivalent
adapter operation; unsupported filesystems fail with
`ATOMIC_CREATE_UNSUPPORTED`, never a check-then-overwrite fallback. It fsyncs the
published bytes and parent directory, records `FILESYSTEM_APPLIED`, and
transactionally enqueues reconciliation and outbox work. Recovery compares the
staged digest and recorded filesystem identity with the final slot to distinguish
its own completed publish from an external collision; ambiguous cases become
`NEEDS_ATTENTION`. The system never guesses a Work from a filename.

### 6. Use a fresh current schema and client contract

This release is defined only for an empty database and fresh current client
state. In-place upgrade from any previous installation is
`UNSUPPORTED/UNSPECIFIED`: it is not implemented, tested, or promised to return
an error, migrate data, or happen to work. No compatibility path, old-state
decoder, alias, or reset behavior is part of the product.

The current Alembic lineage uses `alembic_version_v2` and an independent
declarative registry/metadata. Its first deterministic revision creates the
current system, User/Auth/Session, and catalog core. Later current schema work
adds immutable revisions. Fresh installation runs the current head against an
empty database; migrations do not import runtime services, use raw SQL, or
backfill another schema.

Empty-schema initialization acquires one cross-process exclusive lock keyed by
the canonical database path, runs the current migration head, and commits the
required system and identity bootstrap rows in one typed ORM transaction. The
offline `BootstrapFirstAdministrator` command is the normal first-admin setup;
business HTTP, workers, schedulers, and Library creation start after that
normal bootstrap state. No old-schema inspection, upgrade branch, or special
reinstall handling is defined.

The current server publishes only current contracts:

- `/api/libraries`, not `/api/monitor-folders`;
- `libraryIds`, not `monitorFolderIds`;
- work/version/volume contracts without media-kind projections;
- a Reader contract that keeps exact locator morphologies but removes
  `mediaVersionId` and `mediaKind`.

The current release does not expose application backup/restore. A future
same-current-generation backup requires a separate decision for opaque catalog
IDs, root remapping, user state, derived data, and secret exclusion.

Current Web, Android, and iOS clients start with fresh local state and use the
current API, Reader, progress, bookmark, and download contracts directly.
Private stores use current app, user, Volume, Library scope, and codec
identifiers; no other-generation data is decoded or converted. Normal login
creates the current VerifiedSession. No special handling for non-current state
is specified.

### 7. Separate Library control, health, and authorization

A Library has a user-controlled state
`DRAFT | ACTIVATING | ACTIVE | PAUSED | REMOVING` and a separate observed health
`UNKNOWN | HEALTHY | UNAVAILABLE | ERROR`. Creation produces `DRAFT`. Accepting
Activate atomically changes it to `ACTIVATING` and freezes root, mode, comparison
policy, and topology version before any incrementally visible node can commit. A
discovery-complete first scan changes it to `ACTIVE`; layout diagnostics do not
make infrastructure discovery incomplete. A failed first scan remains locked in
`ACTIVATING` with error health and may only retry or remove. Pause stops new scans
and source operations but does not hide existing readable data; lightweight
watcher journaling remains active so Resume cannot lose paused-period changes.

Authorization uses an explicit `UserLibraryGrant` with
`READ | CURATE | ADMIN`. The creator receives `ADMIN`; an application-wide
administrator still receives an explicit grant. `writePolicy` describes the
filesystem, not the actor. Reading requires `READ`; metadata edits require
`CURATE`; root visibility, grants, activation, pause, scan rules, relocation,
upload, and removal require `ADMIN`, with `READ_WRITE` additionally required for
source writes. Grants are hierarchical (`ADMIN` includes `CURATE` includes
`READ`), and normal grant commands cannot remove or demote the final ADMIN.

Session state includes a monotonic `authzVersion`, and every grant has an opaque
scope epoch that rotates on revoke/regrant. Private cache/download namespaces use
that scope epoch so an unrelated Library ACL change need not invalidate every
artifact. Reader bootstrap, asset/range/page requests, progress, bookmarks, and
catalog queries join Volume to Library and filter in SQL by the current actor;
forbidden and missing IDs follow the same anti-enumeration response policy.
Ordinary DTOs never contain `rootPath`; an admin DTO is a distinct contract.

Explicit online revocation cancels active transfers and protected sessions and
prevents new opens. A device that is genuinely disconnected can only enforce
revocation after the next verified authorization response; transient network
failure alone is not proof of revocation. When invalidation is learned, private
artifacts become inaccessible and are scheduled for app-owned cleanup.

Removal accepts `DRAFT`, `ACTIVATING`, `ACTIVE`, or `PAUSED`. It briefly acquires
`LibrarySourceMutationGate` and commits the durable access barrier: prevent new
source/topology leases, increment both fences, change the Library to `REMOVING`,
revoke all grant scopes, exclude it from every Catalog/Reader/asset/progress
query, set `cancelRequestedAt` and increment `stagingFence` for every non-terminal
source operation, cancel ordinary scan/reconcile intents, and write the
invalidation outbox.
The gate is then released.

A removal-owned drain, which does not call or wait for ordinary reconcile,
first acquires each operation's staging lock, then changes verified unpublished
`PREPARED` operations to `CANCELLED` after cleaning
their owned staging bytes. `FILESYSTEM_APPLIED` or `RECONCILE_QUEUED` operations
become terminal `ABANDONED_BY_LIBRARY_REMOVAL`; their already published source
bytes remain untouched and their reconcile intent is discarded. If ownership is
uncertain, the worker never deletes or claims those bytes: it preserves them,
records a `SOURCE_BYTES_PRESERVED_DURING_REMOVAL` audit event outside the
soon-to-be-deleted aggregate, and terminalizes the operation as abandoned without
requiring a now-revoked Library grant. A crash leaves
the persistent `REMOVING` barrier in place and a removal worker resumes the
drain. Finally, a second short gate verifies that no non-terminal operation
remains and records drain completion before bounded cascade. Every topology
mutation compare-and-sets that the Library is not `REMOVING`. Library removal is
the only operation allowed to eliminate the last ADMIN.

Lock order is fixed: a publisher holds its operation lock before briefly taking
the source-mutation gate; removal commits and releases the gate before waiting
for any operation lock. Removal never holds the gate while draining.

Current client bootstrap uses the authenticated current server profile and
session, then opens the current Reader, progress, bookmark, and Library stores.
Scope epochs inside the verified grant snapshot gate protected stores but are not
required to locate or decode the current VerifiedSession itself.

### 8. Define the current Reader and download boundary

The new language-neutral contract is Reader v5. Reader v5 uses exactly
`REFLOWABLE | PDF | COMIC | AUDIO`, matching the four exact locator variants.
The server publishes source format, morphology, content/manifest revisions, and
delivery capabilities. Each platform intersects them with its local
`EngineCapability`; the server does not claim that a client has an engine.

Bootstrap access is a validated discriminated union, not a bare URL. It can
describe an original single file, an HTTP-range file, a parser-backed resource
manifest, a comic page manifest/stream, or ordered multi-asset audio. It exposes
opaque authenticated endpoints and `canStream`/`canDownload` facts. Clients never
persist a temporary tokenized URL and refresh bootstrap before resuming access.

Server progress identity is `(userId, volumeId)`. A progress snapshot, mutation,
bookmark, exact locator, and download manifest all carry `contentRevision`.
Writes also preserve ADR 0011's `baseRevision` and UUID `mutationId`; an old
content revision fails with `409 CONTENT_REVISION_MISMATCH` instead of overwriting
current state. A saved locator from an old revision is only a recovery candidate:
it must navigate and recapture successfully on current content before it can be
saved under the new revision.

Mutation processing first verifies current authorization, then looks up an
existing `(userId, volumeId, mutationId)` receipt and returns its original result
before checking current content/base revisions. Only an actually applied success
stores a receipt; validation/conflict failures do not. A client that resolves a
conflict creates a new mutation ID.

An audio locator identifies `assetId` plus playback milliseconds and optional
chapter identity. The asset must still belong to the same Volume and current
revision. It never uses a path, filename, or array index as identity.

Every downloadable multi-asset Volume has an immutable manifest:

```text
volumeId
contentRevision
requiredManifestRevision
ordered requiredAssets [assetId, sourceFormat, mimeType, sizeBytes, digest, order, validator]
requiredManifestDigest
```

Every required downloadable asset has a full digest. Resume requests carry a
strong revision validator, and the server never serves updated bytes under an
old manifest. The client stages required original assets on one app-owned
filesystem, validates each digest, fsyncs them, rechecks the manifest revision,
atomically replaces the complete directory, and writes a completion marker.
Optional artwork has a separate optional manifest and never blocks or invalidates
required-bundle completion. A package containing mixed required-manifest
revisions is never publishable. A completed older required manifest with the same
`contentRevision` remains parser-readable but is marked source-update-available;
a different `contentRevision` is not the current offline publication.

Every topology-admitted audio track belongs to the expected required set. If any
expected track is pending, corrupt, or unreadable, the whole Volume is not READY
and cannot be played or downloaded. A track leaves the required set only after a
successful reconciliation proves that the user removed it and publishes a new
content/required-manifest revision; parser failure never silently shrinks a book.

### 9. Make organization mode immutable after activation

`organizationMode`, `topologyVersion`, and `pathComparison` are immutable as soon
as `ActivateLibrary` is accepted and the Library enters `ACTIVATING`, before any
incrementally visible node can commit. The root is likewise no longer directly
editable and can change only through the separately verified, paused
`RelocateLibraryRoot` use case. Reinterpreting even a failed or partially
materialized activation could attach state to different content. A user who
wants a different grammar removes the registration and creates a new one,
receiving new catalog IDs; activation failure does not unlock these fields.

Ignore rules may change through a version-checked command. The change increments
`configRevision`, cancels stale work, and requires a full scan.

## Consequences

- Local directory structure becomes predictable, inspectable, and the only
  source of catalog membership.
- Metadata quality no longer changes identity or grouping.
- Formats and Reader morphologies remain explicit even though media categories
  disappear.
- Simple structural commands disappear; users reorganize files with their normal
  filesystem tools and then reconcile the library.
- Offline ambiguous renames can create new IDs unless a future manifest contract
  is adopted.
- Multi-track audio requires an ordered multi-asset Reader/download contract;
  indexing alone must not be advertised as playable support.
- In-place upgrade from a previous installation is `UNSUPPORTED/UNSPECIFIED`.
  This release starts from an empty database and fresh current client state;
  no upgrade behavior, error contract, migration, or compatibility path is
  promised.
