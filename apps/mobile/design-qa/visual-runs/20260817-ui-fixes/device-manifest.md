# Android device evidence

- Captured: 2026-08-17 (Asia/Shanghai)
- Device serial: `9e896bbc`
- Device: Xiaomi M2102K1AC (`mars`), physical device
- Android: 12 (API 31)
- Display: 1440 × 3200, 560 dpi
- Package: `com.ermao.library` 0.1.0 (versionCode 1)
- Install method: data-preserving `adb install -r`
- APK SHA-256: `BF341A68A1A9E0C4FD5EE6EF402013216E60A07CA9120E67B4BB3914AB75D411`
- Locale/appearance: zh-CN, light
- Capture source: debug-only deterministic visual fixtures running inside the installed application package
- Product-shell smoke: cold launch resumed `com.ermao.library/.MainActivity`; no AndroidRuntime crash was present in the post-launch log window
- Automated evidence: focused Compose tests passed; 28 locale/appearance fixture captures passed; English work-detail popup locale test passed; status toggle, downloaded-volume long press/removal confirmation, and full-path dialog interaction test passed

The live server was unavailable during the product-shell smoke, so data-dependent screenshots use the repository's deterministic in-app fixtures. They exercise the production composables while keeping content and capture state stable.
