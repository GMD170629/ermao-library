# ADR 0016: Source-preserving Reader Publications

- Status: Accepted for source preservation; delivery model superseded by ADR 0025
- Date: 2026-08-16
- Supersedes: ADR 0013

Safety note (2026-08-31): ADR 0026 supersedes the head-only/no-body-rewrite
clause below. Original bytes and the ban on persisted derivatives remain
accepted. The generated safety contract may remove dangerous authored content
from the in-memory Publication before rendering.

## Context

MOBI-family and TXT publications are not EPUB files. Readium can nevertheless
consume them when a format parser exposes a Publication with a reading order,
resources and navigation. Packaging those resources into an EPUB adds a second
persisted representation without being required by Readium or its Locator model.

## Decision

Every reflowable Reader consumes the verified complete original publication through
its platform-local parser. Native Downloads, Web Reader storage and local imports
preserve the original file. Reader must not
create, cache, advertise or download a
derived EPUB, ZIP or unpacked publication directory.

MOBI, AZW, AZW3 and PRC use the pinned libmobi C ABI to expose a bounded virtual
Publication. TXT uses the deterministic TXT parser to expose the equivalent
virtual Publication. These in-memory resources are parsing results, not converted
files. Android, iOS and Web construct the same logical Publication locally from the
downloaded original and pass it directly to native Readium or Readium TS.

Publication resource bytes come from the format adapter. Delivery code may set
HTTP security headers and native containers may apply the documented head-only
security policy, but Reader delivery does not repair, reserialize or replace the
author body. Invalid resources fail through the format adapter's normal error
contract.

Exact reflowable progress remains a Readium Locator containing a stable resource
href plus a selector, fragment/CFI or bounded text context. It does not depend on
an EPUB container. Cross-platform conformance is established by comparing hrefs
and restoring then recapturing the semantic anchor.

The dormant import-time conversion subsystem is outside this Reader decision. It
must not be wired into Reader bootstrap, publication delivery, downloads, cache,
progress restoration or any Reader fallback without a new explicit decision.

## Consequences

- Native Reader starts or observes the authoritative Downloads task when the original
  is missing; Web stores the original through its Reader-owned browser adapter.
- Web and native parsers expose virtual Publication resources locally on demand.
- Every completed original retains its original-format parser and no server chapter
  delivery fallback.
- Parser failures are visible instead of being hidden by a derived EPUB repair.
- Reader v4 removes the former render-artifact field and endpoint as a coordinated
  breaking change.
