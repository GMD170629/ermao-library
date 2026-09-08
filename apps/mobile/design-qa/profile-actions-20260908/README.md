# Android profile and action audit — 2026-09-08

## Target v1

User-owned target: display only the avatar image addressed by the account response; never synthesize an initial, illustration or fallback avatar on Android. Replace bare text actions with semantic icon controls (camera for photo selection) or native styled icon-and-label buttons. Preserve the existing page order, callbacks, locale labels, minimum touch targets, disabled/loading states and native picker/dialog behavior.

Primary: physical Xiaomi M2102K1AC, Android 12, serial `9e896bbc`, 1440 × 3200, portrait, Chinese, light theme, normal font scale. Enter through Home → Me → Profile. No avatar is present for this account; account text is data-dependent and is not reproduced in this report. Existing Me reference: `docs/assets/mobile-app-hifi-v1/me-app-light-v1.png`; the user's request supersedes its decorative account example.

## Ownership and migration

- Avatar transport remains `SettingsClient.loadAvatar` → shared `PersonalSettingsRepository.loadAvatar` → authenticated asset transport. `MeViewModel.loadAccountAvatar` is the single Android loading owner for initial load, upload/delete results and changed avatar URLs.
- Removed the client-generated initial avatar and the local pending-image override. Upload success no longer publishes the selected file bytes as the account avatar. Null and failed responses do not generate an image; delete responses with a server-provided default URL are loaded normally.
- Reused `WarmPageIconAction` for photo selection, removal and compact batch download actions. `SettingsSaveAction` retains one shared implementation and now renders a check icon or progress indicator.
- Replaced bare native text actions across account/security, authentication, servers, administration, library/detail, shelves, downloads, work management, audio recovery and Reader dialogs/settings with native styled controls and meaningful icons.
- Removed `WarmPageTextAction`; all seven callers use the existing `WarmPageSecondaryAction` owner. The five remaining native `TextButton` calls already contain icon content (audio/Reader tools, server switch/removal, folder disclosure), rather than bare text.
- Pagination numbers and native list/selection controls retain their semantics. Batch download actions use compact icons with localized action/count descriptions.
- Removed 11 unused legacy download resources from both locale catalogs after reference search and lint identified them. No lint exclusions or rule weakening were added.

## Verification

- `:androidApp:testDebugUnitTest --tests com.ermao.library.features.me.MeViewModelTest`: 6 passed, 0 skipped. Covers response URL/bytes after upload, pending bytes not becoming the account avatar, reopening, unauthorized image failure and retry, server-default delete response and null delete response.
- Physical-device instrumentation: 10 passed, 0 skipped across `MeSettingsScreensTest`, `WarmPageActionsTest`, `LibraryFilterSheetTest`, `LibraryFilterSheetHeaderTest`. Includes pixel verification of server response image while a different local image is pending, removal of initial fallback, camera accessibility/disabled state, save state, localized actions and narrow/large-text filtering layout.
- `:androidApp:assembleDebug :androidApp:assembleDebugAndroidTest :androidApp:lintDebug --no-configuration-cache --max-workers=1`: passed (`quality-gate.log`). Earlier concurrent lint runs crashed inside the detector; isolated execution completed without disabling checks.
- `git diff --check`: passed.
- The exact Web i18n script validated 2,106 messages for zh-CN/en-US using `PYTHON_EXECUTABLE` and the bundled Node runtime. The `pnpm i18n:check` wrapper itself was blocked by the host pnpm/Node version mismatch; no engine requirements were changed.
- The camera action reached the native photo selection flow. The device showed MIUI's first-use consent surface; no unrelated permissions were granted and no real account avatar was uploaded or deleted.
- A concurrent device test interrupted the first instrumentation run and temporarily replaced/stopped the application. That interrupted run and old-build screenshots are not acceptance evidence. The successful retry and final replace-install are recorded separately.

## Visual review

Primary baseline: `before.png`. Candidate 1: `after.png`. Candidate 2: `final.png`. Final packaged build: `final-packaged.png`.

| Axis | Relative to target / previous baseline |
| --- | --- |
| Avatar source | Better: no client-generated initial or local pending-image substitution |
| Photo action | Better: recognizable camera icon with localized accessible label |
| Save affordance | Better: compact check icon, avoiding a newly enlarged capsule |
| Section order and content | Same: title, account identity, display-name field |
| Typography, colors, shell | Same token owners and native shell |
| Vertical density | Expected data-dependent change: removal of synthetic avatar; no new sections |
| Callback/disabled behavior | Preserved; covered by device tests |

Implementer primary review: no remaining actionable issue in the supplied state. Independent first-stage blind review: zero actionable findings; no overlap, clipping or bare text actions in the final profile screenshot. Independent second-stage evidence review is recorded in the task conversation.

Scope limit: whole-Android source audit plus targeted device tests; not a screenshot certification of every Android page/theme/state. Live custom-avatar upload/delete were exercised with owned fake ports and native rendering tests, not by altering the real user's account. TalkBack end-to-end navigation, every administrator state and all Reader formats were not exhaustively rerun for this presentation-only change.

## Build

Package `com.ermao.library`, version `1.0.0` (1). Final APK: `profile-actions-final.apk`.
SHA-256: `23DB3458B36F81C4A718BF4996377A8852E1FC9C60D6458B15A5ABFB447BC133`.
Installation uses data-preserving `adb -s 9e896bbc install -r`, force-stop, cold launch and package/activity verification. Original screenshots and APKs stay local and are excluded from Git because the product screenshots contain account information.

## Default-avatar unification (target v2, supersedes v1 empty default)

The user subsequently requested unification across clients. `avatarImageUrl` now comes from the authentication response, while nullable `avatarUrl` remains the custom-upload marker. The backend delivers its packaged default WebP through authenticated `/api/auth/avatar`; Web, KMP/Android and iOS consume the supplied address. The former Web icon fallback and iOS BrandMark fallback are removed. Missing/failed responses never synthesize an image. See `docs/adr/server-owned-account-avatar.md`.

The v1 screenshots above document icon styling and response-only behavior, not a live default-avatar deployment. The running NAS was not deployed during this source change. The backend response is verified through real HTTP contract tests; native bytes rendering through physical-device tests.

Final combined verification on 2026-09-09:

- Backend: 28 authentication and avatar contract tests passed. Default delivery, upload, delete, reopening, missing files and out-of-root references are covered. Existing Starlette/httpx deprecation warning remains in the test environment; no dependency upgrade is included.
- Backend ruff checks/format and mypy passed (498 source files).
- Web: typecheck and lint passed; 485 tests passed, zero skipped; 2,106 locale messages validated. Pinned Node 22.23.1 was located. The test runner and i18n script ran directly with PYTHON_EXECUTABLE configured because the pnpm pretest wrapper's `python3` command is absent on Windows.
- Android: debug app/test APK build, unit tests, shared host tests and lint passed (`unified-avatar-build.log`). The added KMP default-display contract test passed in `default-wire-tests.log`.
- Physical Android: 21 tests passed across profile, shared actions, filter sheets and book management (`unified-device-tests.log`), using the combined workspace build, including concurrent book-management updates.
- iOS source and a default-avatar test were updated; macOS compilation and iOS physical-device execution are unavailable on this Windows host and are not claimed.

Source commit includes all local version-control updates requested by the user. Private screenshots, local APKs and runtime logs in this directory remain ignored; the other task's synthetic book-management QA evidence is included.

Final combined APK SHA-256: 5B78F0B2D12CCFF5C65B8B0672ED52EA367EE6D5A4607B3F8B66C997340EAA1D. Data-preserving install succeeded on device 9e896bbc; MainActivity cold launch returned Status ok (434 ms).
