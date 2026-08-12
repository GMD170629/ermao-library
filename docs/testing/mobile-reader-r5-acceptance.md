# Mobile Reader R5 acceptance record

Date: 2026-08-13
Implementation revision: working tree based on the R4 candidate
Overall phase state: **implemented, not accepted** — the R4 freeze, physical iOS, fuzz safety and formal license gates remain open.

## Delivered

- one pinned libmobi v0.12 production source tree and opaque C ABI v1;
- metadata, resource, reading-order, hierarchical TOC, warning and bounded-read indexes without the POC's second whole-publication C copy;
- stable validation/error mapping for missing, pseudo, corrupt, truncated, DRM, empty-content, limits and ranges;
- Android `:mobiCore`, JNI-only native adapter and serialized close-once Kotlin infrastructure wrapper;
- iOS local Swift Package integration and actor/RAII infrastructure wrapper;
- shared 10-book POC corpus plus Hybrid HUFF/CDIC, PRC/AZW aliases, deterministic negative fixtures and complete ABI golden snapshots.

No MOBI UI route, Readium adapter, ReaderFormat/JSON/progress, backend API or user-visible copy was added. The Android application does not depend on `:mobiCore`; the R5 consumers remain platform infrastructure tests.

## Executed evidence

Host C:

- C99 core and C++ public-header builds passed;
- 13 positive files and eight stable negative cases passed;
- resource limit/boundary/EOF reads, caller-buffer behavior, invalid `struct_size`, missing fields, open options and 1,000 open/close cycles passed;
- ASan/UBSan passed with leak detection enabled;
- canonical snapshots include ABI/parser identifiers, metadata, resource category/type/length/SHA-256, reading order, TOC parent/target/title/fragment and warnings;
- synthetic 110 MiB KF8 stage probe: `mobi_load_filename` took 109 ms and reached 114,176 KiB RSS; RAWML reconstruction added no measurable RSS for this small decoded publication; upstream close returned current RSS to 1,712 KiB;
- the separate ABI process completed open/index in 40 ms, first-chunk read below the 1 ms timer resolution, and returned current RSS from 114,176 KiB to 1,588 KiB after close. Pinned libmobi retains the input records; Ermao ABI adds no second whole-resource copy.

Android dedicated AVD `Shuku_API_36` (`x86_64`, API 36):

- `:mobiCore:testDebugUnitTest`, lint, arm64/x86_64 native builds and instrumentation packaging passed;
- Windows-native ADB replace-installed the test APK after intermittent WSL service failures;
- five JNI instrumentation tests passed, covering the full corpus, stable negatives, close-once, Host/Android byte-identical goldens and a synthetic large KF8 file;
- five consecutive 110 MiB KF8 open/index/first-chunk/close cycles completed in 539 ms total; open RSS samples were 233,112/227,076/227,012/227,004/226,996 KiB and post-close samples were 114,436/114,500/114,492/114,484/114,584 KiB, with no monotonic growth;
- the JNI version script exposes only `Java_com_ermao_library_mobi_infrastructure_MobiCoreNative_*` and `ermao_mobi_*`; no upstream `mobi_*` symbol remains in the dynamic export table;
- stripped debug JNI binaries: 214,488 bytes arm64-v8a and 213,792 bytes x86_64.

Android application regression evidence from the current R4 candidate:

- unit tests and warning-as-error lint passed after replacing the hand-written SQLite transaction lifecycle with the behavior-equivalent Android KTX transaction boundary;
- Debug APK SHA-256 `99631e0e8bbe73ac055247d248f1dca45ab822a0c96bfaf1a38f69beb491c711` was replace-installed on `emulator-5554` / `Shuku_API_36`;
- package `com.ermao.library`, version code `1`, version `0.1.0` passed cold-launch, foreground-activity and clean-crash-log verification;
- all five current EPUB Reader and R4 persistence instrumentation tests passed.

## Open gates and known limits

- Freeze/rebase onto the final R4 revision, then repeat the application build/deploy and EPUB regression.
- Run the checked-in `MobiCoreTests` with `-sdk iphoneos` on a paired, unlocked, signed physical iPhone/iPad. The prepared suite covers all 13 positive fixtures, all eight stable negative cases, both Host/iOS ABI golden snapshots and five repeated 110 MiB open/read/close cycles. Simulator evidence is prohibited. This host has no Xcode or attached physical iOS device, so no iOS build/XCTest/performance result is claimed.
- The fuzz safety gate remains open; R5 must not be accepted or distributed until it passes with the fixed corpus and sanitizers.
- Obtain the LGPL linking/relinking/source-offer compliance conclusion before formal distribution.
- Add legally redistributable genuine KFX/AZW4 negative samples. The checked-in extension-spoof fixtures test stable `unsupported` behavior but are not genuine-format coverage.

## R6/R7 handoff

Consume only `ermao_mobi_*` through the platform wrappers. Keep one serialized handle per open publication, cap every read at 256 KiB and close deterministically. R6/R7 own virtual href construction, Kindle URI rewriting and Readium `Publication` adapters. They must not expose ABI handles, build a physical or hidden EPUB, or modify shared progress solely to accommodate MOBI.
