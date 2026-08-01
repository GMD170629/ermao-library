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
