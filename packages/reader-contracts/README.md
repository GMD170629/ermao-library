# Shuku Reader wire contracts

This package is the language-neutral source of truth for Reader v5 wire data.
It deliberately contains schemas and fixtures rather than a shared runtime.
Python, TypeScript, Kotlin, and Swift validate untrusted JSON at their own
boundaries and map it into renderer-neutral domain values.

`reader-v5.schema.json` defines `ReaderPositionReport`. Its `locator` is the
opaque JSON object emitted by the active Reader engine. Empty strings, explicit
nulls and unknown nested extensions are preserved. The server may bound,
serialize, hash, store and return that object, but must never inspect its keys,
infer progress from it, or prove that it is exact. The compact UTF-8 Locator is
limited to 64 KiB.

The sibling `presentation` object is produced by the Reader at the same capture
event. It independently carries `displayPercent`, `totalProgression`, current
href, chapter, page and playback facts. Library surfaces use these fields
directly. Only `locator` is passed back to a Reader for restoration;
presentation values are never navigation candidates.

Reader v5 writes are arrival-ordered and idempotent. The server assigns a
monotonic revision in transaction commit order. `capturedAtEpochMillis` is
metadata, not an ordering input. Reusing a mutation id with identical content
returns its accepted revision without another write; reusing it with different
content is an error. There is no `baseRevision` or Locator conflict resolver.

Reader v4 is immutable historical documentation. v5 does not read, migrate,
rewrite or delete v4 server rows, client progress, pending mutations or conflict
state. The canonical v5 fixtures are consumed by every platform's contract
tests. Adding or changing a field requires updating the schema, all fixtures and
all four boundary validators in the same change.

`locator-dom-projection-v3.schema.json` defines the current reflowable
publication-normalization diagnostic. It projects the ordered reading resources and the
policy-sanitized, pre-Navigator `body` element tree, preserving element paths,
author IDs and normalized locator-block text. Platform CSP, `head` decoration
and Readium runtime nodes are deliberately excluded. The projection records the
exact Reader safety policy version/digest. Equal normalization identifiers are
valid only when this projection is equal.

`normalization-v2` and its schema remain immutable historical fixtures for the
former head-only policy. They are superseded by `normalization-v4` and must not
be rewritten to make current sanitization tests pass. The v3
`projection.sha256` value is `sha256:` followed by the SHA-256 of canonical
projection JSON (UTF-8, sorted keys and compact separators), so formatting the
golden file cannot change its semantic identity. Reader v5 never compares this
diagnostic with a Locator and never uses it to accept, reject, or select progress.

`schemas/txt-decoding-v1.schema.json` and `fixtures/txt-decoding-v1.json`
record the native TXT decoder output, including internal/trailing NUL and empty
text. Applications must not reject or remove NUL before the actual parser.
Verified Foundation codec differences use explicit decoder overrides. Empty
publication and renderer failures are separate from decoding failures.

`reader-http-error-statuses.json` is the authoritative status/code allowlist for
bounded publication and comic resource requests. Web consumes it directly;
`generate-reader-http-errors.py` generates the KMP constants. Run it with
`--check` to verify drift. The matching JSON schema lives under `schemas/`.
A code must match its HTTP status; error response bodies are cancelled without
waiting for EOF. `PUBLICATION_TXT_NUL_CHARACTER` is receive-only compatibility
for older servers; new parsers never emit it. Remove this compatibility entry
only when support for those server versions ends.

See [Reader architecture](../../docs/mobile-reader-architecture.md) for current
adapters and [acceptance gaps](../../docs/reader-safety-v4-verification.md) for
outstanding security/SDK verification.

## Reader safety policy

`reader-safety-policy.json` is the only semantic owner for first-party Reader
content filtering and bounded delivery. Schema v2 / Policy v4 defaults to ALLOW.
Only explicit harmful behavior belongs in a security blacklist. Format and MIME
maps select adapters; absence from a map is not evidence of harmful content.
Existing inclusive size, compression, parser, memory and rendering limits remain
unchanged. Generated decisions carry action, scope, classification, rule ID and
error code. Classifications distinguish SECURITY, CAPABILITY, INTEGRITY,
RESOURCE_LIMIT and IMPLEMENTATION.

XML control documents (container, OPF, NCX) and body markup use the same bounded
XML preprocessor before their respective parsers. Arbitrary DOCTYPE names and
PUBLIC/SYSTEM identifiers are accepted; declarations are removed only in memory
so no parser resolves an external DTD. Ordinary internal text entities expand
within the existing document budget. External, recursive, parameter and unknown
references become literal text. Comments, CDATA and processing instructions are
not executable declarations. The generated named-entity table is encoding data,
not an admission list. No unrestricted DTD parser is introduced.

Sanitize recoverable active content, isolate a damaged optional resource, and
stop the publication only when required content is unreadable, an existing
resource limit is exceeded, or a concrete risk cannot be isolated. Missing engine
or platform defenses stop unprotected execution as an IMPLEMENTATION outcome.
Never retry through an unvalidated parser or online-body fallback.

For PDF, `pdfRangeRequestMaxBytes` is the maximum HTTP transport span and
`pdfRangeMemoryCacheMaxBytes` is the maximum volatile session cache. The
PDFium engine may request any positive `Long` span within the admitted source
length; a span that cannot remain in the bounded cache is routed to
`MATERIALIZE_VERIFIED_ORIGINAL`. This is an explicit hand-off to the shared
Downloads owner, not a whole-response Range fallback, so
`allowWholeResponseFallback` remains `false`.

`schemaVersion` changes only when the JSON shape changes. Every semantic change
increments `policyVersion`. The source `policyDigest` hashes canonical JSON
(UTF-8, sorted object keys, no insignificant whitespace) after removing only
that self-referential member. The generator rejects a stale source digest and
embeds the verified SHA-256 in all bindings. The policy is bundled at build time: there is no remote policy update
or Reader bootstrap negotiation.

Run `generate-reader-safety-policy.py` after changing the source, schema or
fixture manifest. It emits:

- `packages/reader-core/src/reader-safety-policy.generated.ts`;
- KMP `ReaderSafetyPolicy.generated.kt`, which iOS consumes through
  `ErmaoShared` rather than a Swift policy table;
- `apps/api-python/app/contracts/reader_safety_policy_generated.py`;
- native archive-core `reader_safety_policy.generated.h`, so its extension
  detector cannot retain a private comic MIME catalog.

Use `--check` to reject generated drift. The versioned
`fixtures/reader-safety-v2/manifest.json` binds every input and semantic
projection to SHA-256 and records the ordered rule events expected from each
consumer. `check-reader-safety-boundaries.py` rejects raw rule IDs and private
policy catalogs in platform Reader code.

`fixtures/reader-safety-v2/conformance-suite.json` covers every policy rule and
lists only implementation owners that execute each case through a real
production facade in their designated host or physical-device gate. The manifest preserves the exact,
ordered backend/Web/Android/iOS obligations of the authoritative rule; KMP is
not inferred as an iOS substitute, and native physical-device gates remain
separate release evidence.
The backend, Web, KMP host target, Android and iOS physical-device targets must write reports matching
`schemas/reader-safety-conformance-report-v1.schema.json`; the reports contain
the bundled version/digest, actual terminal rule event, action/error code and
semantic projection hash. They never derive an outcome from the fixture's
`expected` object. Run the platform report commands, then compare their JSON
with:

```bash
python3 packages/reader-contracts/verify-reader-safety-conformance.py \
  --require-consumer BACKEND --require-consumer WEB \
  --require-consumer KMP --require-consumer ANDROID --require-consumer IOS \
  <backend-report> <web-report> <kmp-report> <android-report> <ios-report>
```

The verifier rejects missing rule coverage, stale policy bindings, fixture input
drift, incorrect platform outcomes, omissions by a declared executable owner,
and cross-platform disagreement. Platform
CI publishes the generated reports as build artifacts; reports are not source
fixtures and must not be committed as expected output.

## Reading preferences and setting catalog

`reader-settings.json` owns ordered panels/sections, stable setting/control IDs,
bilingual labels, options, numeric constraints, availability rules, bilingual
disabled reasons and the current preference version.
`generate-reader-settings.py` generates the typed Web catalog, KMP access/edit
metadata, shared navigation policy bindings and iOS native localization keys.
Do not edit generated files or add platform-owned setting lists. Run the generator
then `python3 packages/reader-contracts/generate-reader-settings.py --check`.
The check also verifies that iOS maps every catalog field. Web pretest runs it.

Preference storage uses version 6; Reader progress uses v5. Web, Android and
iOS do not migrate older preference schemas. The generator verifies that Web and
KMP runtime versions match the catalog owner.

Historical `reader-safety-v1` and `normalization-v3` fixtures remain immutable.
The v2 suite removes the previous iOS non-audio execution exemption. Missing iOS
adapter/device evidence is a failed release obligation, not coverage supplied by
KMP. `POLICY_DECISION` cases test the generated decision function; they do not
claim SDK call-path coverage. Separate integration tests must prove that native
ContainerAsset wrappers run before PublicationOpener parses control documents.
The normalization v4 identifier diagnoses volatile projections only; Reader v5
opaque progress, verified original caches and download ownership are unchanged.

`COMMON.PARSER_SNAPSHOT_MEMORY` captures the backend's existing parser snapshot
memory reservation and cost estimate. Its fixtures are backend-only because
native and Web readers do not use that snapshot implementation. All previously
declared resource budgets retain their values; this extraction introduces no
new admission threshold. MIME tables are adapter-selection hints: original
download, cache reopen, audio bootstrap, comic resources and PDF Range transport
must not use membership in those tables to refuse content.

## Chapter identity

The [shared chapter core](../../docs/reader-chapter-consistency.md) owns chapter
recognition and final `chapter-N` preorder keys. Reader chapter presentation carries
`navigationKey` (nullable); Book Detail matches it within the same resource.
Cross-binding fixtures live in `fixtures/chapters-v1`. Empty TOCs stay empty.
