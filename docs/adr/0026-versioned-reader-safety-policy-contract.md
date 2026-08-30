# ADR 0026: Versioned cross-platform Reader safety policy

Status: Accepted
Date: 2026-08-31

## Context

Web, Android and iOS use different publication engines. Their former safety
checks evolved independently: Web rejected every DOCTYPE while native readers
accepted bounded standard XHTML declarations, and limits, active-content lists
and error mappings existed in several platform files. A shared parser core would
remove that drift but is disproportionate and would erase useful native engine
boundaries.

The product requires equivalent acceptance, filtering and failure semantics for
EPUB, FB2, TXT, MOBI, AZW, AZW3, PRC, PDF, comics and audio without converting
or rewriting the stored original.

## Decision

`packages/reader-contracts/reader-safety-policy.json` is the sole semantic owner.
It has a separately versioned JSON schema and policy revision. Canonical JSON is
UTF-8 with sorted object keys and no insignificant whitespace; its SHA-256 is
embedded in generated TypeScript, Kotlin, Python and native C bindings. The policy ships
with each build. There is no remote mutation and no Reader bootstrap version
handshake.

The contract owns:

- exact resource formats and MIME types, including actual MOBI-family formats
  and no generic `KINDLE` value;
- inclusive resource, parser, archive, render and delivery budgets;
- stable algorithms, `ruleId`, stages, required consumers, actions and error
  codes;
- authored markup, URI, CSS, SVG, XML/DOCTYPE/entity and DRM decisions;
- PDF active-content and Range constraints, comic archive/page/revision rules,
  and audio container/metadata/chapter rules;
- required platform defenses such as external-entity, script, document-network
  and PDF-action isolation.

The only decisions are `ALLOW`, `SANITIZE`, `BLOCK_RESOURCE` and
`REJECT_PUBLICATION`. Recoverable authored active content is removed from the
in-memory Publication and reading continues. Fatal structural, DRM, budget or
security findings reject the Publication. A missing or bad optional resource can
be blocked without discarding otherwise readable content.

Platforms retain parser and SDK adapters, but those adapters only detect
normalized facts and apply generated decisions. They may not define a second
threshold, allowlist, MIME map, rule ID or safety error. iOS consumes the KMP
binding through `ErmaoShared`; it does not generate or maintain Swift policy
data. A required defense unavailable in an engine fails as `ENGINE_*` or
`PLATFORM_*` and is a conformance defect, not a content security finding. No
security failure may select a legacy parser or online-content fallback.

Standard XHTML 1.0/1.1 public identifiers with their HTTP or HTTPS W3C system
identifiers are accepted after lexical validation, while external DTD resolution
remains disabled. The contract therefore also generates the complete XHTML/XML
named-entity codepoint table used by every parser-safe in-memory copy; platforms
must not depend on an engine-private entity catalog. Internal subsets, custom
entities and XXE reject the Publication. This replaces Web's former blanket
DOCTYPE rejection.

The stored and downloaded original remains byte-identical. Sanitization exists
only in the in-memory parser/renderer projection; it never creates a derived
EPUB, ZIP, generated chapter set or persisted unpacked directory. A semantic
filter change increments the policy version and the affected Publication
normalization identifier so stale locations and projections cannot be claimed as
equivalent.

Native local and streamed PDF paths converge on the repository-owned PDFium
adapter; Web continues using pdf.js. Both engines must emit the same normalized
policy findings and honor the same limits. Android/iOS audio playback remains
unsupported until a separate product change implements players, so audio runtime
rules currently require backend and Web conformance only.

## Conformance and governance

The versioned fixture manifest records input SHA-256, required consumers,
expected action, terminal rule/error, ordered rule events and a semantic
projection digest. The source `policyDigest` is canonical JSON SHA-256 after
excluding only that self-referential member; stale source digests are rejected.
The generator performs schema-independent semantic checks,
cross-reference validation and drift checking. The boundary checker rejects raw
rule IDs and platform-authored policy catalogs in Reader code.

CI must run the generator with `--check`, contract unit tests, the boundary
checker and each consumer's conformance suite. Reports identify the policy ID,
version and digest. Runtime logs may additionally record rule ID, format, stage
and action, but never publication text or private paths. Browser conformance
includes Chromium and WebKit no-network isolation. Android acceptance uses an
explicit physical device; iOS acceptance requires an `iphoneos`/`iosArm64`
build and a selected physical iPhone or iPad. A simulator cannot substitute.

## Superseded clauses

This ADR supersedes only the head-only/no-body-rewrite safety clauses in ADR
0011 and ADR 0016. Their exact-location, source-preservation and no-derived-
publication decisions remain accepted. It also refines ADR 0025: the complete
original is still downloaded before reflowable reading, but its in-memory
Publication is filtered by this contract. ADR 0025's delivery-mode and download
ownership decisions remain unchanged.
