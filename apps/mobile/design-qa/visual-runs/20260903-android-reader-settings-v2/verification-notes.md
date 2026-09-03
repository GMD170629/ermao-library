# Android Reader Settings v2 verification notes

Current acceptance state: BLOCKED by a securely locked physical device.

## Passed

- Reader settings generator drift check: `python packages/reader-contracts/generate-reader-settings.py --check`.
- Shared KMP catalog tests: `:shared:testAndroidHostTest`.
- Android unit tests: `:androidApp:testDebugUnitTest`.
- Android production and instrumentation compilation.
- Debug APK and Android test APK assembly.
- `git diff --check`.

## Pending physical-device gates

- The device remains the required Xiaomi M2102K1AC, Android 12, 1440x3200, density 560.
- Both current APKs are installed with `adb install -r`.
- Reader instrumentation and visual capture were attempted, but the device reports a secure keyguard. The visual harness correctly failed closed with `Unlock the physical device before capturing Reader screenshots`.
- Re-run the Reader presentation tests and Reader visual capture directly through the installed instrumentation package after unlock; do not use the Gradle connected-device task because it uninstalls the debug application when it finishes.
- Capture and review EPUB, PDF, and comic Settings/Advanced Settings, then add current-build screenshots and a blind review result to this run.

## Known repository-wide gate

`lintDebug` still fails with 36 existing errors. The first failure is an unrelated Media3 opt-in error in `AndroidAudioPlaybackService.kt`. The lint report contains no error in the Reader files changed for this candidate, and no lint rule or baseline was weakened.

## Device data note

The first Gradle connected-device attempt removed the existing `com.ermao.library` debug package at teardown, so its prior local debug-app preferences and cache were not preserved. The current candidate was subsequently installed with `adb install -r`; server-side library data was not affected.
