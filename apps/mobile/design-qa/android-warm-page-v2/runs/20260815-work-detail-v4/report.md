# Android Work Detail v4 visual acceptance

Final result: **HISTORICAL ONLY**. This v4 acceptance record is retained as runtime history; its retired design image has been deleted and it must not be used for current comparison.

## Sources

- Current authoritative composition reference: `docs/assets/mobile-app-hifi-v1/work-detail-selected-volume-metadata-light-dark-v6.png`
- Functional source: the existing iOS `WorkDetailView` behavior and the existing Android `WorkDetailUiState` callbacks.
- Android actual: `final/work-about-zh-CN-light.png`
- Android actual SHA-256: `2341999dc58036aa5de61e13923969b14ec357094d887adec82e735dfd3a132f`
- Side-by-side review image: `comparison-reference-left-actual-right.png` (reference left, Android actual right).

The comparison normalizes image width only. It intentionally does not claim a cross-platform pixel-golden result: the supplied design is an iOS composition at 942×1668, while the Android runtime is API 36 at 1080×2400 / 420 dpi. Android system insets, Material touch targets, and platform text metrics remain platform-owned.

## Accepted composition

- Centered Material detail top bar with native back and overflow behavior.
- Hero cover, title, author facet, real format, reading progress, and current reading position.
- Equal-width soft secondary shelf action and unique filled reader CTA.
- Continuous About card with expandable description, real series facet, format, and file size.
- Media selector only when multiple media types actually exist.
- Four-across horizontal volume shelf with current/download state, 2 dp selection treatment, independent download action, and reading progress.
- Continuous chapter card for the selected/single ebook volume.
- Large text changes the hero and actions to a vertical layout without shrinking the 48 dp targets.

## Deliberately excluded fields

Rating, reading time, publication date, language, page count, ISBN, and source are absent from the current mobile contracts. They are not rendered or fabricated. The implementation only renders the real format and `sizeBytes` metadata currently supplied by the app.

## Verification

- `verifyDesignTokens`: passed.
- `:shared:testAndroidHostTest`: passed.
- Focused Android theme/component unit tests: passed.
- `:androidApp:lintDebug`: passed.
- `:androidApp:assembleDebug`: passed.
- `:androidApp:assembleDebugAndroidTest`: passed.
- Work Detail reference-state instrumentation: 1 test passed, capturing About, multi-volume, and single-ebook states.
- `fontScale=2.0` structural capture: 1 test passed across zh-CN/en-US for Home, Library, and Work Detail (6 captures).
- Final emulator: `emulator-5554`, `Shuku_API_36`, API 36, 1080×2400, 420 dpi, font scale 1.0.
- APK: `androidApp/build/outputs/apk/debug/androidApp-debug.apk`
- APK SHA-256: `d326f27df9ec8d777d1dd005db78662d37bf81017eac9f2e865aa6fdf059a96c`
- Replace-install and cold launch: verified; deployment crash scan clean.

The complete Android unit suite still reports the two pre-existing Reader CSP failures in `EpubContentSecurityPolicyTest` (78/80 pass). This Work Detail change does not touch the Reader security implementation, and the failures were not suppressed or re-baselined.

No physical Android device was modified.
