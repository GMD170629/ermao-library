# ADR 0016: Source-preserving Reader Publications

- Status: Accepted
- Date: 2026-08-16
- Supersedes: ADR 0013

## Context

MOBI-family and TXT publications are not EPUB files. Readium can nevertheless
consume them when a format parser exposes a Publication with a reading order,
resources and navigation. Packaging those resources into an EPUB adds a second
persisted representation without being required by Readium or its Locator model.

## Decision

Reader persistence, download and recovery always use the original publication
file. The Reader capability must not create, cache, advertise or download a
derived EPUB, ZIP or unpacked publication directory.

MOBI, AZW, AZW3 and PRC use the pinned libmobi C ABI to expose a bounded virtual
Publication. TXT uses the deterministic TXT parser to expose the equivalent
virtual Publication. These in-memory resources are parsing results, not converted
files. Android and iOS download the authorized original file and construct the
Publication locally. Web obtains the same logical Publication through the
authenticated manifest, positions and resource routes and passes it directly to
Readium TS.

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

- The original source is the only downloadable Reader artifact.
- Web resource requests parse and stream virtual Publication resources on demand.
- Native MOBI/TXT readers use their existing local parser-backed Publications.
- Parser failures are visible instead of being hidden by a derived EPUB repair.
- Reader v4 removes the former render-artifact field and endpoint as a coordinated
  breaking change.
