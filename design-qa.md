# Design QA

## Target

- Parent reference: `codex-clipboard-adb36960-cd80-44c3-b676-f9208a56e30c.png` (`/library`).
- Detail reference: `codex-clipboard-8a103780-a054-46d1-a87a-b5ec99d3a3d6.png` (`/works/:id`).
- Restored action-menu reference: `codex-clipboard-d2c164a0-be35-4db3-bb64-2799c26d7fba.png`.
- Implementation capture: `book-detail-global-frame-and-actions.png`.

## Visual comparison

- The application shell now owns one centered 1280px content frame through the global `--shuku-content-max-width` token. Library and work-detail pages no longer declare competing page widths.
- At the same 2560px browser viewport, automated measurements for both `/library` and the opened work detail are identical: left `764.33`, right `2044.33`, width `1280`.
- A stable root scrollbar gutter prevents the centered frame from shifting when moving between a long list and a shorter detail state.
- The restored action menu matches the former visual hierarchy: 288px white surface, rounded coners, shadow, icon-led rows, and a separator before the destructive action.
- The earlier restored hero, reading controls, media tabs, volume wall, content-structure view, and single-volume chapter-detail view remain intact inside the shared frame.

## Interaction comparison

- The overflow menu exposes `编辑信息`, `元数据识别`, `上传自定义封面`, `重新生成封面`, `下载当前版本`, `发送到 Kindle`, and `删除记录`.
- `从书库隐藏` is deliberately absent, as requested.
- Menu dismissal works through outside click and Escape. Destructive editing/cover/delete actions remain manager-only; available reading actions remain available to members.
- Deleting the library record preserves the source file, matching the requested removal of the hide workflow without broadening deletion behavior.

## Verification

- Authenticated Chrome visual and DOM verification: passed.
- Global frame boundary comparison between parent and detail: passed.
- Focused ESLint: passed.
- TypeScript typecheck: passed.
- i18n parity for `zh-CN` and `en-US`: passed with 2715 messages.
- Full Web test suite: passed, 239 tests.

## Compact action-menu follow-up

- Comparison reference: `codex-clipboard-e3736ebc-c671-4da6-9425-d2aa26759b41.png`.
- Previous oversized state: `codex-clipboard-7e9a06a3-147f-4d45-8eba-caa1cd18d159.png`.
- Implementation capture: `book-detail-compact-actions-menu.png`.
- At the same 2560 x 1296 viewport and 1.5 device-pixel ratio, the menu now measures 240 CSS px / 360 physical px wide, matching the approximately 360px reference width.
- Each action row measures 40 CSS px. With the requested seven actions and no library-hide action, the menu is 310.33 CSS px tall and keeps the reference density and separation.
- Labels, action order, outside-click dismissal, Escape dismissal, focus styling, and manager permissions remain unchanged.
- Focused ESLint, TypeScript typecheck, bilingual i18n validation (2715 messages), and all 239 Web tests passed.

final result: passed

## Setup language-switcher follow-up

- Source visual truth: `codex-clipboard-93acc614-7683-46c5-9f93-7ac92f3b60dc.png` (1980 x 1231 px, setup completion state, language menu open).
- Implementation capture: `artifacts/language-switcher-setup.png` (1980 x 1231 px, setup status-check state, language menu open); combined comparison: `artifacts/language-switcher-comparison.png`.
- The surrounding setup stage differs because browser verification used a local status-check fixture, but the focused language-control region uses the same viewport, placement, locale, and open interaction state.
- Fonts and copy: existing compact labels, icon, weights, and Chinese/English option text are unchanged; both locale transitions were exercised successfully.
- Spacing and layout: the 144px menu is right-aligned to the trigger, uses consistent 16px rounding and 8px internal padding, and remains clear of the right setup panel.
- Colors and tokens: trigger and menu both compute to `rgb(232, 220, 199)`; the menu border is `rgba(176, 139, 110, 0.45)`, while the selected option uses the setup orange at 15% opacity with dark orange text. The former white floating surface is removed.
- Assets: the existing Lucide language, chevron, and check icons remain sharp and consistent with the rest of the setup controls; no new raster assets were needed.
- Interaction and accessibility: listbox semantics, current-language check, right alignment, pointer selection, keyboard behavior, focus restoration, and Chinese/English switching remain intact.
- TypeScript typecheck, ESLint, i18n validation (2726 messages), and all 248 Web tests passed.

final result: passed

## Monitor-folder tree follow-up

- References: `codex-clipboard-8eb96d0a-0473-407d-865e-87ae81278436.png`, `codex-clipboard-bbd7276f-089e-4283-ac34-7b45ea564389.png`, and `codex-clipboard-b7d83d56-49b2-4626-937d-6b3bf13241b0.png`.
- Implementation capture: `artifacts/monitor-folder-tree-setup.png`; side-by-side comparison: `artifacts/monitor-folder-tree-comparison.png`.
- The editable combobox, directory panel, borders, focus color, surface color, and helper copy now use the initialization page's warm beige, olive, and orange visual system.
- The setup variant participates in normal document layout, so its expanded panel remains inside the rounded setup card instead of being clipped by the card boundary.
- The directory viewport measures 256px tall and remains scrollable. Its computed scrollbar color is `rgb(139, 157, 131)` on a transparent track; the selected node and panel remain inside the 1152px reference viewport.
- A restored or typed absolute path keeps `/` as the visible tree root, loads every ancestor in order, expands the selected directory, and exposes its children. The verified path `/home/liumianti/books` rendered `/ > home > liumianti > books`, with `books` selected and expanded.
- The input accepts typing and paste; the backend remains authoritative for absolute, existing, readable directory validation at save time.
- TypeScript typecheck, ESLint, bilingual i18n validation (2726 messages), and all 248 Web tests passed.

final result: passed
