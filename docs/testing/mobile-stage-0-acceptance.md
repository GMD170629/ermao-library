# Mobile Stage 0 acceptance record

- Source revision date: 2026-08-12
- Android status: implementation, combined Gradle gate, emulator deployment, device tests,
  and real FastAPI base-path E2E complete
- iOS status: implementation and static project checks complete; macOS/Xcode gate pending

## Implemented scope

- The untracked Expo/React Native output was removed and replaced by a two-module KMP
  build (`:shared`, `:androidApp`) plus a native SwiftUI Xcode project.
- The backend exposes the unauthenticated typed
  `GET /api/mobile/compatibility` handshake and persists one stable
  `mobile.serverIdentity` through the ORM seed and backup/restore contract.
- Shared Kotlin owns canonical server URLs, bounded safe redirects, compatibility,
  envelopes and normalized errors, profile-isolated persistent cookies, authorization,
  the explicit application session state machine, navigation intents, and distinct
  library wire/domain models.
- Android provides the Compose bootstrap/auth gates, per-profile Keystore/AES-GCM cookie
  persistence, DataStore profiles, generated Warm Page theme, and four independent
  Navigation 3 tab stacks.
- iOS provides the SwiftUI bootstrap/auth gates, Keychain cookie persistence,
  UserDefaults profiles, generated Warm Page theme, four independent NavigationStack
  paths, a stable KMP adapter, XCTest targets, and a shared Xcode scheme.
- `design/tokens.json` is the only numeric token source. Gradle generates Kotlin, Swift,
  and Android resources without adding a Node package.

## Evidence collected on the Windows/WSL host

Backend:

- Changed-source Ruff format/check: passed.
- Mobile capability mypy (`--follow-imports=skip`): passed with 11 source files.
- Focused compatibility, identity, seed, and route-ownership rerun: 9 passed.
- Complete pytest passed with 1076 tests, 5 existing skips, and one third-party
  Starlette/httpx deprecation warning. The host did not provide a RAR extractor, so the
  run used a disposable 7-Zip adapter without changing the machine or repository.
- Repository-wide Ruff format remains blocked by 81 pre-existing unrelated files. All
  17 changed backend source and test files pass Ruff format/check, and the new mobile
  capability passes mypy without import skipping errors of its own.

Shared/Android final combined gate:

- `verifyDesignTokens`, `:shared:testAndroidHostTest`,
  `:androidApp:testDebugUnitTest`, `:androidApp:compileDebugAndroidTestKotlin`,
  `:androidApp:lintDebug`, and `:androidApp:assembleDebug` passed together on Gradle
  9.3.1 with JDK 17. After adding the final authentication/session regressions, the
  shared suite was rerun separately with 33 passing tests and no failures.
- The final shared regressions cover invalid credentials, disabled accounts, nested
  Setup Required, saved-server 503 behavior without false expiry, incompatible protocol
  short-circuiting, every frozen `AppSessionKind`, authorization truth, and private
  namespace projection.
- `:androidApp:connectedDebugAndroidTest` passed all 5 tests on Android API 36, covering
  the Compose gates/tab shell and the instrumented Keystore/profile adapters.
- The Android launcher now uses one generated authoritative brand bitmap behind an
  adaptive icon plus a dedicated monochrome themed-icon vector. Final lint runs with
  warnings as errors and reports no finding.
- Material 3 resolved to 1.4.0 and Navigation 3 to 1.1.4.

APK and mandatory emulator deployment:

- APK: `apps/mobile/androidApp/build/outputs/apk/debug/androidApp-debug.apk`
- Size: 23,122,763 bytes
- SHA-256: `E290340257350B056F65B69E8AC84DBD867FD23589F990216F6634B720C91E09`
- Package/version: `com.ermao.library`, version code 1, version name 0.1.0
- Deployment: replace-install and cold launch verified on `emulator-5554`, AVD
  `Shuku_API_36`; the app was foreground and the crash buffer was clean. The same
  deployment verification was rerun after connected device tests.

Real FastAPI base-path E2E:

- A disposable repository FastAPI instance was exposed through the unified gateway at
  the external app URL `http://10.0.2.2:18765/stage0`; no production server was used.
- The app completed `health -> compatibility -> setup/status`, preserved the deployment
  base path, and displayed the expected blocking Setup Required state for the
  uninitialized database.
- After initializing that disposable server, the app displayed Login, authenticated,
  performed the required `/api/auth/me` verification, and entered the four-tab shell.
- Home, Library, Shelves, and Me were each selected successfully and retained their
  stable tab identities.
- After `am force-stop`, a cold launch restored the profile and encrypted cookie,
  revalidated the session through `/api/auth/me`, and returned directly to Home. The
  crash buffer remained clean.
- A second disposable FastAPI instance used an untrusted, one-day self-signed certificate.
  System trust failed into the dedicated TLS risk gate; Back to editing preserved the
  draft; the destructive choice opened a platform-native confirmation dialog; accepting
  it reached Setup Required and survived a process restart for that profile.
- Starting a different server draft on the same host returned to system trust and failed
  into the TLS gate again, proving the accepted exception was not global. After the test,
  the disposable server/certificate were trashed and the dedicated AVD app data was
  cleared back to the no-profile Server gate.

Post-final static review:

- The shared `WorkSummary` wire/domain contract was compared directly with the backend
  `WorkSummary` schema and contains only `id`, `title`, `author`, `coverUrl`,
  `availableMediaKinds`, and validated `progress` (`0..100`). Reading-navigation fields
  remain on `ActiveMedia`, where the backend contract defines them.
- Redirect handling is bounded to HTTP 301, 302, 303, 307, and 308 and still applies the
  frozen origin, upgrade, downgrade, host, method, and maximum-hop rules.
- Legacy Expo, Turbo, Node modules, `package.json`, and the old application entry point
  are absent. Generated Gradle state and `local.properties` are ignored and are not part
  of the source change.
- Mobile source JSON, String Catalog, plist, privacy manifest, and asset metadata parse as
  UTF-8; the final source tree contains no unfinished-work markers, forbidden domain
  imports, or direct production logging calls. `git diff --check` passes.
- The shared contract changes are included in the successful final combined Gradle run.

iOS static gates:

- Xcode project, shared scheme, plist, privacy manifest, asset catalogs, source references,
  and build-phase paths were parsed successfully.
- English and Simplified Chinese catalogs contain the same 72 keys and matching
  placeholders.
- All 59 generated token symbols referenced by Swift exist.
- AppIcon and BrandMark match the authoritative 1024px Web brand PNG by SHA-256.
- No Swift compiler, Xcode build, XCTest, or Simulator result is claimed on this host.

## Remaining macOS gate

Run on macOS with JDK 17 and current Xcode:

```bash
cd apps/mobile
./gradlew verifyDesignTokens :shared:iosSimulatorArm64Test
cd ../..
xcodebuild \
  -project apps/mobile/iosApp/ErmaoLibrary.xcodeproj \
  -scheme ErmaoLibrary \
  -configuration Debug \
  -destination 'generic/platform=iOS Simulator' \
  CODE_SIGNING_ALLOWED=NO build
xcodebuild \
  -project apps/mobile/iosApp/ErmaoLibrary.xcodeproj \
  -scheme ErmaoLibrary \
  -configuration Debug \
  -destination 'platform=iOS Simulator,name=iPhone 16 Pro,OS=latest' \
  CODE_SIGNING_ALLOWED=NO test
```

Android Stage 0 is complete on the current host. Overall Stage 0 remains open only for
the macOS iOS build, XCTest, Simulator, and real test-server smoke gate above; no iOS
build or test pass is claimed from Windows/WSL.
