# Android Settings UI v1 — implementation report

## Outcome

The current Android settings surface now uses one Material 3 + WarmPage component family without a third-party UI library. The migration covers Me, profile, security, language, about, downloads, current administration routes, and reader settings. Retired mobile administration routes remain out of scope.

Business APIs, KMP contracts, routes, authorization rules, playback state, and persistence/save transaction semantics were not changed.

## Implemented contract

- Root settings uses a saveable, collapsible `LargeTopAppBar`; secondary pages use fixed compact bars.
- Bottom navigation and mini-player chrome render only on the Me root while audio state remains owned by the shell.
- Shared settings primitives own sections, navigation/value/switch/radio rows, inputs, tabs, filter bars, choice sheets, identity headers, content states, save actions, and danger actions.
- Current feature pages use the semantic Material Symbols Rounded registry instead of choosing Filled/Outlined navigation icons locally.
- Aggregate editors expose a localized text Save action; independent preferences remain immediate.
- Security and SMTP tabs are pinned; password fields provide localized visibility controls.
- Queue/users/log filters use a horizontally scrollable filter bar. Long/multi-option reader choices use a radio choice sheet.
- Fixed reader capabilities render as read-only current values with “fixed for this reader” copy; SDK/platform implementation details are absent.
- Segmented controls preserve equal height and complete labels at font scale 2.0.

## Verification

Passed:

- `verifyDesignTokens`
- `:shared:testAndroidHostTest`
- `:androidApp:testDebugUnitTest`
- `:androidApp:assembleDebug`
- `:androidApp:assembleDebugAndroidTest`
- settings-focused physical instrumentation: 31/31
- reader physical visual capture: 1/1, 16 screenshots
- preserved-data install via `adb install -r`
- cold launch on `9e896bbc`: 437 ms; no crash or ANR signature
- static current-route scan: no raw `ListItem`, `TopAppBar`, `FilterChip`, or Filled/Outlined icon imports in migrated feature screens

Device risk checks covered zh-CN/light/font-1.0, en-US/light/font-1.0, zh-CN/dark/font-1.3, en-US/dark/font-2.0, and an actual bound TalkBack service in zh-CN. Compose semantics tests additionally cover tab/radio/switch roles, selection state, disabled/loading state, password visibility descriptions, and choice-sheet behavior.

Repository-wide blockers retained honestly:

- `:androidApp:lintDebug` reports 36 pre-existing errors outside changed settings Kotlin files (Media3 opt-in, exported service, and one existing unused string). No baseline or rule weakening was introduced.
- The full connected suite previously passed 99/114; its 15 existing failures are in unrelated library, navigator, cover-menu, and legacy visual-fixture paths. The scoped settings suite is green.

## Evidence

- Target: `target-contract.md` and `target-blueprints.svg`
- Primary safe captures: `screenshots/primary/me-root.png`, `security-password.png`, `downloads.png`, `administration-root.png`, `opds.png`, `logs-top.png`, `log-capacity.png`, `language-final.png`, and `about.png`
- Risk captures: `screenshots/risk/zh-dark-font-1.3-security-password.png` and `en-dark-font-2.0-language-final.png`
- Reader captures: `screenshots/reader/reader-controls/` (comic, PDF, and EPUB)

Screenshots containing real account or server values are not part of the deliverable evidence set.
