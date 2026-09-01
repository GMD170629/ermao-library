# Shuku Reader wire contracts

This package is the language-neutral source of truth for Reader v4 wire data.
It deliberately contains schemas and fixtures rather than a shared runtime.
Python, TypeScript, Kotlin, and Swift validate untrusted JSON at their own
boundaries and map it into renderer-neutral domain values.

`reader-v4.schema.json` defines a discriminated exact-location union. Reflowable
content requires a Readium resource plus CSS selector, fragment/CFI, or bounded
text anchor. PDF uses a zero-based page index plus normalized page-local
progression. Comics use a zero-based page index plus canonical resource href.
Audio uses asset/chapter identity and playback milliseconds; the owning resource
is carried by the Reader resource contract. An engine locator is
optional for fixed-layout and audio locations, but required for reflowable
content. Boundary adapters additionally verify that every referenced resource
belongs to the active Reader resource.

`displayPercent`, resource progression, logical position, and total progression
are presentation or diagnostic values. They must never be used for automatic
cross-device restoration.

Reader v4 was unreleased when this morphology union replaced the former
all-Readium envelope. Old v4 locations and pending/conflict state are invalid;
there is no dual-read or migration fallback. The canonical fixtures are consumed
by each platform's contract tests. Adding or changing a field requires updating
the schema, all fixtures, and all four boundary validators in the same change.

`locator-dom-projection-v3.schema.json` defines the current content identity used
by reflowable exact progress. It projects the ordered reading resources and the
policy-sanitized, pre-Navigator `body` element tree, preserving element paths,
author IDs and normalized locator-block text. Platform CSP, `head` decoration
and Readium runtime nodes are deliberately excluded. The projection records the
exact Reader safety policy version/digest. Equal normalization identifiers are
valid only when this projection is equal.

`normalization-v2` and its schema remain immutable historical fixtures for the
former head-only policy. They are superseded by `normalization-v3` and must not
be rewritten to make current sanitization tests pass. The v3
`projection.sha256` value is `sha256:` followed by the SHA-256 of canonical
projection JSON (UTF-8, sorted keys and compact separators), so formatting the
golden file cannot change its semantic identity.

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

See `docs/testing/reader-parser-implementation-2026-08-28.md` for migrated
callers, security/SDK limitations and verification evidence.

## Reader safety policy

`reader-safety-policy.json` is the only semantic owner for first-party Reader
content filtering and bounded delivery. Its v1 schema fixes the format/MIME
inventory, budgets, algorithm and rule IDs, actions, stable error codes,
required consumers and platform-defense capabilities for reflowable books,
PDF, comics and audio. A platform may detect normalized facts and apply the
generated action; it must not author another allowlist, denylist, threshold,
MIME table, rule ID or safety error mapping.

The reflowable profile includes the generated XHTML/XML named-entity codepoint
table. Standard XHTML DOCTYPEs can therefore be accepted without resolving an
external DTD, and every platform parses `&nbsp;`, `&copy;` and the remaining
standard names with the same semantics while rejecting unknown names.

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
`fixtures/reader-safety-v1/manifest.json` binds every input and semantic
projection to SHA-256 and records the ordered rule events expected from each
consumer. `check-reader-safety-boundaries.py` rejects raw rule IDs and private
policy catalogs in platform Reader code.

`fixtures/reader-safety-v1/conformance-suite.json` covers every policy rule and
lists only implementation owners that execute each case through a real
production facade in their designated host or physical-device gate. The manifest preserves the exact,
ordered backend/Web/Android/iOS obligations of the authoritative rule; KMP is
not inferred as an iOS substitute, and native physical-device gates remain
separate release evidence.
The backend, Web, KMP host target and Android physical-device instrumentation target write reports matching
`schemas/reader-safety-conformance-report-v1.schema.json`; the reports contain
the bundled version/digest, actual terminal rule event, action/error code and
semantic projection hash. They never derive an outcome from the fixture's
`expected` object. Run the platform report commands, then compare their JSON
with:

```bash
python3 packages/reader-contracts/verify-reader-safety-conformance.py \
  --require-consumer BACKEND --require-consumer WEB \
  --require-consumer KMP --require-consumer ANDROID \
  <backend-report> <web-report> <kmp-report> <android-report>
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

Preference storage uses version 6; Reader progress remains v4. Web, Android and
iOS do not migrate older preference schemas. The generator verifies that Web and
KMP runtime versions match the catalog owner.
