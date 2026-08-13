# Android MOBI exact Locator conformance POC

Fixture: `test-data/library/mobi/08-zh-hans.azw3`

The isolated `readerMobiPoc` application uses Readium Kotlin 3.3.0 and the
same pinned `ermao_mobi_*` ABI used by Web and iOS. It builds an in-memory
Readium Publication without creating an EPUB file or rewriting the XHTML.

Frozen identity and normalization evidence:

- original file SHA-256: `f2b9fdd883430568c161995e80e52fc337ceb417222884c3c782af8202f4c581`
- parser: `libmobi:0.12@85dcfe803fc2a21020ddcf15c3eb66b93d388add`
- normalization: `ermao-mobi-core-v1`
- reading order: `part00000.html`
- reconstructed XHTML SHA-256: `a2c8ab0d3592ab8b5fc7c73a817fc1e2b5f3b175de86ccb0623cfdf1929065e5`

The instrumentation test navigates to the `ZH_TEXT_MARKER` block, captures
`firstVisibleElementLocator()`, navigates away, calls `go()` with the captured
Locator, recaptures the first visible Locator, and requires the shared
exact-block comparator to return `Exact`.

Build evidence completed on 2026-08-13:

```text
:mobiCore:assembleDebug                                 PASS
:readerMobiPoc:assembleDebug                           PASS
:readerMobiPoc:compileDebugAndroidTestKotlin            PASS
:readerMobiPoc:assembleDebugAndroidTest                 PASS
:mobiCore:lintDebug                                     PASS
:readerMobiPoc:lintDebug                                PASS
:androidApp:compileDebugKotlin                          PASS
ermao_mobi_host_tests                                   PASS
```

The environment had no connected Android device. Therefore the
instrumentation journey has been built but not executed, and Android physical
device conformance remains a Phase 0 acceptance gate. This evidence does not
claim Web ↔ Android or iOS ↔ Android physical cross-device exchange.
