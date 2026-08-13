# ADR 0011: Readium exact cross-platform progress

Status: Accepted; Android conformance and six-direction physical-device evidence remain release gates
Date: 2026-08-13

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

Reader v4 defines exact reflowable continuation as the same DOM block or unique
text anchor in the same Publication resource.

An exact position is a Readium Locator envelope containing:

- `engine=readium` and `platform=web|android|ios`;
- the Navigator version for diagnostics;
- an exact `PublicationFingerprint` composed of original file SHA-256, content
  parser identifier, and normalization identifier;
- a JSON-object Readium Locator payload, never a JSON string containing JSON;
- an `href` plus a CSS selector, fragment/CFI, or bounded uniquely verifiable
  text anchor.

The envelope is limited to 64 KiB. `highlight` is limited to 512 characters and
`before`/`after` to 256 characters each. Progression, logical position, and
whole-publication percentage are diagnostic or presentation values and are not
exact anchors.

The three fingerprint fields must match before an automatic remote navigation
is attempted. A parser or normalization change invalidates the old Locator; it
does not enable percentage restoration. Navigator versions do not participate
in content identity.

After `Navigator.go(locator)`, the destination recaptures its first-visible
Locator. Exact restoration succeeds only when `href` matches and selector,
fragment/CFI, or uniquely normalized text resolves to the same block. A
successful `go()` result alone is not proof.

Reader v4 writes use `baseRevision` and a UUID `mutationId`. Revision is
monotonic per user and volume, idempotent replays return the original result,
and a stale base revision returns `409 READER_PROGRESS_CONFLICT` with the current
server snapshot. The server never silently resolves a conflict and never
applies a forward-only rule. Client capture time is diagnostic only.

Each client atomically persists its exact Locator and latest-only pending
mutation before networking. Network loss, process termination, and foreground
transitions preserve pending work. A conflict is durable until the user chooses
the local position, the remote position, or cancel. The server-confirmed
revision is persisted before pending work is cleared.

The language-neutral contract and fixtures live in
`packages/reader-contracts`. Python, TypeScript, Kotlin, and Swift each validate
untrusted JSON at their boundary and map it into renderer-neutral domain values.
Readium SDK types remain platform adapter details.

For EPUB, the first production Publication adapter serves raw package resources
without DOM rewriting and uses `epub-package:1` plus
`shuku-epub-raw-v1`. Any later sanitization or URI rewrite that changes the DOM
must introduce a shared normalization revision and equivalent platform output.
MOBI-family publications use the single pinned `ermao_mobi_*` ABI and identical
virtual href/DOM normalization on all platforms; no hidden EPUB is generated.

## Consequences

Reader v4's earlier Foliate engine, percentage-only progress, server content
token, arrival-order overwrite, non-durable upload, outbox migration, and
percentage fallback contracts are removed rather than migrated.

`displayPercent` remains available for progress bars, library display, and
statistics. It must never be consumed by automatic continuation code.

When exact restoration fails, the client reports that outcome and may offer
explicit nearby-position or chapter navigation. Such user-directed navigation
is never reported as exact synchronization.

PDF exactness is a canonical page plus normalized page-local position. CBZ
exactness is a canonical page resource/index. Their anchors use the same
fingerprint, revision, durability, and post-navigation verification rules but
do not claim DOM-block semantics.

Production enablement is per format and platform. Android conformance, physical
iOS evidence, malicious-publication tests, libmobi safety/license gates, and all
six cross-platform directions are blocking acceptance criteria.
