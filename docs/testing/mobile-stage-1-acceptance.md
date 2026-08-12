# Mobile Stage 1 acceptance record

- Scope: server profiles, first-run setup, login, reauthentication, offline
  entitlement, private-data namespaces, and authenticated-shell gating
- Status: implementation and acceptance in progress
- Stage 0 prerequisite: Shared, Android, backend, emulator deployment, and real
  FastAPI base-path/TLS evidence passed; the physical-device iOS gate remains pending
- Rule: a missing iOS environment may defer iOS evidence, but it does not convert the
  iOS job into an allowed failure and does not permit Stage 1 to be marked complete

## Evidence collected on 2026-08-12

- Ruff format and lint passed for the Mobile compatibility and authentication contract
  files.
- The focused compatibility, Mobile authentication, and existing authentication suite
  passed with 34 tests and one pre-existing Starlette/httpx deprecation warning.
- The complete backend suite reached a final result: 1,079 passed, 5 skipped, and 3
  failed in 477.46 seconds. All three failures are the existing RAR comic tests and are
  caused by this WSL host not providing an `unrar`, `unar`, or compatible 7-Zip binary;
  they are unrelated to the Mobile authentication contract. The full suite is therefore
  not recorded as green, while the focused Mobile contract gate remains green.
- Shared Android-host tests, Android unit tests, warnings-as-errors lint, design-token
  verification, and the Debug APK build passed on the same working tree.
- The Debug APK (`0.1.0`, version code `1`) was replace-installed and cold-launched on
  the `Shuku_API_36` emulator. Foreground launch was verified and the launch crash log
  was clean.
- All six Android instrumented tests passed on API 36, including encrypted platform
  storage and the Stage 0 profile-payload migration to the explicit v2 aggregate.
- iOS resource/catalog and project-reference static checks passed. Linux cannot run
  Xcode, XCTest, physical-device iOS tests, or claim iOS runtime acceptance.
- No minimum-API, physical-device, accessibility, or disposable real-server Stage 1
  journey is claimed by this record yet.

## Contract baseline

The backend contract suite freezes the Mobile authentication surface:

| Method and path | Success | Required failure contracts |
| --- | --- | --- |
| `GET /api/auth/setup/status` | `200`, typed envelope, `Cache-Control: no-store` | none |
| `POST /api/auth/setup` | `201`, admin session and cookies | `409`, `422` |
| `POST /api/auth/login` | `200`, session envelope and cookie | `401`, `403 ACCOUNT_DISABLED`, `409 SETUP_REQUIRED`, `422` |
| `GET /api/auth/me` | `200`, user/authorization/preferences | `401` |
| `POST /api/auth/session/refresh` | `200`, refreshed session cookie | `401`, `503 SESSION_REFRESH_DEFERRED` |
| `POST /api/auth/logout` | `200`, `loggedOut: true`, cookie deletion | idempotent without an active cookie |

The Mobile client must treat `/api/auth/me`, not the presence of a cookie or a successful
setup/login response, as the final authorization truth. Program branches use stable error
codes and typed fields, never localized messages.

## Required deterministic gates

Run all gates against one source revision.

Backend:

```bash
cd apps/api-python
uv run --extra dev --locked ruff format --check \
  tests/contract/api/test_mobile_compatibility.py \
  tests/contract/api/test_mobile_auth_contract.py
uv run --extra dev --locked ruff check \
  tests/contract/api/test_mobile_compatibility.py \
  tests/contract/api/test_mobile_auth_contract.py
uv run --extra dev --locked pytest -q \
  tests/contract/api/test_mobile_compatibility.py \
  tests/contract/api/test_mobile_auth_contract.py
uv run --extra dev --locked pytest -q
```

Shared and Android:

```bash
cd apps/mobile
./gradlew --stacktrace \
  verifyDesignTokens \
  :shared:testAndroidHostTest \
  :androidApp:testDebugUnitTest \
  :androidApp:lintDebug \
  :androidApp:assembleDebug
./gradlew :androidApp:connectedDebugAndroidTest
```

iOS, when a connected physical iPhone, JDK 17, current Xcode, and signing are available.
Set `IOS_DEVICE_ID` to the physical-device identifier shown by `xcodebuild -showdestinations`:

```bash
cd apps/mobile
./gradlew verifyDesignTokens :shared:compileKotlinIosArm64
cd ../..
xcodebuild \
  -project apps/mobile/iosApp/ErmaoLibrary.xcodeproj \
  -scheme ErmaoLibrary \
  -configuration Debug \
  -destination "platform=iOS,id=$IOS_DEVICE_ID" \
  -allowProvisioningUpdates build
xcodebuild \
  -project apps/mobile/iosApp/ErmaoLibrary.xcodeproj \
  -scheme ErmaoLibrary \
  -configuration Debug \
  -destination "platform=iOS,id=$IOS_DEVICE_ID" \
  -allowProvisioningUpdates test
```

The `Mobile Stage 1` workflow keeps the macOS job required and uploads backend JUnit,
Android build/test, instrumented-test, and iOS result bundles for failure diagnosis.

## Functional acceptance matrix

Use disposable FastAPI databases and gateway instances. Never use production accounts or
servers.

### Server profiles and TLS

- Fresh install opens the profile gate and cannot reveal the private shell.
- Add and edit preserve a complete base path; health, compatibility, setup status, and
  authentication calls use that path.
- Exactly one profile is active. A failed switch leaves the previous profile active and
  does not send its cookie to the target server.
- Editing an active server identity follows the same isolation rules as switching.
- Removing a profile clearly accounts for its cookie, entitlement, cache, downloads, and
  pending outbox; cleanup is idempotent and never silently discards pending work.
- System trust is the default. The insecure TLS exception requires the risk page and a
  native destructive confirmation, is stored per profile, and never becomes global.
- Incompatible servers cannot reach setup/login or bypass compatibility checks.

### Setup, login, and shell gating

- An uninitialized server shows native Setup with name, email, password, and password
  confirmation; the client validates confirmation and the server enforces password length.
- Setup `422` errors attach to their fields. Setup `409` rechecks status and replaces the
  route with Login without resubmitting the form.
- Invalid login keeps the normalized email, clears no unrelated profile data, and uses the
  anti-enumeration message. A disabled account opens a blocking gate without exposing the
  cached private shell.
- Setup/login success is followed by `/api/auth/me`. Only a verified response may open the
  four-tab shell.
- Force-stop and cold launch restore only the active profile's encrypted cookie, then
  revalidate through `/api/auth/me` before showing private content.

### Reauthentication, entitlement, and namespace

- An explicit protected-resource `401` opens full-screen Reauthenticate and preserves
  pending sync work. It never leaves the old shell visible underneath.
- Each successful `/api/auth/me` records a 30-day entitlement bound to
  `serverIdentity + userId`. Expiry boundaries are deterministic; a wall-clock rollback
  cannot extend access and is treated as expired.
- Offline grace exposes only complete downloads, local bookmarks, and pending sync state.
  Expired entitlement removes the offline entry. Explicit logout, account disablement, or
  server-identity mismatch revokes it immediately.
- Reauthenticating as the same server/user restores only a validated navigation intent.
  A different user clears all four tab stacks and opens Home.
- Private data is namespaced by `serverIdentity + userId + authzVersion`. An authorization
  version change immediately masks the old namespace and pauses inactive-server work.

## Platform and accessibility evidence

For every frozen Phase 6 state, collect behavior evidence in `zh-CN` and `en-US`, App
Light and App Dark, default and large text, and with reduced motion enabled. Verify native
back behavior, focus restoration, password-manager semantics, TalkBack/VoiceOver labels,
and the longest English copy. System-owned controls are accepted by platform behavior;
App-owned content may use platform-specific visual regression images.

Minimum device coverage:

- Android: minimum supported API plus API 36 emulator, and one physical device for
  process death, Keystore, TLS, network transitions, and system back.
- iOS: at least one connected physical iPhone for every build/test gate, including
  process death, Keychain, TLS, Dynamic Type, VoiceOver, and the supported OS-version matrix.

## Exit criteria

Stage 1 is complete only when all of the following are true on the same candidate revision:

- backend, Shared, Android, Android emulator, KMP iOS, Xcode build, and XCTest gates pass
  without new skips, flaky retries, warnings, or weakened checks;
- Server Center, native Setup, Login, Reauthenticate, 30-day entitlement, logout, server
  switching/removal, and namespace invalidation contain no Stage 0 placeholders or
  fallback-to-success paths;
- the disposable real-server journeys pass for fresh setup, login, process restart,
  two-server isolation, TLS risk, `401`, disabled account, entitlement expiry, and
  authorization-version changes;
- passwords, cookies, certificate details, internal paths, and private payloads do not
  appear in logs or plaintext preferences;
- Phase 6 states have bilingual, light/dark, large-text, accessibility, and platform-back
  evidence on both platforms.

Until the iOS environment is available, the maximum permissible status is:

> Shared/Android/backend Stage 1 conditionally accepted; overall Stage 1 awaiting physical-device
> iOS build, XCTest, real-server smoke, and runtime evidence.
