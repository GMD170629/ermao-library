# Shuku Reader wire contracts

This package is the language-neutral source of truth for Reader v4 wire data.
It deliberately contains schemas and fixtures rather than a shared runtime.
Python, TypeScript, Kotlin, and Swift validate untrusted JSON at their own
boundaries and map it into renderer-neutral domain values.

`reader-v4.schema.json` enforces the structural definition of an exact locator:
an `href` plus a CSS selector, fragment/CFI, or bounded text anchor. Runtime
validation must additionally prove text uniqueness and, after navigation,
recapture the first visible locator and compare the resolved block. A successful
Navigator `go()` call is never sufficient proof of exact restoration.

`displayPercent`, resource progression, logical position, and total progression
are presentation or diagnostic values. They must never be used for automatic
cross-device restoration.

The canonical fixtures are consumed by each platform's contract tests. Adding
or changing a field requires updating the schema, all fixtures, and all four
boundary validators in the same change.
