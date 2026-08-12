# Mobile Reader Architecture

Status: R1–R4 implemented; iOS physical-device acceptance pending
Last updated: 2026-08-13

This document is the architecture contract for the native Reader and its Reader v4 cross-platform progress integration. Read it with the Mobile phase specifications and `docs/mobile-app-development-global-guidelines.md` before changing Reader domain, storage, engines, navigation, or UI.

## 1. Scope and phase boundary

The Reader capability supports these location morphologies:

- reflowable publications use resource, text, logical-position, percentage, and optional engine anchors;
- PDF and comics use standard page positions;
- audio uses file/chapter identity and playback milliseconds.

R1 defines the platform-independent domain. R2 provides the Android Readium EPUB reader. R3 provides the equivalent iOS Readium reader. R4 adds authenticated Reader v4 bootstrap/download, exact local progress, best-effort snapshot upload, cross-platform restoration, and the Work Detail entry.

The native apps do not embed the Web Reader. Web, Android, and iOS share semantics and wire contracts while keeping platform-owned engines and local exact stores.

## 2. Dependency direction

```text
presentation -> Reader application ports/use cases -> Reader domain
engine/storage/network adapters -> Reader application ports + domain
composition root -> presentation + application + adapters
```

Shared Reader domain code must not import UI, Android/iOS, Readium, Foliate, browser, filesystem, HTTP, or database types. Engine-specific locators are validated JSON objects kept behind adapters. Other capabilities use only Reader public APIs.

## 3. Content identity

Two fingerprints have different purposes and must never be conflated:

- `contentFingerprint` on the v4 snapshot is the opaque server volume-version token. It tells the server whether an uploaded location belongs to its current publication.
- the structured location fingerprint contains original file SHA-256, parser version, and normalization version. It tells a client whether exact anchors can be applied to its locally opened publication.

The exact local record identity is:

```text
serverIdentity + userId + clientId + volumeId + localContentFingerprint
```

`authorizationVersion` is deliberately absent. Reauthentication does not hide a valid position for the same client and local publication. A different account, client, server, volume, or local content interpretation cannot reuse that exact record.

## 4. Location model

For a reflowable publication, a location may contain any useful combination of:

- `resourceKey`;
- resource-local `progression` in `0...1`;
- logical `position`;
- bounded exact/prefix/suffix text quote;
- structured local content fingerprint;
- bounded engine locator.

At least one usable anchor is required. `progression` never represents whole-book progress. Whole-book progress is the snapshot `percent` in `0...100`.

An engine locator has a stable engine (`readium` or `foliate`), platform (`android`, `ios`, or `web`), version, and JSON-object payload no larger than 64 KiB. Strings containing encoded JSON and binary payloads are invalid at the wire boundary.

PDF, comic, and audio locations keep their standard page/page-index/playback-millisecond anchors and may add an engine locator when useful.

## 5. Reader v4 server contract

First-party clients use only:

```text
GET /api/reader/v4/volumes/{volumeId}/bootstrap
PUT /api/reader/v4/volumes/{volumeId}/progress
PUT /api/reader/v4/volumes/{volumeId}/reading-status
GET|PUT /api/reader/v4/volumes/{volumeId}/bookmarks
```

Reader v1–v3 routes return `410 Gone`. Mobile compatibility advertises only `readerV4=true` and schema version 4.

The progress request and returned `progressSnapshot` contain:

```json
{
  "schemaVersion": 4,
  "clientId": "stable-client-id",
  "updatedAtEpochMillis": 1786500000000,
  "percent": 32.7,
  "location": null,
  "contentFingerprint": "server-volume-version"
}
```

`location` is nullable so a client with no trustworthy anchor can still upload a percentage. The contract has no mutation id, client sequence, device id, applied flag, event receipt, or conflict-ordering metadata.

## 6. Server persistence

`LibraryReadingProgress` is the only automatic-progress truth, with one row per user and volume. Every authorized, valid PUT unconditionally overwrites the snapshot in request-arrival order, including a lower percentage or older client timestamp.

The repository saves:

- percentage and normalized location JSON;
- client id;
- the client timestamp as `progressedAt`;
- the current server content token;
- server receive time as the row `updatedAt`;
- the existing `UserMediaHistory` projection.

There is no progress event table, sequence waterline, idempotency registry, device tie-break, retry receipt, or client-time ordering rule.

If the request token is stale, the server still overwrites client id, client timestamp, and percentage, but discards the uploaded location and returns the current token. If content changes after an exact location was saved, bootstrap returns its percentage with `location=null` and performs no implicit write. Bookmarks keep their independent exact-location contract.

## 7. Local save and upload

All clients implement the same lifecycle:

1. The engine emits a real location change.
2. A 500 ms trailing debounce coalesces continuous movement.
3. One timestamp is created.
4. The full exact location is committed locally.
5. Only after local commit, one v4 PUT is attempted.
6. A successful response updates the in-memory server snapshot and never replaces the local engine locator.
7. A failed request is discarded immediately.

There is no persistent outbox, retry, lease, quarantine, or sequence counter. During an in-flight request, one in-memory pending slot keeps only the newest stable update. When the request finishes, that slot is sent once. Unsent memory state may be lost on process termination.

Background/exit cancels an untriggered debounce, saves once, and makes a bounded upload attempt. It must not resend a snapshot already sent when no newer location exists. If a trustworthy whole-book percentage cannot be calculated, the client saves exact local progress but does not upload that change.

## 8. Restoration policy

An explicit deep link, chapter/page request, or bookmark always wins. Otherwise the client compares local and server timestamps:

- local newer or equal: restore the local exact locator;
- server newer: try remote candidates in order;
- neither: open at the publication start.

Remote reflow candidates are:

1. compatible engine locator;
2. resource key plus resource progression;
3. text quote;
4. logical position;
5. whole-book percentage;
6. publication start.

If the remote structured location fingerprint does not match the local publication, all exact anchors are skipped and restoration begins at percentage. Android/iOS prefer compatible Readium payloads. Web prefers Foliate and may extract a recognizable CFI from Readium payloads before using public anchors.

Remote restoration never fabricates an exact local locator. The local exact record changes only after the engine completes navigation and emits a real position.

## 9. Local migration

Android and iOS keep the versioned `ermao.reader-progress` v1 local document and migrate exact records from authorization-scoped keys to the stable exact identity. Web stores exact progress in the `exact-progress` IndexedDB store.

The Web database upgrade copies the latest usable exact location per identity from the retired progress outbox, then removes progress outbox, lease, and quarantine stores in the same version-change transaction. Native migrations likewise commit the new exact record before deleting old rows/files. A failed commit preserves the legacy source.

Publication download, bounded streaming, file SHA-256, parser fingerprinting, path/symlink containment, temporary-file validation, and atomic installation remain unchanged by progress simplification.

## 10. Platform adapters

Android uses Readium Kotlin Toolkit 3.3.0. iOS pins Readium Swift Toolkit 3.8.0 to revision `f7d10d2bf5876408feae14d634416f69d1473fd8`. Both map a complete Readium Locator into the engine payload and expose semantic public anchors without leaking Readium types into shared domain code.

Web Foliate includes CFI, section, and internal progress only inside its engine payload. It fills public `resourceKey` and resource-local `progression` only when their meaning is known.

Native publication downloads reuse authenticated cookie storage, stream into an app-private staging file, validate declared and actual size, optional SHA-256, MIME/publication type, and atomically install the result. Redirect, traversal, symlink, empty-body, overflow, truncation, cancellation, and oversized-error cases fail closed.

## 11. Verification requirements

Automated contracts must cover:

- later lower progress overwriting earlier higher progress;
- no server event/sequence/idempotency/device ordering;
- 500 ms burst coalescing;
- single-flight latest-slot behavior;
- network failure leaving exact local state intact with no retry state;
- Readium and Foliate payload round trips plus public-anchor/percentage fallback;
- local timestamp ties winning;
- mismatched publication fingerprints using percentage only;
- PDF, comic, and audio exact positions;
- v1–v3 `410 Gone` and first-party v4-only paths;
- migration commit-before-cleanup behavior.

Android acceptance includes building and deploying the debug APK to the dedicated test emulator, cold launching it, and running relevant instrumentation. iOS acceptance must use an `iosArm64`/`iphoneos` build and a connected physical iPhone or iPad. Simulator evidence is prohibited. Linux KMP compilation is useful static evidence but is not iOS runtime acceptance.

## 12. Security and observability

Reader routes preserve resource authorization and anti-enumeration behavior. External location JSON is bounded and validated before mapping. Logs may contain stable user/volume/correlation identifiers and outcome codes, but never book text, cookies, tokens, full locator payloads, or private filesystem paths.

The Reader shell remains native and owns lifecycle, accessibility, back/close, navigation controls, table of contents, and preferences. Readium WebView or Foliate internals are engine implementation details and never become an unrestricted application bridge.
