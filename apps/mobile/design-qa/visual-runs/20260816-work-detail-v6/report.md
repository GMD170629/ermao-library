# Work Detail v6 implementation run

This run replaces the previous Work Detail implementation with the frozen v6 continuous layout. The checked-in v6 board and `docs/mobile-app-work-detail-selected-volume-design.md` are the sole current design sources.

## Automated gates

- `:androidApp:testDebugUnitTest`: pass
- `:shared:allTests`: pass
- `:androidApp:lintDebug`: pass
- `:androidApp:assembleDebug`: pass
- `:shared:compileKotlinIosArm64`: pass
- Android replace-install on physical `9e896bbc`: pass, app data preserved
- Android cold-launch crash/ANR scan: pass before the device returned to its secure lock screen
- iOS `iphoneos` physical-device build/runtime: pending; no physical Apple device is available in this environment

## Physical visual status

The final v6.1 APK was replace-installed with app data preserved on physical Android `9e896bbc`. Cold launch resumed `com.ermao.library/.MainActivity` with no crash/ANR evidence. The same real library work used in the reported device image was recaptured above and below the fold. The captures verify the combined identity line, filled tags, normalized description and centered chevron, Media Versions selector, volume rail, six selected-volume metadata rows, normal bottom navigation, and absence of a Work Detail directory. No emulator evidence is used as a substitute.

## v6.1 correction run

The physical v6 reviews exposed six visual regressions plus adjacent raw-HTML leakage in the description. The durable acceptance contract is recorded in `issue-ledger.md` as WD-V61-01 through WD-V61-06. Android and iOS implementations now share the corrected author/series line, filled tags, plain-text description with centered chevron, fixed-width available-media selector, and hidden Work Detail directory. Android automated, replacement-install, cold-launch, and same-device visual gates pass. iOS remains pending a physical Apple device; shared `iosArm64` compilation passes but is not presented as iOS visual acceptance.

The follow-up WD-V61-06 correction prevents a single available media kind from stretching across the selector. Physical Android UI bounds confirm the Ebook segment is exactly 280 px on the 560 dpi device, equivalent to the locked 80 dp width. No Comic or Audiobook placeholder is rendered.
