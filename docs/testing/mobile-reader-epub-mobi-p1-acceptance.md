# Mobile Reader EPUB/MOBI P1 acceptance

Date: 2026-08-14
State: implementation complete; release gates remain open

## Delivered

- Strict Reader v4 support for EPUB, MOBI, AZW, AZW3 and PRC. TXT, PDF and CBZ
  remain explicitly unsupported by this reflowable capability.
- A typed source-format contract which preserves the original Kindle-family
  container while mapping the family to the shared MOBI reflowable adapter.
- Format-aware download and managed-publication storage. Size, SHA-256, parser
  and normalization identities are checked before opening.
- Lazy Android and iOS Readium Publications backed by one serialized libmobi
  handle. Native reads are capped at 256 KiB and close is idempotent.
- Product Reader entry from online bootstrap, managed downloads, Download Center,
  Work Detail, Shell and offline grace routes.
- EPUB Navigator reuse for both EPUB and MOBI-family reflowable Publications,
  including TOC, preferences, bookmarks and exact-location restoration.
- The obsolete Android and iOS POC applications were retired after their corpus
  and effective adapter tests moved to the formal targets.

The implementation does not generate a converted EPUB, ZIP or unpack directory.

## Android evidence

Dedicated AVD: `Shuku_API_36` (`emulator-5554`).

- Shared tests, `mobiCore` and `androidApp` unit tests passed.
- `mobiCore` and `androidApp` warning-as-error lint passed.
- App and instrumentation APKs assembled successfully.
- Debug APK SHA-256:
  `4734129fe36ca3dc97030fee022c3ff7331ffa17138d3d4b9dbc6754e600abac`.
- Package `com.ermao.library`, version code `1`, version `0.1.0` passed
  replace-install, force-stop/cold-launch, foreground and clean-crash-log checks.
- Formal product MOBI Reader instrumentation passed and verified an original
  `.mobi` artifact with no sibling `.epub`.
- All eight `mobiCore` device tests passed: positive/negative corpus, ABI goldens,
  cross-256-KiB range reads, close-once, metadata/cover/direction/hierarchical TOC,
  stable errors and the 110 MiB stress publication.

## Open release gates

- Run the checked-in XCTest and UI journeys on a paired, unlocked, signed physical
  iPhone or iPad using `iphoneos`. Simulator evidence is prohibited. This host has
  no Xcode or connected physical iOS device, so no iOS runtime acceptance is claimed.
- Complete the fixed-corpus libmobi fuzz/sanitizer gate.
- Complete the LGPL linking, relinking and source-offer review.
- Obtain legally redistributable genuine KFX/AZW4 negative samples; extension-spoof
  fixtures are not equivalent evidence.
