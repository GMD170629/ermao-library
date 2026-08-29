# Mobile Reader controls — 2026-08-27

> The 2026-08-28 user decision supersedes this record's fresh-Navigator workaround:
> iOS settings now use the existing Navigator's public `submitPreferences` API.
> Readium owns reflow and location retention; the application does not verify or
> roll back the resulting layout. The earlier results below are historical
> evidence, not acceptance of the current submission path. See
> [the current Reader architecture](../mobile-reader-architecture.md#13-unified-reader-settings-2026-08-28)
> and [the unified settings implementation and verification](reader-settings-unification-2026-08-28.md).

## Scope and evidence policy

Android Compose and iOS SwiftUI share the KMP Reader control contract, not UI.
Original publication bytes, location JSON and server APIs are unchanged. No
Readium upgrade, private API, reflection, production script injection, content
rewriting or derived EPUB cache is introduced.

An enabled control requires a native implementation. A preferences-object
assertion alone is not rendering evidence. Unsupported controls remain disabled;
controls for other morphologies are omitted. At the time of this record,
acceptance was **not complete**: the final iOS remount workaround was built after
the physical device disconnected and was not run. That workaround has since been
removed. Earlier passing results must not be attributed to another revision.

### Delivery decision

The user subsequently requested no further physical-device builds and asked to
commit and push all local updates. This delivery therefore stops device work;
the runtime gaps below remain recorded, without claiming that they passed.
Existing test cases and quality-gate configuration are unchanged.

Before repository synchronization, full local host checks passed: 282 shared
tests, 143 Android app JVM tests, design-token verification, and 5 Python FB2
contract tests. The changed Python test also passed Ruff lint and format checks.
The Python run emitted an existing Starlette/httpx deprecation warning.
Web i18n and Android lint retain the blockers recorded below.

## Control / API / effectiveness / evidence

| Control | Android 3.3.0 public API | iOS pinned public API | Conditions and verification |
| --- | --- | --- | --- |
| Font family | `Configuration.addFontFamilyDeclaration`, `EpubPreferences.fontFamily` | `fontFamilyDeclarations`, `EPUBPreferences.fontFamily` | The catalog exposes exactly PingFang/Songti/Kaiti, backed by licensed Sans/Serif/Kaiti assets. iPhone all three font families loaded in the earlier render run. Android all three now load on the physical Chromium 95 WebView through static compatibility WOFF2 assets, verified using `document.fonts` and computed paragraph font. |
| Font size / weight | `fontSize`, `fontWeight` | `fontSize`, `fontWeight` | Reflowable publication; font size uses a 16px CSS root on both platforms. iPhone 24px paragraph size verified. |
| Line height, positive letter spacing, margins, paragraph indentation/spacing, alignment | public preferences and `createPreferencesEditor` | public preferences and `editor(of:)` | Editor effectiveness checks language, writing direction and layout. Publisher-style conflicts disabled; values retained. iPhone line-height ratio verified. |
| Paged / scroll / columns | `scroll`, `columnCount` | `scroll`, `columnCount` | Columns disabled while scrolling; chosen paginated columns retained. Vertical-text restrictions come from the editor. The dynamic iPhone scroll assertion found stale native resource caching; the current direct-submit result is recorded in the 2026-08-28 verification. |
| Five themes / system theme | public colors/theme and native Compose chrome | public colors/theme and SwiftUI chrome | All five paragraph foreground colors passed in the earlier physical render run. System mode resolves Day/Night; choosing a theme exits system mode. Current direct-submit evidence is recorded separately. |
| Publisher styles | `publisherStyles` | `publisherStyles` | One overall native switch; no independent style/color/font implementation. |
| Command animation | `goForward/goBackward/go(animated:)` | `NavigatorGoOptions` | Buttons, tap zones and keyboard commands only; reduced motion respected. Does not control native swipe animation. |
| Contents / progress / bookmarks | public navigation and positions, existing bookmark store | public navigation and positions, existing bookmark store | TOC adapters verify target; bookmark sheets retain failure state. Existing account-scoped bookmark sync retained. |
| Progress label / clock / keep-awake | native common shell / window flags | native common shell / idle timer | Shared settings, applied to all morphologies. |
| Tap zones / keyboard / Android volume keys | Activity and Readium unhandled input | native navigator input | Sheet/input focus guards; Readium handles links/selection before reflowable taps. iOS volume keys stay disabled. |
| Reset | shared `resetReaderPreferences` | matching scoped reset / serial writer | Shared values plus current morphology only; other morphology values preserved. Unit tests verify. |
| Comic/PDF layouts | only previously implemented PDF fit remains enabled | existing PDF toolbar zoom remains; preference-only layout controls disabled | No new fixed-layout engine behavior. |
| Unsupported | disabled shared control states | disabled shared control states | Negative spacing, max page width, smart/dedup/automatic indentation, independent publisher parts, swipe/gesture toggles, iOS volume keys, annotations. |

## Rendering bug found by this work

Readium Swift sets preferences as HTML CSS custom properties, and loads its own
post-publication stylesheet and fonts from `readium://assets`. The previous CSP
allowed only the publication origin, so the settings objects changed while
paragraphs retained the default font, 16px size, line height and color. The CSP
now allows **only `readium://assets` for styles and fonts**, while keeping
`script-src 'none'`, `connect-src 'none'`, frame/object/form restrictions and
unchanged author body projection. The physical-device rendering test failed
before the fix and passed afterwards. No script permission was added.

## Historical pinned Swift SDK cache investigation

The pinned Swift SDK's internal `WebViewServer` buffers already decorated HTML.
A `scroll` change invalidates pagination without committing CSS to the old view,
and the reload can read that earlier buffered document. Physical tests observed
`settings.scroll == true` while the live document still had
`--USER__view: readium-paged-on` and horizontal overflow. Foreground-state checks
ruled out deferred background layout.

The earlier adapter attempted to work around this by recreating the Navigator
and requiring the first visible block to remain identical. That path was only
compiled, not runtime accepted. It could reject valid repagination and is now
removed together with its locator checks, polling, renderer rollback, extra queue
and identity-based SwiftUI remount. The user's 2026-08-28 instruction requires
direct public `submitPreferences` on the existing Navigator. The SDK owns layout;
the app retains its preference store and progress-observation suppression. The
historical scrolling cache failure remains a separate SDK rendering finding and
does not justify restoring the removed workaround.

## Checks run

| Check | Result |
| --- | --- |
| Shared Reader host tests | **94 passed**, zero failures/skips |
| Android Reader JVM tests | **29 passed**, zero failures/skips |
| Android main and instrumentation Kotlin compilation | Passed; no APK runtime acceptance |
| Design tokens | `verifyDesignTokens` passed |
| Final iOS source | Signed Debug `iphoneos` build passed; no Simulator or signing bypass |
| iOS Reader localization | 164 keys contain both `en` and `zh-Hans`; Android has matching 150 Reader keys in English/Chinese |
| Earlier physical XCTest | 37 selected cases passed after the CSP fix; subsequent expanded run passed 36 and failed the new scroll render assertion, leading to the cache fix above |
| Web `pnpm i18n:check` | Failed: existing administrator-message catalog drift, 4 missing and 6 stale keys per catalog; no placeholder mismatches |
| Android `lintDebug` | Failed: existing errors outside Reader, 2 platform ExifInterface uses and 2 unused work-management resources |

The signed physical target used was `00008150-0011112211A0C01C`, iPhone 17 Pro
Max (user device name `Xiaomi 17 Pro Max`). Connection, pairing, Developer Mode
and unlocked state were checked before test runs. At 18:25 the device became
unavailable; the pending run was stopped. A subsequent signed device-target
build is compile evidence only. No emulator or Simulator was used.

### Earlier physical UI matrix

| Original format | Shared appearance/settings, navigation controls, close/reopen |
| --- | --- |
| EPUB | Passed |
| MOBI | Passed |
| AZW | Passed on retry after fixing a notification-banner test race |
| AZW3 | Passed |
| PRC | Passed |
| TXT | Passed |
| FB2 | Passed |
| PDF | Passed, including center-tap visibility regression |
| CBZ | Passed |

These runs used actual authenticated server resources and the common native
sheets. They verify the listed flows, **not every control or exact bookmark/TOC
arrival for every format**. They predate the final native remount/arrival-check
changes and need rerunning on the final build. Early failures exposed hidden
control accessibility and slider grouping issues, which were fixed. Transient
notification banners also affected tests; no notification settings were changed.

## Deferred runtime acceptance and explicit exclusions

- In a future authorized device run, reconnect the physical iPhone and rerun the native render test through the
  current public settings submission path, the nine-format UI matrix, themes,
  system changes and preference persistence. The scroll rendering assertion
  remains an independent SDK check; it is not skipped or replaced by an app reflow workaround.
- No physical Android device was available. All Android rendering/instrumentation,
  fonts, hardware keys, system Back, TalkBack, rotation and lifecycle gates remain
  pending. Compilation is not a substitute.
- Complete per-format TOC/progress/bookmark arrival checks, publisher-style
  conflicts, every typography control, disabled controls without writes, long
  chapters, illustrations/footnotes and reopen persistence on both platforms.
- Complete both-language UI, VoiceOver/TalkBack, large text, hardware keyboard,
  rotation/split-screen, background and process-death recovery evidence.
- Resolve the existing Web i18n and Android lint blockers in their owning
  capabilities. No test skip, lint baseline, suppression or lowered gate was added.
- Annotations and the explicitly excluded custom controls remain disabled.
  Download-entry synchronization and progress-store fallback debt are unchanged.

## Local evidence logs

`/tmp/reader-controls-android-final.log`, `/tmp/reader-controls-ios-render.log`,
`/tmp/reader-controls-ios-final.log`, `/tmp/reader-controls-ios-retry.log`,
`/tmp/reader-controls-ios-layout.log`,
`/tmp/reader-controls-ios-native-factory.log` (interrupted before launch),
`/tmp/reader-controls-ios-device-build.log`,
`/tmp/reader-controls-web-i18n-final.log`.

## 2026-08-28 follow-up: Web i18n and Android lint

This follow-up closes the catalog and lint blockers only. It does not change the
Reader/Shelves flows, public API contracts, dependency versions, or the pending
physical-device acceptance above. The earlier failed runs remain historical evidence.

### Root causes and bounded fixes

- Commit `9fcadcda` already supplied the four administrator audit-event translations,
  switched cover selection to AndroidX ExifInterface, and removed the two unused
  resources in both Android locales. Those four historical lint errors no longer
  reproduce.
- The six administrator errors reported as stale were still user-visible:
  `UserAdministrationError(code, message)` flows through `CodedMessageBody` to
  the Web page's `t(reason.message)`. The Python collector did not recognize that
  constructor, so deleting those entries made the check pass while English error
  toasts retained Chinese text. The existing collector now reads its `message`
  keyword or second positional argument through the existing argument/static-text
  helpers. Both catalogs restore the six entries and their previous English
  translations; the four audit-event translations remain intact.
- Current Android lint reproduced one `LogNotTimber` error in the download task
  failure boundary. That call now uses the existing project logging approach,
  `java.util.logging.Logger`, retaining the `Downloads` logger name and
  `download_task_failed` event, resource ID, and error code. Cancellation,
  failure-state updates, and recovery behavior are unchanged. No second logger
  implementation, logging dependency, suppression, or lint baseline was added.
- Local Web dependencies predated the committed PDF.js patch, causing two missing
  `setReadingWindow` type errors and one PDF integration-test failure. Running
  `pnpm install --frozen-lockfile` with Node `22.23.1` and pnpm `9.12.2` applied the
  existing dependency patches; neither the lockfile nor Reader code was changed.

### Verification

The added extraction and translation assertions failed before the fix. After the
fix, all eight focused i18n tests pass, including positional/keyword arguments,
interpolation, exclusion of internal/dynamic-only messages, and both locales for
the six errors and four audit events.

| Gate | Result |
| --- | --- |
| Web `pnpm lint` / `pnpm typecheck` | Passed |
| Web `pnpm test` | 400 passed, zero failures/skips |
| Web `pnpm i18n:check` | 2053 messages; no missing/stale keys, untranslated English, or placeholder mismatches |
| `verifyMobileOfflineContract` / `verifyDesignTokens` | Passed |
| `:shared:testAndroidHostTest` | 322 passed in the baseline run; unchanged shared sources were up-to-date in the final run |
| `:androidApp:testDebugUnitTest` | 146 passed after the logging change, zero failures/errors/skips |
| `:androidApp:lintDebug` | Passed; report: `No issues found.` |
| `git diff --check` | Passed |

Android tasks ran in one invocation with JDK 17, the configured local Android SDK,
and `--no-parallel --console=plain`; no competing Gradle invocation was started.
Local logs: `/tmp/ermao-i18n-lint-install.log`,
`/tmp/ermao-i18n-lint-web-lint.log`, `/tmp/ermao-i18n-lint-web-typecheck.log`,
`/tmp/ermao-i18n-lint-web-test.log`, and `/tmp/ermao-i18n-lint-android-gates.log`.
The Android report is `apps/mobile/androidApp/build/reports/lint-results-debug.txt`.

### Still unverified

- `adb devices -l` returned no devices. No APK installation, cold launch, physical
  download-failure logging/recovery, bilingual UI, TalkBack, or lifecycle test was
  performed. No emulator was started; the earlier Reader/Shelves device matrix
  remains pending. This follow-up did not run iOS or Web browser UI acceptance.
- The initial diagnostic Gradle run emitted an SDK XML v3/v4 compatibility warning.
  It did not recur in the final incremental gate log, but no SDK tooling change was
  made, so this is not evidence of a clean-environment tooling repair.

Follow-up result: catalog and lint blockers resolved; runtime acceptance remains pending.
