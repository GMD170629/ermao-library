# ADR 0026: Versioned cross-platform Reader safety policy

Status: Accepted
Date: 2026-08-31
Revised: 2026-09-05 (Schema v2 / Policy v4)

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

- format/MIME adapter-selection data, including actual MOBI-family formats;
  these are capability descriptions, never content-security admission lists;
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
in-memory Publication and reading continues. Unisolatable concrete security risks and unchanged capacity limits may stop the
Publication. Actual parser/decryption failures and unreadable required content
stop opening with CAPABILITY or INTEGRITY reasons, never a security accusation. A missing or bad optional resource can
be blocked without discarding otherwise readable content.

The pre-existing backend parser snapshot reservation also belongs to this
contract (`COMMON.PARSER_SNAPSHOT_MEMORY`). Its existing memory ceiling and
source-size cost multiplier are preserved; eviction cannot admit an individual
snapshot larger than that reservation. This backend-only allocation mechanism
is reported as RESOURCE_LIMIT and has below/equal/over conformance cases. It
does not classify an otherwise valid source as malicious. Cache entry count and
idle eviction only control reuse and do not create publication admission rules.

Platforms retain parser and SDK adapters, but those adapters only detect
normalized facts and apply generated decisions. They may not define a second
threshold, allowlist, MIME map, rule ID or safety error. iOS consumes the KMP
binding through `ErmaoShared`; it does not generate or maintain Swift policy
data. A required defense unavailable in an engine fails as `ENGINE_*` or
`PLATFORM_*` and is a conformance defect, not a content security finding. No
security failure may select a legacy parser or online-content fallback.

Content safety defaults to ALLOW and uses explicit behavior blacklists. Unknown
declarations, tags, entities, schemes or MIME values are not dangerous merely
because a catalog lacks them. There are no private NCX exceptions.

All DOCTYPE declarations, including unfamiliar PUBLIC/SYSTEM declarations, lose
their external parser dependency in a volatile parsing copy. Bounded internal
text entities expand as escaped text; external, recursive, parameter and unknown
references remain literal text. The shared named-entity codepoint map remains
encoding data. No unrestricted DTD parser is added. Parser external resolution
stays disabled, following the [OWASP XXE guidance](https://cheatsheetseries.owasp.org/cheatsheets/XML_External_Entity_Prevention_Cheat_Sheet.html).
The risk is external I/O or unbounded expansion, not a declaration's name.

Generated decisions take format, resource role, detected facts and available
isolation capabilities. Their actions include a scope and classification:
SECURITY, CAPABILITY, INTEGRITY, RESOURCE_LIMIT or IMPLEMENTATION. A damaged
optional image, font, navigation document or comic page is isolated; CRC and
conflicting bytes are integrity failures. Benign dot path segments normalize;
actual root escape is blocked. Unknown encryption metadata does not substitute
for the decoder's actual result.

Native adapters wrap the public ContainerAsset before PublicationOpener.open,
so container/OPF/NCX reads pass through XML preprocessing before SDK parsing.
Body/CSS/SVG resource reads stay behind that same protected container. The
publication callback only decorates rendering. Each open may retain its first
fatal error so SDK error wrapping cannot discard the actual failure; close,
cancellation and account changes dispose it. No resource-failure history or
publication-graph reclassification is needed. Cache reopening, retry and lazy resource reads
must perform the current checks; no global mutable failure state is permitted.

The stored and downloaded original remains byte-identical. Sanitization exists
only in the in-memory parser/renderer projection; it never persists a derived
EPUB, ZIP, generated chapter set or unpacked directory. A semantic
filter change increments the policy version and the affected Publication
normalization identifier so stale locations and projections cannot be claimed as
equivalent.

Native local and streamed PDF paths converge on the repository-owned PDFium
adapter; Web continues using pdf.js. Both engines must emit the same normalized
policy findings and honor the same limits. Native platform evidence is required for every applicable manifest obligation;
KMP semantics tests do not substitute for Android or iOS adapter execution.

## Conformance and governance

This is a household NAS reader. Prefer the existing parser controls and small
shared sanitizers over additional policy frameworks. Production reading must not
collect rule-event histories solely for reporting. Tests should execute the real
sanitizer and assert readable output and blocked dangerous side effects; a report
gap does not justify extra production state or an invented passing trace.

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
action and classification, but never publication text or private paths. Browser conformance
includes Chromium and WebKit no-network isolation. Android acceptance uses an
explicit physical device; iOS acceptance requires an `iphoneos`/`iosArm64`
build and a selected physical iPhone or iPad. A simulator cannot substitute.

## Related current contracts

[ADR 0025](0025-reflowable-original-download-before-reading.md) owns complete-original
reflowable delivery and download ownership. [ADR 0028](0028-reader-v5-opaque-position-report.md)
owns opaque Reader v5 progress. Safety normalization diagnostics do not migrate or
reset progress. Historical v1 safety fixtures remain regression data; reader-safety-v2
is the active suite. Missing physical-device evidence remains explicit in the
[current acceptance gaps](../reader-safety-v4-verification.md).
