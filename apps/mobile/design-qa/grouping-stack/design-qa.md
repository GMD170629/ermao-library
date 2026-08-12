# Grouping Cover Stack Design QA

## Evidence

- Source visual truth: `/Users/guyu/.codex/generated_images/019ff3af-0436-7753-a176-58273c6adae4/exec-9495b010-9ca9-4e61-ae62-bca20eb99dfb.png`
- Implementation screenshot: `/Users/guyu/www/shuku-starship/apps/mobile/design-qa/grouping-stack/ios-authors-option2-stack-physical.png`
- Device/state: physical iPhone `00008150-0011112211A0C01C`, compact portrait, light theme, zh-Hans, Authors scope, fixture rows with one/two/three representative works.
- Source pixels: 853 × 1844. Implementation capture: 354 × 781. The source was treated as composition evidence rather than a pixel-token source; both were inspected at fitted full-screen scale because the generated concept does not use the physical device's exact viewport or system chrome.
- Focused region: Authors result rows. This is the only modified visual surface.

## Full-view comparison

The implementation retains the selected option 2 hierarchy: compact native Library shell, stable row text column, fixed cover slot, restrained dividers, and a trailing system chevron. One-cover rows no longer reserve the former three-cover side-by-side width. Two- and three-cover rows use the requested Dune-style overlap.

## Required fidelity surfaces

- Typography: native app typography and existing Warm Page headline/callout hierarchy are preserved. Author names remain primary and work counts secondary; author names are no longer duplicated in their own summary.
- Spacing/layout: cover slot is fixed at 112 pt on iOS (104 dp Android); one/two/three cover counts do not move the text column. Row height remains consistent and touchable.
- Colors/tokens: existing semantic canvas, primary/secondary text, divider, accent-soft placeholder, and cover shadow tokens are unchanged.
- Image quality: real authenticated cover assets continue through the existing cover loader. The fixture intentionally displays native placeholders because it has no cover URLs; no raster placeholder was introduced.
- Copy/content: Authors show only the localized work count. Series retain the representative author plus localized work count. zh-Hans and English Android strings are complete; iOS reuses existing localized keys.

## Comparison history

1. Initial implementation used repeated fixture work IDs, causing SwiftUI to collapse the apparent third stacked item. The fixture was corrected to three stable unique work identities.
2. Post-fix physical-device evidence shows distinct one-, two-, and three-cover stacks, a stable text baseline, and no large unused cover region.

## Findings

- No actionable P0/P1/P2 visual differences remain for the selected hybrid direction.
- P3: final perceived overlap can be revisited with production covers after more three-work author groups exist; current overlap deliberately preserves enough of each cover to remain recognizable.

## Verification notes

- Physical-device signed build, installation, and fixture launch succeeded.
- The automated XCUITest runner did not initialize because Apple device authentication timed out; this occurred before test execution. The rendered physical-device state was inspected through iPhone Mirroring instead.
- Android runtime execution was not required by the product owner; Android source/resource parity was checked statically.

final result: passed
