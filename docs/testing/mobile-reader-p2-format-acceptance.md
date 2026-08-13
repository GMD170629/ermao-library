# Mobile Reader P2 format acceptance

Date: 2026-08-14
State: Android accepted; iOS implementation awaits physical-device evidence

## Scope

P2 adds native TXT, CBZ, and PDF reading without replacing the selected engines.
Web continues to consume server-normalized RWPM for reflowable formats, while
native CBZ and PDF sessions use morphology-specific Readium navigators. FB2,
ZIP, CBR, and RAR are not advertised as Reader-capable formats in this phase.

All exact progress uses the Reader v4 `PublicationLocation` union and a real
source SHA-256 fingerprint. Wire page indexes are zero-based. CBZ additionally
requires the canonical page href, and PDF currently records page-local
progression as zero in native paged mode.

## Delivered

- A single backend and reader-core capability matrix for EPUB, Kindle-family,
  TXT, CBZ, and PDF.
- True source hashes for newly imported supported publications and fail-closed
  bootstrap when a trustworthy identity is unavailable.
- Defensive CBZ indexing with traversal, duplicate, encryption, symlink,
  expansion-size, entry-count, and compression-ratio limits.
- Deterministic TXT normalization shared by Android and iOS adapters.
- Typed canonical comic page units in the shared bootstrap contract.
- Android TXT, CBZ, and PDF publication factories, native navigators, exact
  save/restore, process recreation, and local-first synchronization.
- iOS TXT, CBZ, and PDF native session implementations wired to the product
  composition root. These are not release-accepted until the device gate below
  passes.

## Android evidence

Dedicated AVD: `Shuku_API_36` (`emulator-5554`).

- Shared tests, Android unit tests, Android instrumentation compilation, and
  `iosArm64` KMP compilation passed.
- TXT instrumentation verified decoding, rendering, table-of-contents
  navigation, and exact reflowable location capture.
- CBZ instrumentation verified canonical archive mapping, page navigation,
  exact comic location persistence, and session restoration.
- PDF instrumentation used a real PDF and verified PDFium opening, exact page
  persistence, Activity recreation, recapture comparison, and a new-session
  restore. The current PDF corpus is single-page, so multi-page navigation is
  not yet represented by this test.
- Debug APK was replace-installed, cold-launched, and checked for crashes on the
  dedicated AVD.

## Open release gates

- Build the iOS app for `iphoneos`, install it on a paired, unlocked, signed
  physical iPhone or iPad, then run TXT, CBZ, PDF, persistence, outbox, process
  death, accessibility, and lifecycle XCTest journeys. Simulator evidence is
  prohibited.
- Add a redistributable multi-page PDF fixture and assert page navigation plus
  exact restoration on both native platforms.
- Run the MOBI runtime contract in an image that contains the pinned libmobi
  shared library. A missing runtime must remain distinguishable from a missing
  publication.
- Run RAR/CBR archive tests only in an environment with an approved `unrar` or
  `unar` backend; those formats remain outside the P2 advertised capability
  matrix.
