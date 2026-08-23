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
