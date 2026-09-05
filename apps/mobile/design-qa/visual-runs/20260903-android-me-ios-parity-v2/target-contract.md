# Android Me / iOS settings parity contract v2

Status: frozen for implementation

## Authoritative target

- User feedback from 2026-09-03 is the product decision for this iteration.
- Settings content, ordering, permission filtering, and trailing values follow the current iOS `MeRootView` and the shared `SettingsCenterCatalog`.
- The Android root title follows the same `WarmPageScaffold` root-title implementation used by Home, Library, and Shelves.
- Android keeps platform-native Material icon geometry; iOS SF Symbols are a semantic reference, not a pixel target.
- The existing physical-device capture `../20260903-android-settings-v1/screenshots/primary/me-root.png` is the accepted baseline, not the target.

## Primary checkpoint

- Platform: Android physical device `9e896bbc` (Xiaomi M2102K1AC), compact portrait.
- Flow: cold launch authenticated shell -> select Me -> capture the root at the top; scroll to the system-management/server/preferences/product region and capture the lower state.
- State: `zh-CN`, App Light, font scale 1.0, administrator with system-management capability.

## Must-match axes

- The Me title has the same typography, bar height, and fixed root-page placement as the other Android root tabs.
- Every settings glyph is an outline Material icon with one consistent visual weight; only the selected bottom-tab icon may remain filled.
- Every navigation row uses an open chevron instead of a solid arrowhead.
- Root settings rows do not render explanatory/supporting descriptions.
- Root content follows the iOS/shared catalog order: Profile, Account & Security, Downloads, Email & Kindle, Kindle Send Queue, permission-filtered Users and Permissions / OPDS / System Logs, current server, Language, About.
- Profile, Downloads, Email & Kindle, Kindle queue, current server, Language, and About expose the same trailing status/value semantics as iOS when the value is available.
- The server row remains read-only and shows server name/address plus a trailing Current value.
- Existing navigation destinations, authorization checks, and user actions remain functional.

## Platform-adapted axes

- Android Material Symbols do not need to duplicate SF Symbols paths, but both platforms use outline state for unselected/settings navigation icons.
- Android owns status bars, bottom navigation, touch feedback, predictive back, and exact text metrics.

## Data-dependent axes

- Download count is omitted when there are no records.
- Email & Kindle shows Configured only when the loaded settings snapshot reports SMTP configured.
- Kindle queue shows a count only when one or more failed tasks are present.
- Permission-filtered system-management rows are absent when the actor lacks the corresponding capability.

## Explicit exclusions

- No backend, KMP contract, persistence, or API behavior changes.
- No redesign of profile, security, language, About, downloads, administrative detail pages, or Reader settings.
- No iOS code changes and no claim of cross-platform pixel equality.
- No destructive reset of app data or the existing dirty workspace.
