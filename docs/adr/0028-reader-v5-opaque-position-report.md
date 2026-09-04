# ADR 0028: Reader v5 opaque position reports

Status: Accepted
Date: 2026-09-04
Supersedes: ADR 0011 progress-location, validation, synchronization and persistence decisions

## Context

Reader v4 wrapped platform locators in a morphology-specific application model,
required application-defined proof of exactness, derived percentage and chapter
state on the server, and resolved concurrent writes with `baseRevision`.
That boundary rejected valid Readium output such as an image-only cover Locator
whose `text.highlight` is empty. It also allowed the exact Locator used by the
Reader and the percentage shown by Library surfaces to diverge.

Every supported Reader already owns the information needed for both navigation
and presentation. Readium and the format-specific navigator, not the server,
are the authorities for their Locator. The server only needs an authenticated,
bounded and idempotent synchronization slot.

## Decision

Reader v5 uses `ReaderPositionReport`:

- `locator` is the complete JSON object serialized by the active Reader engine;
- `presentation` independently carries display percentage, normalized total
  progression, current href, chapter, page and playback facts;
- only `locator` may be passed to a Reader for restoration;
- Library surfaces consume only `presentation`.

Locator preservation is semantic JSON preservation. Empty strings, nulls and
unknown nested values are retained. JSON object key order, whitespace and the
original numeric spelling are not contracts. The compact UTF-8 object is limited
to 64 KiB. The server may decode/encode generic JSON, measure it and hash it for
idempotency, but it must not read any Locator key, compare Locator anchors,
derive presentation values, or validate a Locator against publication content.

Progress writes contain a UUID mutation id but no `baseRevision`. The server
atomically assigns monotonically increasing revisions in transaction commit
order. The last successfully committed mutation is the current snapshot.
Client capture time is metadata only. An identical mutation replay returns its
accepted revision without another write; reuse with different content fails with
`READER_PROGRESS_MUTATION_REUSE`.

The client atomically stores the full report and its latest pending mutation
before networking. A retry sends the same mutation id and body. An acknowledgement
clears only the matching pending record. Startup order is explicit target, local
pending v5 report, server v5 report, then publication start. Active sessions are
never moved by another device in the background.

Reader v5 has independent server and client storage namespaces. v4 progress,
receipts and local outboxes are neither migrated nor read nor deleted. First-party
Reader routes move together to `/api/reader/v5`; v4 is a retired protocol.

## Consequences

An empty `highlight`, missing selector, unknown extension or disagreement between
Locator progression and presentation progression cannot cause server rejection.
Malformed or unsupported navigation is reported only when the destination Reader
SDK cannot deserialize or navigate to the returned Locator; the client does not
repair or rewrite the server value.

The same engine Locator can be exchanged among Web, Android and iOS for the same
publication without a platform wrapper. Format adapters must publish cross-client
fixtures and may not truncate text, inject progression, or merge separately
captured Locators.

Reading status is independent from position. Marking a resource finished must not
manufacture a Locator. Structured logs contain identifiers, revision, byte size
and outcome, never Locator or publication content.
