# Work Detail control menu — option 1 QA

## Result

Visual implementation: **passed on Android physical device**.

Full interaction acceptance: **blocked pending iOS physical-device evidence and direct task routing for the existing management forms**. The floating menu, entry points, ordering, state-aware download behavior, permission filtering, and destructive-action placement are implemented. Complex management actions currently open the existing management surface rather than entering a dedicated task sheet directly.

## Target and evidence

- Selected reference: `docs/assets/mobile-app-hifi-v1/work-detail-book-control-menu-floating-card-v1.png` (`850 × 1840`, SHA-256 `61742F06649D9964B0ECE7E03C5F03E6309DE1660CFBA41EBB0C84A9EE114BBA`).
- Android implementation: `iteration-02/android/work-detail/zh-CN-light/03-book-menu-open.png` (`1440 × 3200`).
- Volume long-press state: `iteration-02/android/work-detail/zh-CN-light/04-volume-menu-open.png` (`1440 × 3200`).
- Combined comparison: `iteration-02/reference-vs-android-book-menu.png`.
- Device: Xiaomi M2102K1AC, Android 12 / API 31, serial `9e896bbc`, portrait, 1440 × 3200, density 560.
- State: authenticated administrator, zh-CN, light theme, TXT volume. Because the selected volume is TXT, “发送到 Kindle” is correctly omitted; EPUB/PDF eligibility remains conditional in code.

## Visible comparison findings

- The menu is anchored to the right with a compact card width, safe-area margin, rounded outline, elevation, dimmed background, and translucent/blurred material.
- The page remains identifiable beneath the overlay; focus is moved to the menu without turning it into a full-screen management page.
- Header identity, consistent action rows, internal scrolling, and pinned destructive action match the selected option’s hierarchy.
- The book menu and volume-cover long-press menu share the same visual component while preserving their separate action sets.
- The top-right Work Detail overflow action is absent.
- Android uses window blur behind the dialog as the platform-equivalent implementation of the selected frosted-card effect.
- Reference and runtime data/theme differ, so pixel equality is not a valid criterion; the comparison is accepted on composition, hierarchy, density, material, and interaction state.

## Verification

- `:androidApp:lintDebug` — passed.
- `:androidApp:testDebugUnitTest` — passed.
- `:shared:allTests` — passed.
- Debug APK replace-install — passed without clearing app data.
- Cold launch resumed `com.ermao.library/.MainActivity` — passed.
- Post-launch crash/ANR scan — no matching entries.
- iOS localization catalog JSON validation — passed.
- iOS compile/runtime/visual evidence — pending a connected physical iPhone/iPad; Simulator evidence is prohibited by repository policy.
