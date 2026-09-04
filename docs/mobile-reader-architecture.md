# Mobile Reader Architecture

Status: Reader v5 implementation in progress; cross-platform physical-device conformance pending
Last updated: 2026-09-04

This document is the authoritative architecture contract for the native Reader
and Reader v5 cross-platform progress integration. ADR 0028 owns the position
wire boundary. Historical Reader v4 exactness and conflict rules are not
compatibility requirements.

## 1. Scope and position ownership

The Reader capability supports these presentation morphologies:

- reflowable publications use the Locator emitted by Readium;
- PDF and comics use their navigator Locator and page presentation;
- audio uses file/chapter identity and playback milliseconds.

The active Reader engine exclusively defines the Locator. Application code does
not prove that it contains a selector, fragment, text anchor, page or other
application-defined identity. A valid engine Locator can contain empty text and
unknown fields.

The native apps do not embed the Web Reader. Web, Android, and iOS share semantics and wire contracts while keeping platform-owned engines and local exact stores.

## 2. Dependency direction

```text
presentation -> Reader application ports/use cases -> Reader domain
engine/storage/network adapters -> Reader application ports + domain
composition root -> presentation + application + adapters
```

Shared Reader domain code must not import UI, Android/iOS, Readium, browser,
filesystem, HTTP, or database types. Engine Locators cross the shared boundary as
opaque JSON objects. Other capabilities use only Reader public APIs.

## 3. Publication diagnostics and progress identity

Reader v5 retains these Publication diagnostics:

- original source file SHA-256;
- parser identifier which generated the Publication content structure;
- normalization identifier which generated stable reading order, hrefs, and DOM.

Navigator SDK versions are build diagnostics and are not added to the Locator
wire object. None of these fingerprint fields participates in reading-progress
ownership or validation. Progress is
owned by the server-authorized `bookId + resourceId`; an asset, parser, or
normalization change does not create a new progress slot or block restoration.

For EPUB, MOBI-family, and TXT, matching content identity means that every client
uses the same source-format parser contract and produces compatible engine
Locators. Runtime DOM need not be byte-identical. The
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

## 4. ReaderPositionReport

Reader v5 stores one `ReaderPositionReport` containing:

- the complete opaque JSON-object Locator serialized by the active engine;
- `displayPercent` and normalized `totalProgression` reported independently;
- nullable current href, chapter, page and playback presentation.

The Locator's compact UTF-8 representation is limited to 64 KiB. Empty strings,
nulls and unknown extensions are preserved. No component outside the Reader
adapter reads its keys. Presentation is never used for navigation, and Locator
fields are never used to calculate presentation.

## 5. Reader v5 server contract

First-party clients use only:

```text
GET /api/reader/v5/resources/{resourceId}/bootstrap
GET /api/reader/v5/resources/{resourceId}/progress
PUT /api/reader/v5/resources/{resourceId}/progress
GET|PUT /api/reader/v5/resources/{resourceId}/reading-status
GET|PUT /api/reader/v5/resources/{resourceId}/bookmarks
```

Reader v1–v4 routes return `410 Gone`. Mobile compatibility advertises
`readerV5=true` and schema version 5.

The progress request contains:

```json
{
  "schemaVersion": 5,
  "clientId": "stable-client-id",
  "mutationId": "58a3ac3c-52d0-41ed-9c85-0524b532f25b",
  "capturedAtEpochMillis": 1786500000000,
  "position": {
    "locator": {},
    "presentation": {
      "displayPercent": 99,
      "totalProgression": 0.99,
      "currentHref": "OEBPS/Text/backcover.xhtml",
      "chapter": {"href": "OEBPS/Text/backcover.xhtml", "title": "封底", "index": 19},
      "page": null,
      "playback": null
    }
  }
}
```

The response contains `acceptedRevision` and the current snapshot. The server
does not reject a Locator because an application-defined anchor is absent.

The lightweight progress GET returns the current snapshot or `null`. It emits a
revision ETag and accepts `If-None-Match`; unchanged state returns `304`. It is
used only while a Reader session is open and is checked after opening, on
foreground entry, and on network recovery. There is no polling, WebSocket, or SSE.

## 6. Server persistence

Reader v5 has independent current-snapshot and mutation-receipt tables. Revision
increases monotonically in transaction commit order. Mutation receipts make
retries idempotent.

The repository saves:

- the opaque Locator JSON and client-reported presentation;
- client and mutation identity;
- client capture time for diagnostics only;
- the current revision and server receive time;
- a digest used only to detect mutation-id reuse.

There is no `baseRevision`. The last successfully committed mutation is current.
The authorized book and resource are the progress identity. Locator content and
Publication fingerprint differences never reject a progress read or write. v4
rows are left untouched and are never read by v5.

## 7. Local save and upload

All clients implement the same lifecycle:

1. The engine emits a real location change.
2. A 500 ms trailing debounce coalesces continuous movement.
3. One timestamp is created.
4. The complete position report is committed locally.
5. The position report and latest-only pending mutation commit atomically.
6. Only after local commit, one single-flight v5 PUT is attempted.
7. Success clears only the pending mutation named by the acknowledgement.
8. Network failure preserves the same mutation id and request body for retry.

Each platform retries durable pending work on network recovery, foreground entry,
and Reader exit. During an in-flight request, one durable latest slot retains
only the newest report. Pending state survives termination. Preference reflow is
not user movement, but any Locator emitted for a real Reader location change can
be uploaded without application exactness proof.

## 8. Startup and session restoration policy

An explicit deep link, chapter/page request, or bookmark always wins. An authenticated
Reader entry fetches a fresh lightweight bootstrap when network is available.
When content is already local, bootstrap and local parsing remain independent.
The deterministic order is explicit target, local pending v5 report, server v5
report, then publication start. A pending state for another book or resource is
ignored.

The selected Locator is deserialized and passed directly to the active SDK.
Presentation fields never participate. If the SDK rejects or cannot navigate to
it, the client reports `LOCATION_RESTORE_FAILED` and does not repair or overwrite
the saved value. A newer remote write never moves an already open Reader; it is
considered on the next entry.

## 9. Local persistence

Reader v5 uses a new local persistence namespace. No v4 progress, pending
mutation or conflict document is imported, scanned, reset or re-uploaded. Reader
preferences, local imports and completed Downloads are separate capabilities and
are not removed by the protocol cutover.

Native Downloads and the Web Reader publication store verify the original authorized
file before a reflowable Reader opens it. Parser and normalization identifiers remain
diagnostics and never create a second persisted reading representation.

## 10. Platform adapters

Android uses Readium Kotlin Toolkit 3.3.0. iOS pins official Readium Swift Toolkit 3.9.0 to revision `de07026e9f825a5791f27a7ac4cd6bb1a784ab8d`. Both serialize the complete public Readium Locator directly into the opaque v5 field. They add no engine/platform/version wrapper and do not project Locator anchors into shared domain fields.

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
behind the adapter and emits the public location-change Locator as one object;
failure to read the frame fails closed and disables position capture. Reflowable source
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

Reader v5 bootstrap for a reflowable resource is metadata/progress only. It neither
opens a Publication nor materializes navigation and it exposes no manifest, positions
or chapter-resource URL. Server parsers remain bounded infrastructure for import,
metadata and content safety; they never validate progress Locator fields and are not a first-party
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
support explicit scrubber navigation. They are reported independently in
presentation and never replace the engine Locator. Parser validation exceptions crossing KMP into
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
manual Downloads and local imports remain separate from the v5 progress namespace.

## 11. Verification requirements

Automated contracts must cover:

- mutation idempotency, mutation-id reuse rejection and monotonic revisions assigned in server commit order;
- deterministic non-blocking startup restoration: explicit target, local pending v5 report, server v5 report, then publication start;
- absence of `baseRevision`, revision-conflict `409`, local/cloud/cancel dialogs and remote exactness arbitration (mutation-id reuse still returns its dedicated `409`);
- progress GET null/200/304 and revision ETag;
- 500 ms burst coalescing;
- single-flight latest-slot behavior;
- network failure preserving the latest durable pending mutation;
- all four Locator JSON round trips preserving empty, null and unknown values;
- presentation disagreement never causing Locator rejection or server recomputation;
- identical book/resource progress surviving Publication fingerprint changes;
- PDF, comic and audio Locator plus presentation snapshots;
- v1–v4 `410 Gone` and first-party v5-only paths;
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

Reader routes preserve resource authorization and anti-enumeration behavior.
Locator JSON is checked only as an object and for the 64 KiB transport/storage
bound; its fields are not validated or mapped. Logs may contain stable
user/resource/correlation identifiers, revision, byte count and outcome codes,
but never book text, cookies, tokens, Locator payloads, or private paths.

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

Preference storage is version **6**, independent of the Reader **v5** position
protocol. Values stay local to the device, server and account.
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

Bookmarks use the Reader v5 `ReaderPositionReport`. Local state is
isolated by `serverIdentity + userId + resourceId + assetId + contentFingerprint`, retains
the engine Locator and independent presentation for local jumps, and uploads the
same report without a morphology projection. Every mutation atomically replaces the
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

Local and Reader v5 positions are scoped by book and resource rather than
Publication fingerprint. Startup uses a local pending report before the current
server report. Otherwise the server report restores automatically. Server order
is its monotonic commit revision; client capture time never overrides it.
Navigator initialization and preference reflow emissions are not user progress.

After every successful local progress transaction the Reader publishes the
shared `ReaderProgressPresentationUpdate` contract at application scope. The
event carries the same independently captured presentation stored beside the
opaque Locator. An open Book Detail projection applies a matching
namespace/book/resource update immediately, including overall progress, resource
progress, and chapter state, then refreshes the server representation without
replacing newer local state.
Book Detail also performs a non-blocking refresh whenever it becomes active.
Chapter, page and href state comes directly from presentation. Neither the
backend nor the detail UI derives it from Locator fields.


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
