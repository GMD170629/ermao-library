# Mobile Work Detail Continuous Layout and Selected-Volume Contract

## Status and authority

Status: adopted Work Detail design contract, revision v6.1, 2026-08-16.

This document freezes the selected continuous Work Detail layout and interaction behavior. Phase 1 remains authoritative for capability, API, authorization, Reader, download, and media truth; Phase 2 remains authoritative for navigation and overlay ownership; Phase 3 remains authoritative for task order; Phase 4 remains authoritative for visual tokens. This document and the v6 board below own the Work Detail composition and selected-volume behavior.

![Work Detail selected-volume metadata Light/Dark v6](assets/mobile-app-hifi-v1/work-detail-selected-volume-metadata-light-dark-v6.png)

Work Detail v2–v5 images have been deleted. The v6 board is the only retained visual reference and the only permitted visual-regression baseline.

## Locked composition

Compact Work Detail is one continuous scroll in this order:

1. system back and collapsible title semantics, with no top-right overflow;
2. one centered 2:3 work cover, with no carousel and no pagination dots;
3. title, one centered `author / series / selected media kind` line, and filled-background tags;
4. one dynamic primary action;
5. the secondary actions `下载 / 阅读状态 / 加入 / 更多`;
6. an optional expandable plain-text description with a centered chevron control;
7. a `Media types` heading on the left and the real Ebook/Comic/Audiobook choices on the right, including the single-media state;
8. a horizontally scrolling, paginated volume rail;
9. metadata for the currently selected volume;
10. normal AuthenticatedShell navigation.

Work Detail shows the four app destinations. Only Reader and Now Playing use their established immersive navigation rules.

## Actions and authorization

- `加入` replaces the old inline edit position and opens the existing shelf picker. It is not an administrative mutation.
- The primary action derives from selected media, selected volume, readability, progress, and download state. It may be Start/Continue Reading, Download to Read, Start/Continue Listening, or unavailable with a truthful reason.
- E-book, comic, and audiobook controls are shown only when the work actually has those media kinds. When present, audiobook is a normal selectable media kind rather than a disabled visual placeholder.
- Each visible media choice keeps one fixed 80 dp/pt segment. One available kind occupies one segment, two kinds occupy two segments, and three kinds occupy three segments; visible choices never stretch to fill missing kinds, and unavailable kinds do not render placeholder or disabled segments.
- Work Detail does not render a chapter, track, or page directory below metadata. Reader and Now Playing retain ownership of their directory/navigation surfaces.
- `更多` below the primary reading action opens the contextual Book control menu defined by `mobile-app-work-detail-management.md`; the top bar has no management entry.
- Long-pressing a volume cover opens the contextual Volume control menu for that exact volume. No persistent volume-edit button is rendered, and the title remains presentational.
- Long press is not the sole accessible route: VoiceOver/TalkBack expose a localized `Volume actions` custom action on the cover, and keyboard/switch-control activation provides an equivalent action.
- Normal users retain the volume download-state control and never see mutation actions.

## Volume rail and pagination

- Each cover uses the shared 2:3 volume contract and is approximately one third of Compact content width.
- The rail has no separate `All volumes / N volumes` header; media-kind selection already owns that header row.
- The first viewport shows about three complete volumes and part of the next volume as the scroll affordance.
- A normal tap selects a volume. Selection is keyed by stable `volumeId`, not by visible position or localized title.
- Approaching the loaded tail requests the next bounded page using deterministic `sortOrder + volumeId` ordering.
- New pages are deduplicated by `volumeId`; they do not reset selection or scroll position.
- Loading is appended to the rail. A page failure keeps existing volumes and shows a tail retry action. Empty first-page failure uses the normal media-local error state.
- Switching media cancels or rejects stale volume-page results and restores that media kind's selection and rail anchor when available.

## Selected-volume metadata

The metadata section is keyed by the selected `volumeId`. Selection changes update the primary action and metadata as one atomic visible state.

The section keeps these six rows in this order:

| Row | Source |
|---|---|
| Format | selected volume format label |
| Language | selected volume language |
| Published date | selected volume published date |
| Page count | selected volume real `pageCount` |
| Metadata source | selected volume stable, server-provided metadata-source display name |
| File path | selected volume authorized file display path |

Rules:

- Missing values display `—`; rows do not borrow values from another volume or the work.
- EPUB, MOBI, TXT, audiobook, or any other format without a real `pageCount` displays `—`. The client never estimates paper pages.
- Metadata source is a stable display value from the selected-volume contract, not a localized provider guess or the active server hostname.
- File path comes from the authorized Work Detail response. The client does not synthesize a server path or substitute its private downloaded-file path. Long values truncate visually while preserving the full accessible value.
- These are passive rows and do not show navigation chevrons.
- Changing volume invalidates stale metadata responses; old-volume values must never flash under the new selection.

## Theme, localization, and accessibility

- Light and Dark use Phase 4 semantic tokens; the board is not a color-sampling source.
- All labels and accessibility actions ship in deliberate `zh-CN` and `en-US` forms. User titles, paths, provider display names, and filenames remain unchanged.
- iOS targets are at least 44 pt and Android targets at least 48 dp.
- Dynamic Type/font scaling may increase cover width or reduce simultaneously visible volumes, but never shrinks labels or touch targets to preserve three exact columns.
- The volume rail announces collection position, selected state, download state, and whether more results are loading.
- Reduced Motion removes nonessential rail settle animation without changing selection or pagination behavior.

## Regression gates

Implementation is not conformant until Android and iOS each cover:

- one author/series/media line with no separate series row;
- filled tag containers in Light and Dark;
- HTML-free description text and a centered chevron expand/collapse action;
- `Media types` on the left with available media choices on the right, including single-media works;
- fixed per-option media width without stretching a single option or reserving unavailable-media placeholders;
- no chapter, track, or page directory on Work Detail;
- Light and Dark;
- single media and all three media kinds;
- one volume, three volumes, and paginated volumes;
- selected-volume metadata changes and missing page count;
- shelf picker from `加入`;
- normal tap selection versus authorized long-press management;
- VoiceOver/TalkBack custom management action;
- download states for ordinary users and hidden mutation actions for unauthorized users;
- maximum supported text size, long English, long paths, rotation, and expanded layout;
- physical-device screenshots compared against v6 with platform-owned navigation excluded from cross-platform pixel identity.
