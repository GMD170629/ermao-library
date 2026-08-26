# Work Detail Emby-Inspired Refinement — Physical iOS QA

final result: passed

Scope: the selected iOS visual target and the five detail-page refinements requested on 2026-08-25. Android received the matching component changes and compiles, but Android runtime acceptance remains pending because no physical ADB device was connected.

## References and evidence

- User target: `/var/folders/d8/2c367y3s79b_hrmg8d1b8vzm0000gn/T/codex-clipboard-c1dcf6e6-d089-437a-94d1-92a70085a459.png`
- User's current-state capture: `/var/folders/d8/2c367y3s79b_hrmg8d1b8vzm0000gn/T/codex-clipboard-a1e0954a-bbdb-4d25-af53-4491e87665fd.png`
- `reference-and-ios-user-data.png`: side-by-side comparison against the real signed-in book state on physical iPhone.
- `reference-and-ios-physical.png`: side-by-side comparison against the deterministic physical-device fixture containing series, tags, description, progress, and chapter states.

## Blocking visual checks

- PASS — The cover-derived backdrop reaches behind the transparent navigation bar and through the top safe area.
- PASS — Primary and quick actions use a play triangle, down arrow, checkmark, bookmark, and ellipsis with one coherent optical weight.
- PASS — Chapter reading state is expressed with text only; the duplicate chart/check/circle state glyphs were removed.
- PASS — Series appears on the same creator line after the author, and non-empty tags render immediately below as restrained chips.
- PASS — The description has no section heading or empty placeholder. Long text uses a light trailing expand/collapse text action.
- PASS — The bottom tab bar does not cover the current chapter row at the captured compact viewport.
- PASS — Native back navigation, primary reading action, action menus, facet links, and chapter rows remain interactive.

## Remaining non-blocking note

- P3 — Books without a cover or cover-derived color naturally show the canvas in the hero safe area; this is preferable to inventing decorative artwork.

## Verification

- iOS `iphoneos` Debug build succeeded for physical device `00008150-0011112211A0C01C`.
- The app was replace-installed without clearing data and cold-launched successfully.
- Real signed-in data and the fixture state were inspected through iPhone Mirroring on the same device.
- The focused XCUITest could not start because the scheme still compiles pre-existing stale `MobiPublicationFactoryTests` APIs (`sourceID` versus `resourceID`, missing `assetID`). The production target and this view compile successfully; no test was skipped or weakened.
- Android `:androidApp:compileDebugKotlin` succeeded with the matching visual changes.
- `adb devices -l` returned no physical Android device, so Android screenshot/runtime acceptance is pending and no emulator was used.

## Interaction regression follow-up

- PASS — The former coordinate-driven full-screen custom book menu was replaced by a native `Menu`.
- PASS — “更多” opens immediately on the physical iPhone and exposes add-to-shelf, mark-unread, and download actions.
- PASS — The reading-status native menu opens and exposes both manual states.
- PASS — Add-to-shelf opens its Sheet and can be dismissed without mutating membership.
- PASS — Description expansion no longer animates the entire long ScrollView.
- PASS — The cover-derived backdrop blur was reduced and rasterized offscreen on iOS; Android uses the same reduced blur radius.
