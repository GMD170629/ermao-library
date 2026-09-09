# Mobile operation feedback

## Contract

Operation completion feedback is native-themed (B): Android renders a rounded
floating Snackbar, and iOS renders an intrinsic-width capsule using Warm Page
colors. Plain success has a status icon and localized result text, without a Close
button or modal scrim. Its full-opacity dwell is **1,000 ms**, followed by the
platform fade-out. Platform accessibility accommodations may extend that dwell.

`shared/core/feedback/OperationFeedbackPolicy.kt` owns success duration and
replacement precedence. The four semantic kinds are Success, PartialSuccess,
Failure and Action. Localized text never selects a kind. Action-bearing feedback
retains its operation window; failures and partial outcomes retain their existing
timeout or explicit dismissal. Plain success never replaces an outcome needing
attention. A suppressed success is consumed rather than replayed later.

Each presentation gets a unique event identity, including repeated identical
messages. Replacement cancels the preceding timer. Expiration and consumption
must target that identity, not whichever result happens to be current. Feedback
has no persistence and is cleared when its owning surface/session ends.

## Reused owners and migrated callers

- Android: `WarmPageSnackbars.kt` extends the existing native feedback host;
  `SnackbarHostState` still owns suspension, cancellation and action results.
  The shell hosts its feedback inside navigation content bounds, above bottom
  navigation and the audio accessory. Reader and modal surfaces retain their
  own correctly positioned hosts using the same implementation.
- iOS: `Design/OperationFeedback.swift` extracts the existing Work Detail capsule
  into a shared presenter and overlay. Shell feedback is positioned above its
  bottom controls; modal results use the same component in their own surface.
- Migrated surfaces include book management, Work Detail, shelf-save feedback,
  successful download-management outcomes, and administrative operation results.
  Reader action/Undo and failure feedback retains its recovery behavior. Existing
  inline partial/error summaries and diagnostic results remain persistent.
- `BookManagementSession` remains the owner of mutation outcomes. Its notice
  revision and semantic kind let native adapters consume a specific result
  without erasing a newer result or an unrelated failure. Closing a metadata
  result sheet transfers its pending notice to the underlying surface.
- Removed Android's standalone management Snackbar with its mandatory Close
  button, iOS's standalone saved/Close overlay, and Work Detail's private capsule
  and timer. Neither platform duplicates network or mutation operations.

Download acceptance remains “added/queued”; it does not claim transfer completion.
No backend, wire contract, reader safety rule or generated binding is edited.
Existing Chinese and English localized result strings are reused.

## Verification (2026-09-09)

- Shared Android-host test suite: 451 tests, zero failures/errors/skips, including
  feedback precedence, one-second policy, repeated operations and stale
  consumption. Original mutation ordering and failure-path tests remain enabled.
- Android main compilation, instrumentation-test compilation and strict
  `lintDebug` pass. Instrumentation tests cover a full visible second, repeated
  identical success, and preserving a pending Undo operation.
- Android runtime/visual/accessibility evidence is pending: this workstation has
  no connected ADB device and no installed Android emulator. The full Android
  unit-test task is blocked by the existing chapterCore host JNI prerequisite,
  which requires an x86_64 host instead of this arm64 Mac. No gate was weakened.
- iOS signed `iphoneos` Debug application build passes. The new feedback test
  source compiles, but the full test-target build is blocked by existing Reader
  fixture/API mismatches (ContentStore's missing navigationKey, MOBI fixture
  argument order, ReaderSecurity's fileprivate helper access, and a ReaderSafety
  Int/Int32 mismatch). No Reader fixture changes, skips or relaxed settings are
  included in this feedback change. The app build reports pre-existing LoginView
  deprecation warnings and the toolchain's AppIntents metadata notice, not new
  feedback-source warnings.
- iOS physical installation and launch have succeeded on the connected iPhone
  17 Pro Max. Visual and accessibility interaction coverage remains pending.

## iOS feedback localization regression

- Dynamic management notice keys now resolve as complete runtime strings, instead
  of localization interpolation templates. Work Detail and download result copy
  explicitly use the active SwiftUI locale.
- `Design/LocalizedCopy.swift` owns language-bundle lookup, extracted unchanged
  from the Reader option helper. Reader controls and their existing localization
  tests now use this same owner; no translation dictionary is duplicated.
- Added regression coverage for all six management notices and explicit Chinese /
  English selection. A standalone Foundation executable using the production
  helper verified all 40 feedback translations against the compiled app bundles.
- The signed iOS application rebuild passed using the previously verified,
  unchanged KMP framework. A full dependency-resolution attempt timed out at
  Google's Maven repository; offline resolution lacked dependencies. The temporary
  local framework-reuse build step was restored to the original Gradle command.
  Existing Reader test-target blockers listed above remain unchanged.


Device acceptance must include save, mark-read, shelf save, download acceptance,
sheet dismissal, return navigation, rapid repeated actions, protected error/Undo
feedback, keyboard/audio obstruction, large text, and VoiceOver/TalkBack in both
Chinese and English.
