# Mobile Reader Architecture

Status: Reader v4 cross-format exact-progress contract implemented; physical-device conformance pending
Last updated: 2026-08-26

This document is the single authoritative architecture contract for the native Reader and its Reader v4 cross-platform progress integration. If a Mobile phase document or historical acceptance artifact describes a different progress state machine, this document wins and the conflicting material must be removed rather than implemented as compatibility behavior. Read it with the Mobile phase specifications and `docs/mobile-app-development-global-guidelines.md` before changing Reader domain, storage, engines, navigation, or UI.

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

## 3. Publication diagnostics and progress identity

Reader v4 retains these Publication diagnostics:

- original source file SHA-256;
- parser identifier which generated the Publication content structure;
- normalization identifier which generated stable reading order, hrefs, and DOM.

Navigator SDK versions are also diagnostic metadata. None of these fingerprint
fields participates in reading-progress ownership or validation. Progress is
owned by the server-authorized `bookId + resourceId`; an asset, parser, or
normalization change does not create a new progress slot or block restoration.

For EPUB, MOBI-family, and TXT, matching content identity means that every client
uses the same source-format parser contract and produces stable reading-order hrefs
and semantic text anchors. Runtime DOM need not be byte-identical. Exact restoration
uses the same href plus a selector, fragment/CFI or bounded text context. The
production identifiers are:

- EPUB: `epub-package:1 / shuku-epub-locator-dom-v2`;
- MOBI family: pinned libmobi parser / `ermao-mobi-core-v1+shuku-locator-dom-v2`;
- TXT: `shuku-txt-parser-v1 / shuku-txt-publication-v2`.

The original library file is immutable and is the only persisted Reader artifact.
Reader bootstrap, download, cache and recovery never create a derived EPUB, ZIP or
unpacked publication directory. MOBI-family and TXT parsers expose bounded virtual
Publication resources in memory. Web streams those resources through authenticated
Publication routes; Android and iOS bind those same resources through the shared
KMP OnlinePublicationSession. Explicit completed downloads and local imports use
the original native parsers. Delivery may
set CSP and apply the documented head-only security policy but does not rewrite the
author body.

The exact local progress record identity is:

```text
serverIdentity + userId + clientId + bookId + resourceId
```

`authorizationVersion` is deliberately absent. Reauthentication does not hide a
valid position for the same client, book, and resource. A different account,
client, server, book, or resource cannot reuse that exact record.

## 4. Location model

Reader v4 uses a renderer-neutral `PublicationLocation` discriminated union. All
variants retain the structured Publication fingerprint as diagnostic metadata, and the complete encoded
location is limited to 64 KiB. The variants are:

- `reflowable`: a required Readium `engineLocator` with an exact DOM anchor;
- `pdf`: a zero-based page index and required four-decimal normalized page-local progression;
- `comic`: a zero-based page index and the canonical safe reading-order resource href;
- `audio`: an asset id, optional chapter id, and playback position in milliseconds.

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
GET /api/reader/v4/resources/{resourceId}/bootstrap
GET /api/reader/v4/resources/{resourceId}/progress
PUT /api/reader/v4/resources/{resourceId}/progress
PUT /api/reader/v4/resources/{resourceId}/reading-status
GET|PUT /api/reader/v4/resources/{resourceId}/bookmarks
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

The response contains revision, source `clientId`, the exact Publication location,
display-only percentage, and server receive time. Locator is required. A non-exact position returns
`422 READER_LOCATOR_NOT_EXACT`.

The lightweight progress GET returns the current snapshot or `null`. It emits a
revision ETag and accepts `If-None-Match`; unchanged state returns `304`. It is
used only while a Reader session is open and is checked after opening, on
foreground entry, and on network recovery. There is no polling, WebSocket, or SSE.

## 6. Server persistence

`ReaderResourceProgress` is the current aggregate snapshot with one row per user
and resource. Revision increases monotonically. Mutation receipts make retries
idempotent.

The repository saves:

- the validated Publication location JSON and derived display percentage;
- client and mutation identity;
- client capture time for diagnostics only;
- the current revision and server receive time;
- the existing `UserMediaHistory` projection.

A stale `baseRevision` returns `409 READER_PROGRESS_CONFLICT` with the current
snapshot. The server never silently overwrites or applies a forward-only rule.
The authorized book and resource are the progress identity. Publication fingerprint
differences never reject a progress read or write.

## 7. Local save and upload

All clients implement the same lifecycle:

1. The engine emits a real location change.
2. A 500 ms trailing debounce coalesces continuous movement.
3. One timestamp is created.
4. The full exact location is committed locally.
5. The exact Publication location and latest-only pending mutation commit atomically.
6. Only after local commit, one single-flight v4 PUT is attempted.
7. Success persists the confirmed revision before clearing pending state.
8. Network failure preserves pending state; `409` drops the rejected mutation and
   raises an ephemeral remote-progress notice for the open session.

Each platform retries durable pending work on network recovery, foreground entry,
and Reader exit. During an in-flight request, one durable latest slot retains
only the newest stable Locator. Pending state survives termination. A `409`
mutation is never immediately replayed: only the next genuinely different exact
location creates a replacement mutation based on the newest server revision.
Preference reflow and repeated capture of the same block are not movement.

When no exact anchor is available, the client may save a platform-local engine
position but must not upload or label it cross-device synchronized.

## 8. Startup and session restoration policy

An explicit deep link, chapter/page request, or bookmark always wins. Online
Reader entry fetches a fresh bootstrap. When content is already local, bootstrap
and local parsing are independent: bootstrap failure does not prevent the parser
from opening the publication. With no pending mutation, the newest valid exact
location for the same book and resource restores automatically. Invalid or
un-restorable progress starts at the beginning. A newer server snapshot is
selected deterministically and a newer valid local pending mutation remains local
and retries normally; no startup progress condition may display a blocking
local/cloud/cancel dialog. A pending state for another book or resource is ignored.

Once Reader is open, a newer snapshot from another `clientId` that differs from
the current exact position is shown as a non-modal notice. It does not steal focus
or block reading. The user may dismiss it, or navigate to it; navigation is accepted
only after the same morphology-specific exact verification described below. If the
user instead continues reading to a different exact position, that real movement
rebases and overwrites the remote revision.

For reflowable content, after `Navigator.go(locator)`, the platform recaptures the
first-visible Locator. Success requires the same href plus matching selector,
matching fragment/CFI, or a uniquely matching normalized text context. PDF,
comic, and audio recapture and compare their canonical morphology-specific
identity. A navigation API's success result alone is not proof.

If exact verification fails, the user can explicitly try a nearby position,
open the chapter, or keep the local position. Progression, position, and
displayPercent are never silently adopted.

## 9. Local persistence

The streaming migration preserves existing exact progress, bookmarks, pending
mutations, local imports and explicitly completed Downloads. It does not trigger
an identity reset, delete a database, or reinterpret locator payloads. Cleanup
only removes obsolete automatic online body replicas and partials whose origin
can be established, never ambiguous files or user-created offline content.

Explicit Downloads stores and verifies the original authorized file. Online Reader never acquires a complete original. Parser and
normalization identifiers remain diagnostics and never create a second persisted
reading representation.

## 10. Platform adapters

Android uses Readium Kotlin Toolkit 3.3.0. iOS pins official Readium Swift Toolkit 3.9.0 to revision `de07026e9f825a5791f27a7ac4cd6bb1a784ab8d`. Both map a complete Readium Locator into the engine payload and expose semantic public anchors without leaking Readium types into shared domain code.

The approved iOS baseline is **3.9.0** (authorized 2026-08-28), including upstream
[HTML/CSS resource cache invalidation fix #781](https://github.com/readium/swift-toolkit/pull/781).
This supersedes earlier instructions freezing iOS at 3.8.0; Android and Web pins
are unchanged. Do not downgrade to 3.8.x to avoid migration or build errors.
Further SDK changes require explicit authorization and a corresponding update to
the project revision, SwiftPM lock, locator diagnostic version, this policy and
`apps/mobile/iosApp/verify_readium.py`. The same check runs in the Xcode build and
Mobile CI. Official SDK source remains unmodified: no private APIs, copied cache
patches, preference reflow validation, Navigator replacement or layout compensation.
Old locator SDK version metadata remains restorable and is not a rejection rule.
Upgrade acceptance must exercise font changes and scroll/paged mode across newly
loaded, preloaded and revisited chapters on a physical iOS device; compilation
alone does not close a rendering defect.
Evidence and outstanding paths: [iOS 3.9.0 upgrade record](testing/ios-readium-3.9.0-2026-08-28.md).

Web uses Readium TS. Its version-locked same-origin iframe bridge is isolated
behind the adapter until the toolkit exposes a public first-visible-block API;
failure to read the frame fails closed and disables exact sync.

Online reflowable opening resolves manifest and positions, then binds requested original chapters/resources to native Readium. Metadata and HEAD never read chapter bodies. Application adapters keep their existing 8 MiB chapter, 32 MiB auxiliary-resource and 64 MiB body-cache limits; PDF requests remain at most 1 MiB and reject an ignored Range before body consumption. Native SDK ordinary caches are allowed: the product no longer requires deep SDK patches to enforce an exact aggregate cache budget. Owned sessions are closed on navigation/account changes.

Native Reader uses `ReaderLaunchCoordinator` for online, verified-local, visible-download and unavailable decisions. The default application admission limit is `ReaderAdmission.maximumPublicationBytes`: 2 GiB inclusive, including IMAGE_DIR member totals. This is not a guarantee that every admitted file can open. Whole-array platform limits, XML/decompression/image safety limits and engine failures remain independent. No settings screen, synthetic chapter splitting, format conversion, new indexing or incremental parser is introduced.

An online parser/size limit or unsupported PDF Range can select download after checking known local limitations. Authentication, corruption, revision changes and network errors do not. The transition observes the existing account-owned Downloads runtime, shows cover/title/reason, queue/download/parse states, real bytes and percentage, cancel and retry. The only complete-file transfer remains `DownloadResourceRuntime` / `KtorDownloadsGateway`; Reader has no download adapter of its own. Verified artifacts open without network and remain managed by Downloads. Closing detaches the launch and pauses only its owned transfer; late completion cannot open a closed or different-account reader. Local parse failure never loops or redownloads.

The original chapter target, or the latest persisted Reader progress, is restored after download using the existing progress owner. All file lengths, offsets and totals use 64-bit arithmetic. Product admission policy is passed to C through explicit open options; no duplicated 64/512 MiB file gate remains in native Reader. TXT/FB2 full materialization and MOBI parser memory behavior remain existing engine constraints; OS memory termination cannot be reliably recovered.

The server still parses its existing original source when needed, without a prior import-index prerequisite. EPUB uses the original ZIP structure; TXT/FB2 defer XHTML generation until a chapter request; MOBI snapshots are coalesced and runtime-owned, invalidated by revision and released on eviction/shutdown. Parser budgets are unchanged. Only declared online source/cache admission failures use `PUBLICATION_ONLINE_LIMIT`; requested resource limits retain `PUBLICATION_RESOURCE_TOO_LARGE`. Actual format-parser resource failures use `PUBLICATION_PARSER_LIMIT`/`PUBLICATION_PARSER_MEMORY` and do not automatically select Downloads. Corruption and authentication remain distinct. Chapters remain whole.

Web retains the existing online-only behavior, cache strategy and pinned dependency patches. The native download transition and ordinary SDK-cache concession do not apply to Web. See ADR 0024 and the native transition verification record for evidence and limitations.

FB2 uses `shuku-fb2-parser-v1 / shuku-fb2-publication-v1` on every client.
The native platform XML parsers feed a shared bounded mixed-content decoder.
It preserves the server's `fb2/section-NNNN.xhtml` resources, six-digit
`fb2-node-NNNNNN` anchors, nested TOC, inline formatting, tables, poems,
embedded images and internal note/return links. The server body golden in
`test-data/library/fb2/reader-contract-bodies.json` is verified by Android,
iOS and backend tests. FB2 binary resources use the actual Base64 decoder and
explicit size budgets and stay in memory. Image signatures are not checked before
the final image decoder. DTD/entity isolation remains; namespace acceptance is
determined by the platform XML parser, without a second namespace validator.
The documented `l:href`/`xmlns:xlink` repair only affects parser input, never the
original file. This replaces the earlier MIME-signature and extra-prefix policy.

Online native Publications bind the server-provided position list through an
in-memory positions service without opening chapter bodies. Local imports and
completed offline originals retain their parser-specific positions services.
These logical positions
support explicit scrubber navigation only: percentage is still never an exact
restoration or upload identity. Parser validation exceptions crossing KMP into
Swift must be declared with `@Throws` and mapped to a stable Reader error,
including blank/invalid TXT input.

Library's `KINDLE` resource family is accepted only at the online Reader entry.
Reader bootstrap resolves the exact MOBI/AZW/AZW3/PRC original before opening.
It is not an offline artifact format or a reason to relax parser validation.

Pinned libmobi's legacy MOBI6 HTML can omit the XHTML default namespace and the
`mbp` prefix declaration. Native adapters bind these on the root element before
the security decorator, otherwise WebKit can render an XML error document.
`MobiMarkupEnvelope` changes only the XML envelope in memory; original bytes,
resource hrefs, body markup and locator projection stay unchanged. Existing
namespace declarations are preserved. This is not a conversion artifact or a
change to the parser/locator identity.

Explicit offline downloads use Downloads' public DownloadResourceRuntime only.
Its descriptor comes from Library Resource/Asset metadata, independently of Reader
bootstrap. Android and iOS adapt storage, notifications and lifecycle; task creation,
identity/version deduplication, pause, resume, retry, transfer validation, atomic
publication and completion registration have one shared owner. Single files and
IMAGE_DIR page sets share one transfer mechanism; only resource organization differs.
Web uses the same original-asset download contract and lets the browser save it.
The asset response carries `X-Asset-Version` (`sizeBytes:mtimeMillis`). Explicit
Downloads sends the expected version on initial and resumed transfers. A mismatch
returns `412 ASSET_VERSION_CHANGED` before streaming; the client rejects a missing
or mismatched version header before opening a sink. This is independent of weak
ETag cache validation and never falls back to a complete online Reader transfer.

Reader can open completed original artifacts through Downloads' public contract.
Native Reader may select the visible Downloads transition only for the typed online
limitations described above. Ordinary retries request the failed chapter/page/range.
Web never invokes an original-file transfer from its online Reader. Only obsolete
online body caches/partials with identifiable provenance are removed; manual
Downloads, local imports, bookmarks and progress are preserved by this migration.

## 11. Verification requirements

Automated contracts must cover:

- mutation idempotency and monotonic revision;
- stale base revision producing a session remote notice without immediate replay;
- deterministic non-blocking startup restoration: explicit targets win; otherwise the newest valid exact location wins, server wins equal capture times, invalid pending state is retired, and newer local pending state rebases onto the fresh revision;
- absence of startup local/cloud/cancel dialogs and of legacy debounce, lease, `clientSequence`, applied-sequence, or quarantine state machines;
- progress GET null/200/304, revision ETag, same-client and same-anchor suppression;
- accepting a remote position only after exact post-navigation verification;
- the next genuinely different exact location rebasing onto the remote revision;
- 500 ms burst coalescing;
- single-flight latest-slot behavior;
- network failure preserving the latest durable pending mutation;
- all four Publication location round trips and morphology-specific post-navigation verification;
- progression, position, and percentage never counting as exact;
- identical book/resource progress surviving Publication fingerprint changes;
- PDF, comic, and audio exact positions;
- v1–v3 `410 Gone` and first-party v4-only paths;
- process-death recovery for pending state and fresh session reconstruction from bootstrap.
- Nav-to-NCX fallback, invalid navigation-node filtering, and body failure independence;
- source bytes remaining unchanged and no Reader derivative directory being created;
- MOBI/TXT in-memory Publication href and Locator conformance across platforms;
- cold open while non-current chapters/pages are blocked, with no original-file request,
  download task, complete-file artifact or continuing background transfer;
- oversized/unstructured TXT chapters, ignored Range, malformed length, interrupted
  responses, concurrent reads, cancellation, revision changes and account isolation;
- native visible download fallback, deduplication, resume, cancellation, storage failure,
  original target/progress restoration and no late opening after cancellation/account change;
- 2 GiB minus one / exactly 2 GiB / plus one admission, 64-bit totals and known allocation guards;
- local parse failure without automatic redownload or online/local loops;
- actual novel EPUB plus independent TXT measurements: server parse, first body,
  first readable view, transferred bytes and peak body cache. Results must identify
  platform/device and distinguish measured evidence from pending acceptance.

Android acceptance includes building and deploying the debug APK to an explicitly selected physical Android device, cold launching it, and running relevant instrumentation. iOS acceptance must use an `iosArm64`/`iphoneos` build and a connected physical iPhone or iPad. Simulator evidence is prohibited. Linux KMP compilation is useful static evidence but is not iOS runtime acceptance.

## 12. Security and observability

Reader routes preserve resource authorization and anti-enumeration behavior. External location JSON is bounded and validated before mapping. Logs may contain stable user/resource/correlation identifiers and outcome codes, but never book text, cookies, tokens, full locator payloads, or private filesystem paths.

The Reader shell remains native and owns lifecycle, accessibility, back/close,
navigation controls, table of contents, and preferences. Readium internals are
engine implementation details and never become an unrestricted application
bridge.

## 13. Unified reader settings (2026-08-28)

`packages/reader-contracts/reader-settings.json` is the only settings catalog.
Its ordered sections, stable IDs, Chinese/English labels, options, numeric
bounds and reading morphologies generate Web and KMP metadata. Native sheets
remain SwiftUI/Compose. iOS obtains the same metadata through KMP and resolves
generated native localization keys. Platform adapters may map editable field
names and SDK capabilities, but must not maintain an independent setting list.
`generate-reader-settings.py --check` detects metadata, localization and iOS
field-binding drift; the Web pretest gate runs it.

Preference storage is version **5**, independent of the unchanged Reader **v4**
exact-progress protocol. Values stay local to the device, server and account.
No preference API or cross-device synchronization is introduced. The Web storage
adapter migrates old line-height-only publisher flags to a disabled/off master;
KMP migrates native v3/v4 records while preserving the actual native master.
iOS uses that same decoder and no longer writes a duplicate `iosDraft`. Invalid
records are not overwritten on read. Legal custom values remain stored and are
displayed even when they are not preset choices. Reset replaces every reading
format's preferences in the current namespace, without touching progress,
bookmarks, downloads or other accounts.

The sole publisher setting is `preservePublisherStyles`, displayed as
“出版方样式” / “Publisher Styles” under Advanced Settings → Paragraph and Content
Styles. Native engines receive their public `publisherStyles` preference.
Publication-specific effectiveness comes from the SDK preference editor. The
pinned Web engine has no public master switch: Web displays off/disabled with
an explanation and keeps regular user fonts, theme and typography. It must not
simulate that master using CSS, document rewriting or bundled partial toggles.

The five themes and Web option values remain authoritative. Appearance contains
text typography or comic/PDF page width and zoom; Settings contains interface,
page turning, format layout, text optimization and the unified advanced groups.
The native-only gesture-animation setting is removed. Unsupported controls keep
their names and positions; saved values are not represented as effective values.
The SDK's fixed-on swipe behavior is explained explicitly. Native command
animation controls public navigation options, not the engine's swipe animation.

Android and iOS both use the existing preference writer and session:
**edit → persist locally → submit necessary public SDK preferences**. Submission
is not a pagination-completion signal. Preference changes must not poll for
layout, capture/compare visible paragraphs, navigate to restore an anchor, roll
back the renderer, recreate a Navigator, reopen/download a book, or introduce
settings loading UI. Genuine save/SDK errors remain errors. Normal opening,
TOC/bookmark jumps and exact progress restoration retain their own workflows.
Preference reflow observations remain excluded from progress persistence.

`apps/web/public/fonts/reader` remains the licensed font resource owner. Native
PingFang/Heiti/YaHei map to Source Han Sans, Songti to Source Han Serif and Kaiti
to LXGW WenKai, through the existing public font declarations. Identical labels
do not promise identical glyph metrics across platforms. SDK sources remain
unmodified and versions follow the approved baseline in section 10 (iOS 3.9.0);
no private API or layout compensation is added.

The pinned iOS PDF SDK exposes `fit`, but explicitly ignores width fit in its
paginated mode. This path stays disabled instead of changing reading mode or
claiming it works. Absolute zoom uses the existing public PDF/scroll view;
comic command animation uses public Navigator go options. Other comic layout,
negative spacing, smart optimization and fixed-layout capabilities without a
usable public interface remain disabled.

Current implementation and acceptance evidence, including device and SDK limits:
`docs/testing/reader-settings-unification-2026-08-28.md`. Compilation is not proof
of rendering effectiveness.

Bookmarks use the existing Reader v4 collection wire schema. Local state is
isolated by `serverIdentity + userId + resourceId + assetId + contentFingerprint`, retains
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

Local and Reader v4 exact positions are scoped by book and resource rather than
Publication fingerprint. Positions with the same semantic Readium anchor restore
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
shared `ReaderProgressPresentationUpdate` contract at application scope. The
event carries the complete, validated `PublicationLocation`; platform shells
must not replace it with a resource-only href, synthetic page key, percentage,
or chapter title. An open Book Detail projection applies a matching
namespace/book/resource update immediately, including overall progress, resource
progress, and chapter state, then refreshes the server representation without
replacing newer local state.
Book Detail also performs a non-blocking refresh whenever it becomes active.
Chapter state is derived from exact href/fragment first, then the server's
global chapter index and sort order. Duplicate titles are never navigation
identities, and overall percentage is not used to guess a chapter; 100 percent
is the sole exception and marks every chapter read.


## 15. Parser authority and failure preservation (2026-08-28)

The actual format parser/decoder decides whether bytes can be read. Application
prechecks must not reject NUL, strip trailing NUL, sniff PDF/image signatures, or
open an original with another parser merely to predict readability. A zero-byte
original is not above the size limit; the actual parser reports its empty/invalid
result. Storage owns containment, account isolation and atomic publication, not
format parsing. SDK versions follow the approved baseline in section 10; SDK
sources remain unmodified. Historical 3.8.0 acceptance records are not current pins.

Original bytes, in-memory TXT/FB2/MOBI Publications, existing chapter boundaries,
and native preference submission are preserved. No conversion artifact, implicit
complete download, synthetic chapter or typography validation is permitted.
Authentication, path safety, XXE/script/network isolation, transport/revision
contracts and explicit budgets remain application responsibilities, with actual
failure codes. The Reader error boundary retains stage, source and stable code;
original causes stay internal and never enter user-visible diagnostics. A generic
parser failure does not delete progress/downloads or select Download Center.

The status/code contract is owned by
`packages/reader-contracts/reader-http-error-statuses.json`, consumed by Web and
generated into KMP. Older NUL errors are receive-only compatibility, not rules.

This is a target policy, not a claim of complete migration. Original chapter
security decorators still require initial XML/head/body checks until fixed SDK
public interfaces can safely replace their isolation. Generated TXT/FB2 chapters
reuse the CSP template without the extra whole-chapter XML pass. The fixed iOS
comic decoder does not report UIImage decode failures, and remains unaccepted.
The implementation/evidence matrix is authoritative for current coverage:
`docs/testing/reader-parser-implementation-2026-08-28.md`.
