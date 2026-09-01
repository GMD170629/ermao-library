# Mobile Reader Architecture

Status: Reader v4 download-then-read contract implementation in progress; physical-device conformance pending
Last updated: 2026-09-01

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
unpacked publication directory. Every first-party reflowable Reader validates and
opens a complete original through its local parser. MOBI-family and TXT parsers expose
bounded virtual Publication resources in memory; EPUB reads its original ZIP through
a bounded local fetcher. `packages/reader-contracts/reader-safety-policy.json`
owns all safety decisions. Delivery applies generated decisions and platform
defenses; `SANITIZE` may remove dangerous authored content from the in-memory
Publication but never changes the stored original or persists a derivative.

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

An explicit deep link, chapter/page request, or bookmark always wins. An authenticated
Reader entry fetches a fresh lightweight bootstrap when network is available. When content is already local, bootstrap
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

Native Downloads and the Web Reader publication store verify the original authorized
file before a reflowable Reader opens it. Parser and normalization identifiers remain
diagnostics and never create a second persisted reading representation.

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
failure to read the frame fails closed and disables exact sync. Reflowable source
resources come from the account/version-scoped browser original store, never a
server RWPM or chapter endpoint.

The shared `ReaderDeliveryMode` has three values. `DOWNLOAD_ORIGINAL` covers EPUB,
FB2, TXT, MOBI, AZW, AZW3 and PRC; `STREAM` covers PDF and comics; unsupported
formats do not enter Reader. The former online-readability gate and online-limit
fallback are removed. PDF delivery follows `PDF.RANGE_PROTOCOL` and rejects an
ignored Range before body consumption. Native PDFium engine requests are distinct
from HTTP spans: requests that exceed the 8 MiB volatile cache route to the canonical
Downloads runtime, then install the verified local file in the same PDFium session.
Web pdf.js and comic page delivery remain online-first.

Android and iOS use the repository-owned PDFium adapter for both local and streamed
PDF opening. The former local Readium/PDFKit versus remote PDFium split is removed.
Web continues using pdf.js. These engines expose normalized findings to the same
generated PDF policy; SDK defaults may not silently enable actions forbidden by
`PDF.DISABLE_ACTIVE_CONTENT`.

Native Reader uses `ReaderLaunchCoordinator` for verified-local, required-download,
stream and unavailable decisions. Admission uses
`COMMON.ORIGINAL_MAX_BYTES`; IMAGE_DIR member totals use the applicable comic
budget rules. This is not a guarantee that every admitted file can open. Whole-array
platform limits, XML/decompression/image safety limits and engine failures remain
independent. No synthetic chapter splitting, format conversion, persisted unpacked
publication, new indexing or incremental parser is introduced.

Every missing reflowable original selects the visible loading transition. It observes
or creates an account-owned Downloads task and shows cover/title, queue/download/parse
states, real bytes and percentage, cancel and retry without an explanatory download
reason. The only native complete-file transfer remains `DownloadResourceRuntime` /
`KtorDownloadsGateway`; Reader has no download adapter of its own. Verified artifacts
open without network and remain managed by Downloads. Closing detaches the launch and
pauses only its owned transfer; late completion cannot open a closed or different-account
reader. A missing/stale artifact is rebuilt through Downloads, while local parse failure
never loops or redownloads. PDFium's transparent materialization has no transition UI
and creates a normal Download Center task that continues after Reader close; ordinary
PDF errors and all comic errors do not select it.

The original chapter target, or the latest persisted Reader progress, is restored after download using the existing progress owner. All file lengths, offsets and totals use 64-bit arithmetic. Product admission policy is passed to C through explicit open options; no duplicated native file gate remains in Reader. TXT/FB2 full materialization and MOBI parser memory behavior remain existing engine constraints; OS memory termination cannot be reliably recovered.

Reader v4 bootstrap for a reflowable resource is metadata/progress only. It neither
opens a Publication nor materializes navigation and it exposes no manifest, positions
or chapter-resource URL. Server parsers remain bounded infrastructure for import,
metadata and exact Locator validation where still consumed; they are not a first-party
body-delivery fallback. Corruption, authentication and parser-limit errors remain
distinct.

Web stores complete originals in a dedicated Reader Cache Storage adapter keyed by
authorization namespace, resource, asset and `size:mtime` version. It has no persistent
download task, pause or resume state. Cancellation aborts and deletes the incomplete
entry; a later attempt starts at zero. Cold opening still requires fresh authorization
and Reader metadata. See ADR 0025.

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

Every reflowable native Publication uses its parser-specific local positions service.
The Web local adapters generate the same stable reading-order href and locator contract.
These logical positions
support explicit scrubber navigation only: percentage is still never an exact
restoration or upload identity. Parser validation exceptions crossing KMP into
Swift must be declared with `@Throws` and mapped to a stable Reader error,
including blank/invalid TXT input.

Library persists and exposes MOBI-family originals only by their exact
`MOBI`/`AZW`/`AZW3`/`PRC` format. Reader bootstrap, required download, local opening and
restoration use that exact value directly. Generic `KINDLE` is unsupported
and is never inferred from a filename or accepted as an online/offline format.

Pinned libmobi's legacy MOBI6 HTML can omit the XHTML default namespace and the
`mbp` prefix declaration. Native adapters bind these on the root element before
the security decorator, otherwise WebKit can render an XML error document.
`MobiMarkupEnvelope` changes only the XML envelope in memory. Existing namespace
declarations are preserved. The safety adapter may subsequently sanitize the
in-memory body under ADR 0026; original bytes and resource hrefs remain unchanged,
and any semantic projection change requires a new normalization identifier. This
is not a conversion artifact.

Native original downloads use Downloads' public DownloadResourceRuntime only.
Its descriptor comes from Library Resource/Asset metadata, independently of Reader
bootstrap. Android and iOS adapt storage, notifications and lifecycle; task creation,
identity/version deduplication, pause, resume, retry, transfer validation, atomic
publication and completion registration have one shared owner. Single files and
IMAGE_DIR page sets share one transfer mechanism; only resource organization differs.
Web uses the same original-asset descriptor and media contract through its Reader-owned
browser publication store.
The asset response carries `X-Asset-Version` (`sizeBytes:mtimeMillis`). Explicit
Downloads sends the expected version on initial and resumed transfers. A mismatch
returns `412 ASSET_VERSION_CHANGED` before streaming; the client rejects a missing
or mismatched version header before opening a sink. This is independent of weak
ETag cache validation and never falls back to server-delivered reflowable bodies.

Reader opens completed original artifacts through Downloads' public contract. Native
Reader selects the transition for every missing reflowable original. Ordinary PDF and
comic retries request the failed page/range and never create an implicit task. Web Reader
performs its original-file transfer directly into the browser store and reads that body.
Only obsolete online body caches/partials with identifiable provenance are removed;
manual Downloads, local imports, bookmarks and progress are preserved by this migration.

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
- a slow original response showing increasing bytes/percentage while Reader remains unopened,
  followed by local reading with manifest/positions/chapter endpoints blocked;
- interrupted responses, malformed length/version/MIME, cancellation without partial
  publication, cache/task reuse, missing-file rebuild and account isolation;
- native required-download deduplication, resume, cancellation, storage failure,
  original target/progress restoration and no late opening after cancellation/account change;
- PDF/comic online retries and audio playback creating no implicit reflowable download task;
- below / exactly at / above `COMMON.ORIGINAL_MAX_BYTES`, 64-bit totals and known allocation guards;
- local parse failure without automatic redownload or online/local loops;
- actual novel EPUB plus independent TXT measurements: original transfer, local parse,
  first readable view, transferred bytes and parser memory. Results must identify
  platform/device and distinguish measured evidence from pending acceptance.

Android acceptance includes building and deploying the debug APK to an explicitly selected physical Android device, cold launching it, and running relevant instrumentation. iOS acceptance must use an `iosArm64`/`iphoneos` build and a connected physical iPhone or iPad. Simulator evidence is prohibited. Linux KMP compilation is useful static evidence but is not iOS runtime acceptance.

## 12. Security and observability

Reader routes preserve resource authorization and anti-enumeration behavior. External location JSON is bounded and validated before mapping. Logs may contain stable user/resource/correlation identifiers and outcome codes, but never book text, cookies, tokens, full locator payloads, or private filesystem paths.

The versioned Reader safety contract in `packages/reader-contracts` is the sole
owner of formats/MIME, limits, algorithms, `ruleId`, filtering actions and error
codes across backend, Web, Android and iOS. KMP exposes generated policy data to
iOS through `ErmaoShared`. Native/Web code implements only fact detectors,
generated decisions and declared platform defenses; it never carries a private
allowlist, threshold or fallback parser. Unavailable enforcement is an explicit
`ENGINE_*` or `PLATFORM_*` conformance failure. The contract is bundled and its
canonical digest is checked by CI; Reader bootstrap does not negotiate it.

The Reader shell remains native and owns lifecycle, accessibility, back/close,
navigation controls, table of contents, and preferences. Readium internals are
engine implementation details and never become an unrestricted application
bridge.

## 13. Unified reader settings (2026-08-28)

`packages/reader-contracts/reader-settings.json` is the only settings catalog.
Its ordered sections, stable IDs, Chinese/English labels, options, numeric
bounds, reading morphologies, availability rules and disabled reasons generate
the Web and KMP metadata and resolvers. Native sheets remain SwiftUI/Compose.
iOS obtains the same metadata and availability decisions through KMP and resolves
generated native localization keys. Platform adapters may map editable field
names and SDK capabilities, but must not maintain an independent setting list or
availability policy. `generate-reader-settings.py --check` detects metadata,
localization and iOS field-binding drift; the Web pretest gate runs it.

Preference storage is version **6**, independent of the unchanged Reader **v4**
exact-progress protocol. Values stay local to the device, server and account.
No preference API or cross-device synchronization is introduced. Web, Android
and iOS read only the current V6 record from their stable namespace. A record
without the current `schemaVersion` or one rejected by the current decoder is
ignored and is not overwritten. Accepted records use the current canonical
representation. Legal custom values remain stored and are displayed even when
they are not preset choices. Reset replaces every reading format's preferences
in the current namespace, without touching progress, bookmarks, downloads or
other accounts.

The sole publisher setting is `preservePublisherStyles`, displayed as
“出版方样式” / “Publisher Styles” under Advanced Settings → Paragraph and Content
Styles. Native engines receive their public `publisherStyles` preference.
Publication-specific effectiveness comes from the SDK preference editor. Web
implements the same bounded semantic at its presentation boundary: enabling it
releases publisher-owned font family, weight, letter spacing, line height,
paragraph indentation/spacing and alignment. Theme colors, font size, page
geometry, reading mode and spread remain reader-owned. The released controls
stay visible and retain their saved values while contextually unavailable;
disabling Publisher Styles applies those values again without reopening or
navigating the publication.

`textPageWidth`, `comicPageWidth` and `pdfPageWidth` are logical widths: CSS px
on Web, dp on Android and pt on iOS. At an available width of 640 or less the
Navigator uses the full width and the control is contextually unavailable. On
wider layouts only the Navigator content container is centered and constrained
to `min(availableWidth, savedWidth)`; controls, gestures and safe areas retain
the full viewport. The surrounding canvas uses the active Reader palette.

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

In continuous scrolling mode, app-owned Previous/Next commands move the current
content viewport by the shared navigation-policy fraction. At a resource edge
they navigate to the adjacent original reading-order resource and position its
near edge; the first and last resources do not wrap. Toolbar, tap-zone and
keyboard commands share the existing session navigation queue and link-navigation
owner, while left/right preserve LTR/RTL semantics. Native adapters use bounded,
one-shot WebView geometry operations because the SDK has no public viewport-turn
command; they do not rewrite publication content or recreate the Navigator.
Paginated commands retain the SDK's ordinary page-turn behavior. This rule does
not alter SDK-owned VoiceOver scrolling.

`apps/web/public/fonts/reader` remains the licensed font resource owner. The three
font choices are PingFang, Songti and Kaiti. Native PingFang maps to Source Han
Sans, Songti to Source Han Serif and Kaiti to LXGW WenKai, through the existing
public font declarations. Identical labels
do not promise identical glyph metrics across platforms. SDK sources remain
unmodified and versions follow the approved baseline in section 10 (iOS 3.9.0);
no private API or layout compensation is added.

The pinned iOS PDF SDK exposes `fit`, but explicitly ignores width fit in its
paginated mode. This path stays disabled instead of changing reading mode or
claiming it works. Absolute zoom uses the existing public PDF/scroll view;
comic command animation uses public Navigator go options. Other comic layout,
negative spacing, smart optimization and fixed-layout capabilities without a
usable public interface remain disabled.

Compilation is not proof of rendering effectiveness. Verification must include
the generated-contract check, platform tests and the relevant real-reader path.

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
and native preference submission are preserved. Reflowable reading requires the
verified complete original, but no conversion artifact, persisted unpacked publication,
synthetic chapter or typography validation is permitted.
Authentication and root/path ownership remain their existing capability
responsibilities. XXE/script/network isolation, transport/revision decisions and
Reader budgets come from the generated Reader safety policy and are enforced by
platform adapters with actual rule IDs and failure codes. The Reader error boundary retains stage, source and stable code;
original causes stay internal and never enter user-visible diagnostics. A generic
parser failure does not delete progress/downloads or select Download Center.

HTTP status/code compatibility remains owned by
`packages/reader-contracts/reader-http-error-statuses.json`, consumed by Web and
generated into KMP. Content security semantics are owned by
`reader-safety-policy.json`. Older NUL errors are receive-only compatibility, not rules.

All chapter security decorators must now consume the generated policy and report
their conformance fixtures. CSP, XML parser flags, scheme handlers, PDFium and
WebView/WKWebView isolation remain implementation mechanisms, not semantic rule
owners. A fixed iOS decoder or SDK limitation remains unaccepted until physical-
device conformance demonstrates the required generated action. Historical
implementation evidence remains useful but is superseded where it describes a
platform-owned policy.
