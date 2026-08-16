# Work Detail control menu v2 QA

Status: Android physical-device PASS; cross-platform acceptance is pending iOS physical-device evidence.

## Frozen target

- The translucent control card is 224 dp/pt wide, uses a compact 38 dp/pt cover header and a single-line body-sized title, and retains 48 dp/pt minimum action targets.
- The card is positioned from the actual trigger coordinate, flips above or to the opposite side when necessary, and is clamped inside safe drawing bounds. It is not attached to a screen corner.
- A volume menu opens only from a long press on the volume cover.
- Form actions open a focused native Sheet over Work Detail. They do not navigate to a standalone management or edit screen.
- The supplied Emby image is an interaction reference for contextual editing, not a visual or field-for-field source of truth.

## Android physical-device evidence

- Device: Xiaomi `M2102K1AC`, Android 12 / API 31, serial `9e896bbc`.
- Book menu: `iteration-02/android/work-detail/zh-CN-light/01-book-menu.png`.
- Direct in-detail Edit Sheet: `iteration-02/android/work-detail/zh-CN-light/02-edit-sheet.png`.
- Volume-cover long-press menu at the pressed coordinate: `iteration-02/android/work-detail/zh-CN-light/03-volume-menu-at-touch.png`.
- Combined reference/implementation review: `iteration-02/reference-vs-android-edit-sheet.png`.
- The final debug APK was replace-installed without clearing app data, cold-launched to `com.ermao.library/.MainActivity`, and produced no app crash or ANR signature in the post-launch scan.
- Installed version: `0.1.0` (`versionCode=1`). APK SHA-256: `5660113CB6642EBF89E0DF48672DB1EE1E0285BA5B5E258E25CFAF8298D48A4C`.

## Automated verification

The following command passed without warnings introduced by this change:

```text
./gradlew :androidApp:lintDebug :androidApp:testDebugUnitTest :shared:allTests :androidApp:assembleDebug
```

The standalone Android management navigation destination, screen composable, page/scope selector, callbacks, and now-unused localized copy were removed. Task forms are composed directly by Work Detail through `WorkManagementTaskSheet`.

## Remaining gate

iOS source has the same pointer anchoring and focused Sheet routing, but this Windows workspace cannot perform the repository-required signed `iphoneos` build, installation, or physical-device visual run. No Simulator evidence was used. Cross-platform status therefore remains pending rather than claimed as PASS.
