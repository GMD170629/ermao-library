# Reader Web mobile parity v1

## Locked outcome

- Web mobile Reader at a 411 x 914 logical viewport is the unique visual target for Android Reader-owned chrome.
- EPUB, comic, and PDF keep the same four primary actions in this order: 目录, 笔记, 外观, 设置.
- Opening a panel keeps the four-action navigation visible inside the same floating surface and hides the progress row.
- Panel heights are TOC 672, Notes 560, Appearance 576, and Settings 624 logical pixels/dp, capped by the available viewport above the top safe clearance.
- The panel uses a 76 logical pixel/dp navigation area, 16 logical pixel/dp content inset, and 26 logical pixel/dp outer radius.
- Setting order, grouping, values, visibility, enabled state, and localized availability explanation come only from the generated Reader settings catalog.
- EPUB navigation resolves EPUB 3 navigation first, EPUB 2 NCX second, and reading order only when neither produces usable entries.

## Must-match axes

- Block existence and order, first-screen fold, content density, surface geometry, typography roles, component proportions, selected and disabled states, and Reader-owned color/outline/shadow language.
- The open-panel shell, persistent bottom navigation, progress-row visibility, labels, close affordance, and content scrolling behavior.
- Directory hierarchy and navigation behavior for the same deterministic publication fixture.

## Platform-adapted differences

- Android status/navigation bars, gesture inset, font rasterization, and a minimum 48 dp semantic touch target around smaller visible controls.
- Back handling and accessibility focus use Android platform semantics while preserving the target visible composition.
- Reader settings remain capability-truthful: PDF swipe-page toggle and PDF/comic zoom stay disabled with the generated `notImplemented` explanation until their native controllers expose a safe runtime command. Their visual rows still follow the Web geometry and disabled-state opacity.

## Evidence matrix

- Primary: physical Android device 9e896bbc, zh-CN, warm theme, portrait, default display/font scale, EPUB fixture; controls, TOC, Notes, Appearance, and Settings.
- Flow: close button, outside tap, repeated action, Android back, panel scroll, directory jump, bookmark/annotation tab switch, and setting state persistence.
- Format: EPUB, comic, and PDF use the same shell and capability-truthful generated availability state.
- Risk after Primary passes: en-US, Night theme, long disabled explanation, large font, and TalkBack semantics.

## Baseline and target

- Accepted pre-change baseline: `artifacts/reader-ui-comparison/android/*.png`.
- Web target: `artifacts/reader-ui-comparison/web/*.png`; the empty TOC target must be replaced with a deterministic populated Web capture after the NCX/navigation repair.
- Existing visual runs are immutable and are not reinterpreted by this contract.
