# Work Detail visual target contract v3

Status: frozen before implementation after resolving the directional reference against the Phase 1–5 contracts; v3 incorporates the user's explicit instruction to restore and retain the reading decision block.

## Evidence contract

- Platform: Android physical device `9e896bbc` (`M2102K1AC`, Android 12 / API 31).
- Primary configuration: 1440 x 3200 px, 560 dpi, `fontScale=1.0`, zh-CN, light theme, portrait, complete product shell, deterministic EBOOK state with reading progress.
- Direction reference: `target/reference-direction.png`.
- The supplied design is directional, not a 1:1 pixel target. Android system chrome, native interaction behavior, real data, and existing product capabilities remain authoritative.

## Final visual effect

1. The first scan reads: work identity and progress, primary resume action, then supporting content.
2. The hero uses a compact two-column relationship: a 2:3 cover at roughly one third of the content width and a balanced identity/progress column. Long titles may wrap without making the hero dominate the first screen.
3. The complete reading decision block remains directly after the hero: reading progress when available, the secondary shelf action, and the filled primary reading action. The primary label remains truthful to state (`开始阅读` or `继续阅读`) and is never removed merely to imitate the reference. Resume/read is the only filled accent action; shelf is clearly secondary. Both remain complete, balanced, and reachable.
4. When a synopsis exists, the content area keeps the required top-level `简介 / 媒体版本` switch. When it does not, the switch disappears and media content begins directly. Multi-media work keeps the native-themed EBOOK / COMIC / AUDIOBOOK control.
5. Content uses the Warm Page continuous canvas, whitespace, alignment, and hairline dividers. Ordinary sections and rows do not become repeated raised cards, and decorative cards are never nested.
6. Volume presentation stays compact. Covers retain 2:3; a single volume never stretches into a half-screen tile. Selection, reading, and download states use one clear treatment each.
7. Multi-volume media uses the required three-column Compact grid. Single-volume EBOOK falls back directly to compact, scannable chapter rows and keeps existing navigation behavior.
8. The top app bar, bottom navigation, edge-to-edge insets, ripple, back behavior, and system bars remain Android-adapted.

## Must-match axes

- Required identity/status/action/content hierarchy, including conditional content and media controls.
- Presence and first-screen prominence of the reading progress, shelf action, and primary EBOOK reading action.
- First-fold density and hero/action proportions.
- Cover/title/progress/primary-action visual mass.
- Continuous flat surface language and stable page gutters.
- Compact volume sizing for both one-volume and multi-volume data.
- Typography hierarchy and action completeness at normal font size.
- Full product-shell navigation and system-area integrity.

## Platform-adapted and data-dependent

- Exact spacing, typography metrics, system chrome, and bottom-navigation treatment use the repository's Android Warm Page tokens.
- Ratings, accumulated reading-time summaries, and fields not present in the current model are not added. Existing supported metadata remains data-dependent.
- Synopsis, progress, volume count, media type, download state, and chapter count come from real or deterministic fixture data.

## Explicit exclusions

- No 1:1 pixel reproduction.
- No 200% font-scale acceptance in this pass.
- No dark-theme or en-US visual matrix before the normal-font Primary gate passes.
- No product-feature redesign, new metadata capability, golden promotion, or screenshot-infrastructure work.

## Candidate promotion rule

Compare every candidate with this target and the previous accepted physical-device baseline. Mark each must-match axis `better`, `same`, or `worse`. Promote only when every axis is non-worse and at least one highest-priority open difference is better. Reject any candidate with a worse axis; do not average regressions away.
