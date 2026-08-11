# ADR 0006: Native mobile shell with shared Kotlin contracts

- Status: Accepted
- Date: 2026-08-11

## Context

The previous `apps/mobile` contents were untracked Expo/React Native generated artifacts
without an iOS application or reusable business implementation. The mobile product
baseline requires native platform navigation and controls, four independently restored
top-level destinations, server-profile isolation, cookie sessions, explicit TLS risk
handling, and a shared interpretation of the backend contracts.

Sharing all UI would weaken the platform behavior required by the mobile visual and
navigation specifications. Splitting every capability into a separate Kotlin module at
the bootstrap stage would instead add framework export and Swift interop complexity before
those capabilities have independent build or lifecycle needs.

## Decision

The mobile application is rebuilt from scratch with two Gradle modules:

- `:shared` is the single Kotlin Multiplatform library and exports the stable
  `ErmaoShared` Objective-C-compatible framework.
- `:androidApp` is the native Jetpack Compose application.
- `iosApp` is a native SwiftUI Xcode project and is not a Gradle module.

Kotlin shares domain values, wire DTO mapping, API and cookie behavior, session state,
validated navigation intents, and public runtime commands. SwiftUI and Compose own view
state, accessibility, platform navigation stacks, system dialogs, and adaptive layout.
Each Home, Library, Shelves, and Me destination owns a persistent native stack. Reader and
Now Playing remain future root-level presentation slots rather than tab-owned routes.

Capability-first packages inside `:shared` preserve the dependency direction
`presentation -> public facade -> application -> domain`; infrastructure implements only
application ports and domain contracts. A capability becomes a separate Gradle module
only after it has a real lifecycle, build-isolation, or independent-consumer need.

The server profile stores the canonical external application URL, including an optional
base path and excluding `/api`. A public compatibility handshake supplies the stable
server identity and protocol contract. Private persistence uses the namespace
`serverIdentity + userId + authzVersion`.

Profiles and non-secret restoration metadata use ordinary platform persistence. Session
cookies remain in a profile-isolated Ktor cookie store backed by Android Keystore/AES-GCM
or iOS Keychain (`AfterFirstUnlockThisDeviceOnly`). Passwords and cookies never enter
application session snapshots or ordinary key-value storage. System TLS trust is the
default; bypass is an explicit per-profile mode reached only through the native risk
confirmation flow.

`design/tokens.json` is the sole numeric design-token source. Gradle validates it and
generates Kotlin, Swift, and Android resource outputs at build time. Generated outputs are
not committed and Mobile does not introduce a Node package or join pnpm/Turbo.

iOS integrates the shared framework through the Kotlin direct-integration Xcode build
phase. CocoaPods and experimental Swift Export are not part of the bootstrap architecture.

## Consequences

- Android and iOS can evolve native UI independently while sharing one interpretation of
  authentication, authorization, server compatibility, and library domain contracts.
- Adding a Kotlin sealed state or navigation intent requires fail-safe handling in both
  platform adapters before release.
- Cookie/TLS clients are profile scoped; no global certificate bypass or cross-profile
  cache is permitted.
- The Stage 0 Android gate can be closed on the current development environment after
  emulator and real test-server verification. The iOS gate remains open until the same
  source revision passes KMP iOS tests and Xcode build/test on macOS.
