# Mobile Reader controls — 2026-08-27

## Scope and evidence policy

Android Compose and iOS SwiftUI share the KMP Reader control contract, not UI.
Original publication bytes, location JSON and server APIs are unchanged. No
Readium upgrade, private API, reflection, production script injection, content
rewriting or derived EPUB cache is introduced.

An enabled control requires a native implementation. A preferences-object
assertion alone is not rendering evidence. Unsupported controls remain disabled;
controls for other morphologies are omitted. Implementation is present, but acceptance is **not complete**. The final iOS
native-layout fix was built after the physical device disconnected and has not
been run. Earlier passing results must not be attributed to that final revision.

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
| Font family | `Configuration.addFontFamilyDeclaration`, `EpubPreferences.fontFamily` | `fontFamilyDeclarations`, `EPUBPreferences.fontFamily` | Licensed Sans/Songti/Kaiti assets; three sans labels map to the same licensed font. iPhone all three font families loaded in the earlier render run, verified using `document.fonts` and computed paragraph font. Android render assertion added, device pending. |
| Font size / weight | `fontSize`, `fontWeight` | `fontSize`, `fontWeight` | Reflowable publication; font size uses a 16px CSS root on both platforms. iPhone 24px paragraph size verified. |
| Line height, positive letter spacing, margins, paragraph indentation/spacing, alignment | public preferences and `createPreferencesEditor` | public preferences and `editor(of:)` | Editor effectiveness checks language, writing direction and layout. Publisher-style conflicts disabled; values retained. iPhone line-height ratio verified. |
| Paged / scroll / columns | `scroll`, `columnCount` | `scroll`, `columnCount` | Columns disabled while scrolling; chosen paginated columns retained. Vertical-text restrictions come from the editor. The dynamic iPhone scroll assertion found stale native resource caching. The public-constructor fix below is awaiting physical-device verification. |
| Five themes / system theme | public colors/theme and native Compose chrome | public colors/theme and SwiftUI chrome | All five paragraph foreground colors passed in the earlier physical render run; final native remount path needs revalidation. System mode resolves Day/Night; choosing a theme exits system mode. |
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

## Pinned Swift SDK cache and native adapter ownership

The pinned Swift SDK's internal `WebViewServer` buffers already decorated HTML.
A `scroll` change invalidates pagination without committing CSS to the old view,
and the reload can read that earlier buffered document. Physical tests observed
`settings.scroll == true` while the live document still had
`--USER__view: readium-paged-on` and horizontal overflow. Foreground-state checks
ruled out deferred background layout.

The iOS Reader adapter now creates a fresh **public**
`EPUBNavigatorViewController` with the same live `Publication`, the new
`EPUBPreferences`, the same registered fonts and a captured public exact Locator.
The SwiftUI host is keyed to navigator identity. It verifies the recaptured block
before saving settings; failure restores the prior live navigator and settings.
System appearance updates and user updates share a serial queue. No publication
copy, conversion, script injection, SDK patch or private cache access is used.

Owner: Mobile Reader native adapter (`makeIosReflowableNavigator` and
`executeControlPreferences`). Removal condition: a separately authorized pinned
SDK update fixes resource invalidation, and the existing physical render test
passes through public `submitPreferences`, including mode changes, rotation,
resource revisits and semantic-location preservation. Until then, recreation is
the single application path for native text preference changes. This path is
**compiled but not runtime accepted** because the phone disconnected before the
next test run could launch.

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

- In a future authorized device run, reconnect the physical iPhone and rerun the final native render test, the nine
  format UI matrix, theme/system changes, native remount/rollback and semantic
  position preservation. The new scroll assertion must pass; it is not skipped.
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
