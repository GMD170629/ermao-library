# Content Discovery Design QA

Status: content-discovery compact/light smoke review passed. Work Detail v2 implementation, signed build, and its updated physical-device journey have passed.

## Reference set

- `docs/assets/mobile-app-hifi-v1/home-app-light-v1.png`
- `docs/assets/mobile-app-hifi-v1/library-app-light-v1.png`
- `docs/assets/mobile-app-hifi-v1/library-search-works-results-app-light-v1.png`
- `docs/assets/mobile-app-hifi-v1/library-series-scope-app-light-v1.png`
- `docs/assets/mobile-app-hifi-v1/library-authors-scope-app-light-v1.png`
- `docs/assets/mobile-app-hifi-v1/library-series-facet-app-light-v1.png`
- `docs/assets/mobile-app-hifi-v1/library-author-facet-app-light-v1.png`
- `docs/assets/mobile-app-hifi-v1/library-filter-sheet-app-light-v1.png`
- `docs/assets/mobile-app-hifi-v1/work-detail-introduction-ios-app-light-v2.png`
- `docs/assets/mobile-app-hifi-v1/work-detail-media-volumes-ios-app-light-v2.png`
- `docs/assets/mobile-app-hifi-v1/work-detail-ebook-chapters-ios-app-light-v2.png`
- `docs/assets/mobile-app-hifi-v1/work-detail-actions-sheet-ios-app-light-v2.png`
- Phase 5 and Phase 7 specifications are authoritative for composition and state behavior.

## Implementation review

- System-owned navigation, search, menus, sheets, refresh, buttons, alerts, and back behavior remain native controls.
- App-owned content uses the Warm Page semantic tokens, cover ratios, spacing scale, typography hierarchy, and progress treatment.
- Home, all three Library scopes, Facet, and Work Detail have explicit loading, content, empty, ordinary-error, pagination-error, cached/stale, and permission states where applicable.
- Compact grid adapts from three columns to two and then list presentation for narrow width or larger accessibility text.
- Reader is intentionally outside this phase; the Work Detail action remains visible and disabled with localized explanatory copy.
- iOS and Android strings are complete for zh-CN and en-US in the implementation catalogs.

## Runtime comparison

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
- Android: per the product-owner decision for this delivery, Android runtime tests and screenshots are not required. Static resource and source checks were completed; no runtime visual claim is made.

### Work Detail v2 verification

- The iOS and Android implementations now use first-level “About / Media Versions” tabs, three media kinds, title-adjacent facet navigation, title-under progress, and single-volume EPUB chapter fallback.
- Download progress and reading progress are separate. Because managed mobile downloads, reader launch, editing, cover updates, and reading-status mutation are not exposed by the current mobile capability contract, both clients render those actions unavailable instead of simulating completion.
- Shared KMP `iosArm64` compilation, design-token verification, signed physical-device `iphoneos` build, localization parsing, and source whitespace checks passed.
- The updated physical-device XCUITest passed on iPhone 17 Pro Max / iOS 26.6. It verified Library → Work Detail, disabled truthful reader CTA, About, Media Versions, single-volume EPUB chapter fallback, native back, Series scope, and Series Facet navigation.
- Passing-run evidence:
  - `design-qa/screenshots/ios-work-detail-v2-about-physical-en.png`
  - `design-qa/screenshots/ios-work-detail-v2-media-chapters-physical-en.png`
- No simulator was used.

## Required follow-up evidence

Complete the remaining dark-mode, maximum Dynamic Type, VoiceOver, reduced-motion, landscape/iPad, Authors Facet, menu, search, empty/error, cached/stale, permission-revalidation, and pagination visual matrix before treating the full Phase 7 visual regression suite as complete.
