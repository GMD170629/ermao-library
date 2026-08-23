# ADR 0011: Cross-format exact Reader progress

Status: Superseded in Mobile identity and persistence terms by ADR 0020; exact-location semantics remain accepted
Date: 2026-08-14

## Context

Reader v4 has not been released and has no production data. Its earlier design
treated engine locators as optional hints, allowed percentage-only writes,
silently replaced progress by request arrival order, and discarded failed
uploads. That model cannot support the unified Readium platform's required
cross-device continuation semantics.

The Web/iOS POC demonstrates that Readium can exchange a Locator for the same
normalized Publication and return to the same visible DOM block across layout,
viewport, font, and pagination changes. It does not prove identical visual page,
line, character offset, coordinate, or pixel. Android and literal six-direction
exchange still require independent evidence.

## Decision

Reader v4 defines a renderer-neutral `PublicationLocation` discriminated union.
Its variants are `reflowable`, `pdf`, `comic`, and `audio`; every variant carries
the same exact `PublicationFingerprint`.

Exact reflowable continuation is the same DOM block or unique text anchor in the
same Publication resource. Its required Readium engine locator contains:

- `engine=readium` and `platform=web|android|ios`;
- the Navigator version for diagnostics;
- a JSON-object Readium Locator payload, never a JSON string containing JSON;
- an `href` plus a CSS selector, fragment/CFI, or bounded uniquely verifiable
  text anchor.

PDF identity is a zero-based canonical page index plus a required page-local
progression normalized to four decimals. Comic identity is a zero-based page
index plus the canonical safe reading-order resource href. Audio identity is a
file id, optional chapter id, and playback milliseconds. Their optional engine
locators aid navigation and diagnostics but do not participate in identity.

The complete Publication location is limited to 64 KiB. `highlight` is limited to 512 characters and
`before`/`after` to 256 characters each. Progression, logical position, and
whole-publication percentage are diagnostic or presentation values and are not
exact anchors.

Reading progress is owned by the server-authorized `workId + volumeId`.
Original file SHA-256, content parser identifier, and normalization identifier
remain attached to the Publication location for download verification and
diagnostics, but they do not participate in progress ownership, validation,
conflict detection, or restoration. A file or parser change does not create a
new progress slot.

After navigation, the destination recaptures its location and compares the
morphology-specific canonical identity. For reflowable content, `href` and the
selector, fragment/CFI, or uniquely normalized text must resolve to the same
block. A successful navigation API result alone is not proof.

Reader v4 writes use `baseRevision` and a UUID `mutationId`. Revision is
monotonic per user and volume, idempotent replays return the original result,
and a stale base revision returns `409 READER_PROGRESS_CONFLICT` with the current
server snapshot. The server never silently resolves a conflict and never
applies a forward-only rule. Client capture time is diagnostic only.

Each client atomically persists its exact Publication location and latest-only pending
mutation before networking. Network loss, process termination, and foreground
transitions preserve pending work. Online startup always refreshes bootstrap and
uses the latest server position unless a durable local pending mutation exists.
When that pending mutation and the server diverge, the user must choose local,
cloud, or cancel before Reader opens.

After Reader opens, lifecycle checks use the revision ETag progress endpoint.
A newer revision from another client becomes a session-only, non-modal notice.
It never moves the Navigator automatically. Accepting it requires exact
post-navigation verification. Continuing to a genuinely different exact block
rebases a new mutation onto that remote revision; the rejected stale mutation is
not replayed. Dismissing a notice ignores only that revision for the current
session. The server-confirmed revision is persisted before pending work is cleared.

The language-neutral contract and fixtures live in
`packages/reader-contracts`. Python, TypeScript, Kotlin, and Swift each validate
untrusted JSON at their boundary and map it into renderer-neutral domain values.
Readium SDK types remain platform adapter details.

Reflowable content identity uses Locator DOM Projection v2 before Navigator
decoration. It contains ordered reading resources plus the complete `body`
element tree, author IDs and normalized locator-block text. It excludes `head`,
platform CSP and Readium runtime nodes. Equal fingerprints mean equal
projections, not byte-identical live WebView DOMs.

EPUB preserves the validated author body and uses `epub-package:1` plus
`shuku-epub-locator-dom-v2`. MOBI-family publications use the single pinned
`ermao_mobi_*` ABI and `ermao-mobi-core-v1+shuku-locator-dom-v2`; no hidden EPUB
is generated. TXT uses `shuku-txt-parser-v1` plus
`shuku-txt-publication-v2`, with the checked-in KMP chapter and XHTML rules as
the semantic source of truth. Platform security adapters may decorate `head`
but must never delete, reparent or reserialize body content.

## Consequences

Reader v4's earlier untagged Locator envelope, Foliate engine, percentage-only
progress, server content token, arrival-order overwrite, non-durable upload,
outbox migration, and percentage fallback contracts are removed rather than
migrated. Because v4 was unreleased, old server progress and mutation receipts
are deleted and old client exact/pending/conflict documents are rejected. Durable
conflict documents are not part of the replacement contract: startup decisions
are modal and session remote notices are ephemeral.

`displayPercent` remains available for progress bars, library display, and
statistics. It must never be consumed by automatic continuation code.

When exact restoration fails after applying the saved position to the current
work and volume, the client reports that outcome and may offer
explicit nearby-position or chapter navigation. Such user-directed navigation
is never reported as exact synchronization.

PDF, comic/CBZ, and audio anchors use the same work/volume ownership, revision,
durability, and post-navigation verification rules but do not claim DOM-block
semantics. Their Publication fingerprints remain artifact-verification and
diagnostic data, not progress identity.

Production enablement is per format and platform. Android conformance, physical
iOS evidence, malicious-publication tests, libmobi safety/license gates, and all
six cross-platform directions are blocking acceptance criteria.
