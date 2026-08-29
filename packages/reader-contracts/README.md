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

`locator-dom-projection-v2.schema.json` defines the content identity used by
reflowable exact progress. It projects the ordered reading resources and the
pre-Navigator `body` element tree, preserving element paths, author IDs and
normalized locator-block text. Platform CSP, `head` decoration and Readium
runtime nodes are deliberately excluded. Equal normalization identifiers are
valid only when this projection is equal.

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
callers, security/SDK limitations and verification evidence. Format inference,
script isolation, protocol validity and resource budgets have separate owners.

## Reading preferences and setting catalog

`reader-settings.json` (schema `schemas/reader-settings-v1.schema.json`) owns
ordered panels/sections, stable setting/control IDs, bilingual labels, options,
numeric constraints, availability rules and bilingual disabled reasons.
`generate-reader-settings.py` generates literal Web
constants and typed KMP access/edit metadata plus iOS native localization keys.
Do not edit generated files or add platform-owned setting lists. Run the generator
then `python3 packages/reader-contracts/generate-reader-settings.py --check`.
The check also verifies that iOS maps every catalog field. Web pretest runs it.

Preference storage version 5 is **not** a new Reader progress protocol. Progress
remains v4. Web migration owns the legacy line-height flag → off conversion;
KMP owns native migration (including iOS), preserving the native publisher
master. Retired partial publisher fields exist only in storage migration and
migration regression inputs, never in runtime rendering.
