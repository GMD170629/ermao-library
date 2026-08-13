# Readium Web MOBI Runtime Publication POC

This isolated POC proves the runtime path below without creating an EPUB, ZIP, or unpacked publication directory:

```text
AZW3 / MOBI fixture
  -> libmobi 0.12 through ermao_mobi ABI v1
  -> Web Publication Manifest + same-origin resource routes
  -> @readium/shared Publication
  -> @readium/navigator EpubNavigator
```

It intentionally does not modify the production Foliate reader in `apps/web`.

## Run

From this directory, use two terminals:

```bash
pnpm dev:server
pnpm dev
```

Then open `http://127.0.0.1:4173`.

The native server reads fixtures from `test-data/library/mobi`, retains one opaque libmobi handle, emits an EPUB-profile Readium Web Publication Manifest, and streams each reconstructed resource in chunks no larger than the ABI's 256 KiB read limit.

## What to verify

- `08-zh-hans.azw3`: CJK text and non-BMP characters render intact.
- Layout controls: both paginated and scrolled preferences keep the publication visible.
- `03-css.azw3`: `#css-proof` computes to `margin-left: 37px` and `rgb(32, 78, 121)`.
- `04-font.azw3`: the embedded `Shuku Test Font` is ready and used by `#font-proof`.
- `05-images.azw3`: both PNG and JPEG decode with non-zero natural dimensions.
- Export Locator: captures a bounded Readium Locator containing `href`, `cssSelector`, text highlight, progression, logical position, and the structured source/parser/normalization fingerprint.
- Import Locator: accepts either raw Readium Locator JSON or an iOS/Web engine envelope and reports exact block, approximate resource, or fallback precision.

## Checks

```bash
pnpm build:server
pnpm typecheck
pnpm test
pnpm build
```

No Playwright suite is used. Browser acceptance is performed directly against a locally running native publication server and Readium Navigator.

## Precision contract

"Exact" requires the same original SHA-256, parser ID, normalization ID, reading-order resource, and stable DOM block or text anchor. It does not mean the same page number, viewport coordinates, or pixels; those necessarily change with viewport, font, line height, and pagination mode.

Both clients bound the engine payload to 64 KiB and quotes to 512 characters. A giant single paragraph therefore remains safe, but can only restore to its block or fall back to progression/position. Character-offset precision needs a separately verified DOM Range or partial-CFI implementation on both toolkits.

The TS toolkit does not expose a stable public first-visible-element method in 2.8.2. The POC adapter first requests the toolkit's internal `first_visible_locator` event, then uses a same-origin DOM block capture fallback. Product integration must keep this behind an adapter and should replace it when Readium publishes a stable API.
