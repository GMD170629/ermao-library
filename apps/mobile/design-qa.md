# Content Discovery Design QA

Status: the historical content-discovery compact/light smoke review passed. Work Detail v6 is now the authoritative target and requires a new physical-device visual and interaction acceptance run before implementation can be called current.

Latest Work Detail control-menu run: option 1 was tightened into a 224 dp pointer-anchored translucent card, and direct task Sheets replaced the standalone management route. Android physical-device visual and runtime QA passed for the book menu, volume-cover long press, and in-detail edit flow. Evidence and the remaining iOS physical-device gate are recorded in `design-qa/visual-runs/20260816-work-detail-control-menu-v2/report.md`.

## Reference set

- `docs/assets/mobile-app-hifi-v1/home-app-light-v1.png`
- `docs/assets/mobile-app-hifi-v1/library-app-light-v1.png`
- `docs/assets/mobile-app-hifi-v1/library-search-works-results-app-light-v1.png`
- `docs/assets/mobile-app-hifi-v1/library-series-scope-app-light-v1.png`
- `docs/assets/mobile-app-hifi-v1/library-authors-scope-app-light-v1.png`
- `docs/assets/mobile-app-hifi-v1/library-series-facet-app-light-v1.png`
- `docs/assets/mobile-app-hifi-v1/library-author-facet-app-light-v1.png`
- `docs/assets/mobile-app-hifi-v1/library-filter-sheet-app-light-v1.png`
- `docs/assets/mobile-app-hifi-v1/work-detail-selected-volume-metadata-light-dark-v6.png`
- Phase 3, Phase 5, and `docs/mobile-app-work-detail-selected-volume-design.md` are authoritative for Work Detail composition and state behavior. The v6 asset is the only retained Work Detail design reference; v2–v5 design images have been deleted.

## Implementation review

- System-owned navigation, search, menus, sheets, refresh, buttons, alerts, and back behavior remain native controls.
- App-owned content uses the Warm Page semantic tokens, cover ratios, spacing scale, typography hierarchy, and progress treatment.
- Home, all three Library scopes, Facet, and Work Detail have explicit loading, content, empty, ordinary-error, pagination-error, cached/stale, and permission states where applicable.
- Compact grid adapts from three columns to two and then list presentation for narrow width or larger accessibility text.
- Reader is intentionally outside this phase; the Work Detail action remains visible and disabled with localized explanatory copy.
- iOS and Android strings are complete for zh-CN and en-US in the implementation catalogs.

## Runtime comparison

Current Android execution policy: local APK installation, instrumentation, screenshots, visual review, and final runtime acceptance default to an explicitly selected physical Android device. Emulator runs recorded below are historical milestone evidence only; they must not be reused as current final acceptance or cause automation to start an AVD when a physical device is available.

- Latest physical-device deployment: serial `9e896bbc`, model `M2102K1AC`, Android API 31. The current debug APK was replace-installed without clearing app data, cold-launched into `com.ermao.library/.MainActivity`, and produced no app `FATAL EXCEPTION` or ANR signature in the post-launch log scan.
- Android Emulator remains permitted only for an explicitly requested supplementary API/device matrix or CI without attached hardware.

- iOS physical device: `00008150-0011112211A0C01C`, iPhone 17 Pro Max, iOS 26.6. Simulator use was prohibited and no simulator was used.
- All 26 XCTest cases passed on the device. After the visual smoke check exposed an unregistered `ContentRoute` destination, the modifier was moved inside each `NavigationStack`; all 26 tests passed again and the affected journey was rerun.
- Home, Library Works, Series grouping, Series Facet, Work Detail, native back, and the native Filter Sheet were exercised through iPhone Mirroring against the test-only content fixture. The selected tab, source scope, and Library content were restored after back navigation.
- The XCUITest runner still exits before bootstrapping because the device refuses the `XCTestDriverInterface` channel (exit code 74). This is a runner/infrastructure failure before any test method executes, not an assertion failure; the equivalent critical path was therefore verified manually on the same physical device.
- Captured evidence for the prior content-discovery baseline (the Work Detail image below predates v2 and is not v2 acceptance evidence):
  - `design-qa/screenshots/ios-home-physical-zh.png`
  - `design-qa/screenshots/ios-library-physical-zh.png`
  - `design-qa/screenshots/ios-work-detail-physical-zh.png`
  - `design-qa/screenshots/ios-series-facet-physical-zh.png`
  - `design-qa/screenshots/ios-filter-sheet-physical-zh.png`
- Android Warm Page three-page milestone: API 36 AVD `Shuku_API_36` (`emulator-5554`), 1080×2400 at 420 dpi (about 412×915 dp), portrait, animations disabled, `font_scale=1.0`.
- The debug-only `VisualFixtureActivity` renders seven deterministic, offline scenarios. The blocking matrix is 7 scenarios × zh-CN/en-US × Light/Dark = 28 Android goldens. The comparator rejects channel differences greater than 8 when more than 0.5% of compared pixels differ; only the clock/status-icon area is masked. Modal fixtures use the device screenshot so the real Sheet is included; ordinary screens use the fixture window surface to exclude unrelated foreground windows.
- The default matrix and the six Light `fontScale=2.0` Home/Library/Work Detail structure captures passed (`VisualFixtureActivityTest`: 3 tests). Home's dedicated Compose test passed (1 test), and the existing shell/localization smoke suite passed (5 tests). Instrumentation execution is therefore non-zero and explicitly bound to `emulator-5554`.
- Final Android runtime evidence is in `design-qa/screenshots/android-warm-page-20260815-final/` (34 PNGs). The 28 blocking baselines are checked into `androidApp/src/androidTest/assets/warm-page-goldens/`.
- Passing instrumentation XML is archived in `design-qa/evidence/android-warm-page-20260815/` for the 3-test visual fixture, 1-test Home contract, and 5-test shell/localization smoke runs.
- `verifyDesignTokens`, `:shared:testAndroidHostTest`, the focused metrics/progress unit tests, debug APK assembly, Android-test APK assembly, replace-install, cold launch, version verification, and crash-log verification passed.
- The repository-wide Android unit and lint gates are not green for unrelated Reader work already present in the working tree: the full unit suite has one `DownloadReaderEntryPolicyTest` expectation mismatch, and `lintDebug` crashes inside the lifecycle lint detector while analyzing the dirty `ReaderActivity.kt`. A prior full instrumentation run also retained three Reader-only failures after the visual fixture was fixed. These failures were not skipped, weakened, or changed by this UI milestone.

### Work Detail v6 verification

Work Detail v2–v5 design and verification images were deleted to prevent design regression. Only the v6 design, specification, and evidence under `design-qa/visual-runs/20260816-work-detail-v6/` may be used for current Work Detail acceptance.

## Required follow-up evidence

Complete the remaining dark-mode, maximum Dynamic Type, VoiceOver, reduced-motion, landscape/iPad, Authors Facet, menu, search, empty/error, cached/stale, permission-revalidation, and pagination visual matrix before treating the full Phase 7 visual regression suite as complete.
