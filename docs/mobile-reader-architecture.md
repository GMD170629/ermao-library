# Mobile Reader Architecture

Status: Reader v4 cross-format exact-progress contract implemented; physical-device conformance pending
Last updated: 2026-08-14

This document is the architecture contract for the native Reader and its Reader v4 cross-platform progress integration. Read it with the Mobile phase specifications and `docs/mobile-app-development-global-guidelines.md` before changing Reader domain, storage, engines, navigation, or UI.

## 1. Scope and exactness boundary

The Reader capability supports these location morphologies:

- reflowable publications use an exact Readium resource plus DOM block/text anchor;
- PDF and comics use standard page positions;
- audio uses file/chapter identity and playback milliseconds.

For reflowable content, “exact” means the same DOM block or unique text anchor in
the same Publication resource. It never means the same visual page, line,
character offset, screen coordinate, or pixel. PDF exactness is a canonical page
plus normalized page-local position; comic exactness is the canonical page
resource/index.

The native apps do not embed the Web Reader. Web, Android, and iOS share semantics and wire contracts while keeping platform-owned engines and local exact stores.

## 2. Dependency direction

```text
presentation -> Reader application ports/use cases -> Reader domain
engine/storage/network adapters -> Reader application ports + domain
composition root -> presentation + application + adapters
```

Shared Reader domain code must not import UI, Android/iOS, Readium, Foliate, browser, filesystem, HTTP, or database types. Engine-specific locators are validated JSON objects kept behind adapters. Other capabilities use only Reader public APIs.

## 3. Content identity

Reader v4 has one exact Publication identity:

- original source file SHA-256;
- parser identifier which generated the Publication content structure;
- normalization identifier which generated stable reading order, hrefs, and DOM.

Navigator SDK versions are diagnostic metadata and are not content identity.
All three fingerprint fields must match before automatic remote restoration.

The exact local record identity is:

```text
serverIdentity + userId + clientId + volumeId + PublicationFingerprint
```

`authorizationVersion` is deliberately absent. Reauthentication does not hide a valid position for the same client and local publication. A different account, client, server, volume, or local content interpretation cannot reuse that exact record.

## 4. Location model

Reader v4 uses a renderer-neutral `PublicationLocation` discriminated union. All
variants contain the structured Publication fingerprint and the complete encoded
location is limited to 64 KiB. The variants are:

- `reflowable`: a required Readium `engineLocator` with an exact DOM anchor;
- `pdf`: a zero-based page index and required four-decimal normalized page-local progression;
- `comic`: a zero-based page index and the canonical safe reading-order resource href;
- `audio`: a file id, optional chapter id, and playback position in milliseconds.

For a reflowable publication, the required engine locator contains:

- an `href` and media type;
- a CSS selector, fragment/CFI, or bounded uniquely verifiable text context;
- optional progression and logical position for display and diagnostics;
- the structured Publication fingerprint;
- a bounded Readium Locator payload.

Progression and position alone are not exact and cannot be uploaded. Whole-book
`displayPercent` is never an automatic restoration candidate.

The reflowable engine is `readium`; platform is `android`, `ios`, or `web`.
`highlight` is limited
to 512 characters and `before`/`after` to 256. JSON strings containing encoded
JSON and binary payloads are invalid at the wire boundary.

PDF, comic, and audio may add an engine locator for navigation assistance or
diagnostics. It does not participate in their exact location identity.

## 5. Reader v4 server contract

First-party clients use only:

```text
GET /api/reader/v4/volumes/{volumeId}/bootstrap
PUT /api/reader/v4/volumes/{volumeId}/progress
PUT /api/reader/v4/volumes/{volumeId}/reading-status
GET|PUT /api/reader/v4/volumes/{volumeId}/bookmarks
```

Reader v1–v3 routes return `410 Gone`. Mobile compatibility advertises only `readerV4=true` and schema version 4.

The progress request contains:

```json
{
  "schemaVersion": 4,
  "clientId": "stable-client-id",
  "mutationId": "58a3ac3c-52d0-41ed-9c85-0524b532f25b",
  "baseRevision": 17,
  "capturedAtEpochMillis": 1786500000000,
  "locator": {
    "kind": "reflowable",
    "publication": {},
    "engineLocator": {
      "engine": "readium",
      "platform": "ios",
      "version": "readium-swift:3.11.0",
      "payload": {}
    }
  }
}
```

The response contains revision, the exact Publication location, display-only percentage, and
server receive time. Locator is required. A non-exact position returns
`422 READER_LOCATOR_NOT_EXACT`.

## 6. Server persistence

`LibraryReadingProgress` is the current aggregate snapshot with one row per user
and volume. Revision increases monotonically. Mutation receipts make retries
idempotent.

The repository saves:

- the validated Publication location JSON and derived display percentage;
- client and mutation identity;
- client capture time for diagnostics only;
- the current revision and server receive time;
- the existing `UserMediaHistory` projection.

A stale `baseRevision` returns `409 READER_PROGRESS_CONFLICT` with the current
snapshot. The server never silently overwrites or applies a forward-only rule.
Fingerprint mismatch is a validation failure, not a percentage fallback.

## 7. Local save and upload

All clients implement the same lifecycle:

1. The engine emits a real location change.
2. A 500 ms trailing debounce coalesces continuous movement.
3. One timestamp is created.
4. The full exact location is committed locally.
5. The exact Publication location and latest-only pending mutation commit atomically.
6. Only after local commit, one single-flight v4 PUT is attempted.
7. Success persists the confirmed revision before clearing pending state.
8. Network failure preserves pending state; `409` persists a conflict.

Each platform retries durable pending work on network recovery, foreground entry,
and Reader exit. During an in-flight request, one durable latest slot retains
only the newest stable Locator. Pending and conflict state survive termination.

When no exact anchor is available, the client may save a platform-local engine
position but must not upload or label it cross-device synchronized.

## 8. Restoration policy

An explicit deep link, chapter/page request, or bookmark always wins. Otherwise
only a fingerprint-compatible exact Publication location may restore automatically.
For reflowable content, after `Navigator.go(locator)`, the platform recaptures the
first-visible Locator. Success requires the same href plus matching selector,
matching fragment/CFI, or a uniquely matching normalized text context. PDF,
comic, and audio recapture and compare their canonical morphology-specific
identity. A navigation API's success result alone is not proof.

If exact verification fails, the user can explicitly try a nearby position,
open the chapter, or keep the local position. Progression, position, and
displayPercent are never silently adopted.

## 9. Local persistence

Reader v4 was unreleased, so the cross-format union is a coordinated destructive
replacement. Web clears the old exact/pending/conflict IndexedDB namespaces;
native progress and sync codecs use document version 5 and reject version 4;
the server data migration deletes old v4 progress and mutation receipts. No
Foliate, legacy Reader v4, location, completion, or percentage migration exists.

Publication download, bounded streaming, file SHA-256, parser fingerprinting, path/symlink containment, temporary-file validation, and atomic installation remain unchanged by progress simplification.

## 10. Platform adapters

Android uses Readium Kotlin Toolkit 3.3.0. iOS pins Readium Swift Toolkit 3.8.0 to revision `f7d10d2bf5876408feae14d634416f69d1473fd8`. Both map a complete Readium Locator into the engine payload and expose semantic public anchors without leaking Readium types into shared domain code.

Web uses Readium TS. Its version-locked same-origin iframe bridge is isolated
behind the adapter until the toolkit exposes a public first-visible-block API;
failure to read the frame fails closed and disables exact sync.

Native publication downloads reuse authenticated cookie storage, stream into an app-private staging file, validate declared and actual size, optional SHA-256, MIME/publication type, and atomically install the result. Redirect, traversal, symlink, empty-body, overflow, truncation, cancellation, and oversized-error cases fail closed.

Reader v4 bootstrap is also the authoritative Download Center catalog source. A completed
artifact persists the real `mediaVersion.id`, `mediaVersion.mediaKind`, server-completed
hint, and the volume's index/sort order. The stable local hierarchy is
`work -> media version -> volume`; title/author/cover decorate the work, never replace
these identifiers. Pre-v4 local manifests may migrate into deterministic per-volume
`legacy-volume:<volumeId>` groups, but an online v4 response missing or contradicting
media-version identity fails closed.

A shared foreground volume runtime exposes observable `Preparing`, `TaskCreated`,
`Downloading`, `Progress`, `ReadyToOpen`, `Failed`, and `Cancelled` states. Reader
navigation consumes `ReadyToOpen` only after byte verification, atomic file publication,
and completed-artifact persistence. An already verified downloaded volume enters Reader
directly; authenticated cover loading is a non-blocking visual transition and is never a
publication-completion dependency.

## 11. Verification requirements

Automated contracts must cover:

- mutation idempotency and monotonic revision;
- stale base revision producing a durable conflict;
- 500 ms burst coalescing;
- single-flight latest-slot behavior;
- network failure preserving the latest durable pending mutation;
- all four Publication location round trips and morphology-specific post-navigation verification;
- progression, position, and percentage never counting as exact;
- mismatched publication fingerprints refusing automatic restoration;
- PDF, comic, and audio exact positions;
- v1–v3 `410 Gone` and first-party v4-only paths;
- process-death recovery for pending and conflict state.

Android acceptance includes building and deploying the debug APK to the dedicated test emulator, cold launching it, and running relevant instrumentation. iOS acceptance must use an `iosArm64`/`iphoneos` build and a connected physical iPhone or iPad. Simulator evidence is prohibited. Linux KMP compilation is useful static evidence but is not iOS runtime acceptance.

## 12. Security and observability

Reader routes preserve resource authorization and anti-enumeration behavior. External location JSON is bounded and validated before mapping. Logs may contain stable user/volume/correlation identifiers and outcome codes, but never book text, cookies, tokens, full locator payloads, or private filesystem paths.

The Reader shell remains native and owns lifecycle, accessibility, back/close,
navigation controls, table of contents, and preferences. Readium internals are
engine implementation details and never become an unrestricted application
bridge.

## 13. Native EPUB controls and preferences

iOS and Android use the same native EPUB control information structure as the
Web Reader without embedding the Web Reader: back, current chapter, and quick
bookmark at the top; chapter navigation, progress slider, contents, notes,
appearance, and settings at the bottom. Sheets, menus, sliders, switches, safe
area handling, Dynamic Type, VoiceOver/TalkBack, and reduced motion remain
platform-native.

The device-level Reader preference contract is scoped by `serverIdentity +
userId` and contains `appearance`, `display`, `interaction`,
`epub.typography`, and `epub.optimization`. Defaults match the Web Reader:
Warm/manual, 18 px, 1.9 line height, Source Han Sans fallback, weight 400,
standard margins, single-page paginated flow, and the documented paragraph
defaults. Legacy `paper`, `night`, and `system` inputs migrate to Warm, Night,
and system mode. Preference-driven Readium reflow must suppress the resulting
location observation from progress persistence.

The enabled theme set is Day `#F7F7F4/#1E293B`, Warm
`#FDF6EA/#2B2118`, Green `#E8F0E3/#203126`, Night
`#0F172A/#E2E8F0`, and Black `#000000/#F8FAFC`; system mode resolves to Day
or Night. Readium public preferences own colors, size/weight ratios, line and
paragraph layout, positive letter spacing, margins, scroll mode, and column
count. Unsupported controls remain present but disabled, with no explanatory
copy. These include annotations, animation and swipe toggles, phone page width,
negative letter spacing, independent publisher-style parts, and smart/safe
optimization. iOS volume-key turning is disabled; Android enables it.

`apps/web/public/fonts/reader` is the single licensed font asset source. Source
Han Sans serves PingFang/Heiti/YaHei, Source Han Serif serves Songti, and LXGW
WenKai serves Kaiti. The files add approximately 35 MB uncompressed. iOS
Readium declares these bundled WOFF2 files through its public custom-font API.
Readium Kotlin 3.3 does not expose the equivalent public declaration API, so
Android packages the assets for forward compatibility but keeps the font-family
control disabled; reflection, private scripts, and EPUB DOM modification are
prohibited.

Bookmarks use the existing Reader v4 collection wire schema. Local state is
isolated by `serverIdentity + userId + volumeId + contentFingerprint`, retains
an exact platform Locator for local jumps, and projects only `reflow
resourceKey/progression` to the server. Every mutation atomically replaces the
local collection and latest pending snapshot before a single-flight whole-set
PUT. A newer mutation replaces an in-flight pending snapshot. Without pending
local work, remote and local entries merge by ID/creation time; with pending
work, the local set wins and UI may state only “device first / pending sync,”
not conflict-free synchronization.

## 14. EPUB progress recovery and detail projection

Native EPUB readers start in immersive mode with their control overlays hidden.
The center reading zone, accessibility actions, and keyboard Escape affordance
remain responsible for revealing controls; loading and recovery UI must not
force the controls open.

Local and Reader v4 exact positions are compared only when their publication
fingerprints match. Positions with the same semantic Readium anchor restore
silently. Different positions are ordered by their actual captured timestamp,
with the server winning an exact timestamp tie. The newer position is restored
automatically and the older position is offered in a non-modal themed notice.
The notice does not block reading, remains until dismissed, selected, or normal
navigation occurs, and persists the selected historical position only after the
Navigator confirms the target resource. Legacy servers without
`capturedAtEpochMillis` use `receivedAtEpochMillis` as the ordering fallback.
Navigator initialization and preference reflow emissions are not user progress
and must never be persisted as new reading activity.

After every successful local progress transaction the Reader publishes the
shared `ReaderProgressPresentationUpdate` contract at application scope. An
open Work Detail projection applies a matching namespace/work/volume update
immediately, including overall progress, volume progress, and chapter state,
then refreshes the server representation without replacing newer local state.
Work Detail also performs a non-blocking refresh whenever it becomes active.
Chapter state is derived from exact href/fragment first, then the server's
global chapter index and sort order. Duplicate titles are never navigation
identities, and overall percentage is not used to guess a chapter; 100 percent
is the sole exception and marks every chapter read.
