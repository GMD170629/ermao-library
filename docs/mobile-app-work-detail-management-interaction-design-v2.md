# Mobile Work Detail Management Interaction Design v2

## Status and authority

This document refines the selected task-centered management workspace. It is an interaction-design companion to `mobile-app-work-detail-management.md`; that capability contract remains authoritative. The selected menu composition is frozen by `docs/assets/mobile-app-hifi-v1/work-detail-book-control-menu-floating-card-v1.png`. The five earlier generated boards under `docs/assets/mobile-work-management-design-v2/` illustrate task forms only and are not menu layout sources. Their filenames and any visible split, move, structural reclassification, or deletion controls are retired historical content. If generated text conflicts with this document or the capability contract, ignore the generated text.

The design does not add batch management, new-volume creation, merge, source-file operations, provider configuration, Kindle conversion, or any other capability not already exposed by the native management repository.

## Navigation model

- Work Detail removes the top-right overflow/management action.
- The **More** quick action below the reading CTA opens a scrollable, grouped Book control menu over the current detail context.
- Long-pressing a volume cover opens the same menu surface keyed to that exact volume. The volume title remains presentational.
- The menu begins with compact cover/title/context identity, dims the detail page behind it, and preserves the user's scroll and selected volume when dismissed.
- Simple operations execute from the menu with progress/confirmation. Form, provider-search, file-picker, target-search, and comparison tasks open a focused Sheet above the detail page.
- A successful write dismisses the task surface, refreshes the affected work/volume, and keeps the user on Work Detail.
- VoiceOver/TalkBack expose a localized **Volume actions** custom action on the cover, and keyboard/switch-control users receive an equivalent non-gesture action.

## Selected floating-menu visual contract v2

![Work Detail Book Control Menu Floating Card v1](assets/mobile-app-hifi-v1/work-detail-book-control-menu-floating-card-v1.png)

The selected direction is a compact contextual floating card, not a fixed right-side panel, full-width bottom sheet, dialog page, or navigation destination.

- Anchor the menu to the invoking pointer location. A volume long press uses the actual press coordinate; the **More** action uses the tapped control bounds. Place the closest menu corner beside that anchor, then clamp the card inside 12 pt/dp safe-area margins. The card must not jump to a fixed screen corner.
- Compact width targets 216–232 pt/dp and is content-bounded; Expanded layouts keep the same cap rather than stretching it. Avoid a wide empty lane between labels and trailing icons.
- Use the platform blur/material implementation over a warm raised-surface tint. Target visual opacity is 88–92%, with a subtle warm outline and one soft elevation shadow. The background scrim dims Work Detail but leaves the selected cover and page structure recognizable.
- The compact header uses a 36–40 pt/dp cover, a body-sized semibold title, and at most one caption line of selected-volume context. Long titles truncate rather than increasing the header into a second hero region.
- Rows remain single-column with a visually compact 44 pt/dp rhythm while preserving a platform-compliant 48 pt/dp touch target. Horizontal padding is 14–16 pt/dp, trailing icons are 18–20 pt/dp, and label/icon spacing is intentional rather than filled by an oversized spacer. Dividers and group spacing express hierarchy; rows are not individual cards.
- The menu body scrolls independently only when the available space around the anchor cannot contain all actions. Work Detail underneath does not move while the overlay is open.
- Tapping outside, system Back/Escape, or completing an immediate action dismisses the menu and restores focus to the invoking control or cover.
- The same surface geometry and material are reused for Book and Volume control menus. Only the contextual header and locked operation list change.
- Light and dark themes map the material through semantic Warm Page colors; do not hard-code the dark concept board's sampled colors.
- The reference image contains illustrative content and scale. It freezes overlay placement, hierarchy, density, and material character, not device chrome, demo data, or rasterized UI.

The user-supplied edit-form reference freezes the interaction model only: selecting **Edit** presents a focused native Sheet above the current Work Detail, with dismiss, editable fields, keyboard-safe scrolling, and a persistent save action. Its Emby colors, fields, paths, locks, and sorting controls are illustrative and do not override this product's field contract.

## Focused-task presentation contract

- Every form/search/comparison task opens directly from its control-menu row as a native Sheet over Work Detail. There is no intermediate management workspace, scope selector, task menu, or standalone management navigation destination.
- **Edit** opens the relevant work or volume editor directly. Closing or saving returns to the unchanged Work Detail scroll position and selected volume.
- Upload Cover may hand off to the platform file picker; Regenerate Cover uses a native confirmation dialog owned by Work Detail. The remaining complex operations open their exact task Sheet.
- The former standalone Work Management/Edit page and its navigation route are removed on both platforms. Shared application/domain operations remain reusable and are not duplicated into presentation code.

## Locked menu contents

### Book control menu

`添加到“系列” / 添加到“书架” / 标记为未读 / 下载 / 编辑 / 识别 / 上传封面 / 重新生成封面 / 发送到 Kindle`

The first two items act on the work. Mark Unread, Download, and Send to Kindle act on the currently selected volume. Edit, Recognize, and both cover actions act on the work.

### Volume control menu

`标记为未读 / 下载 / 编辑 / 修改媒体类型 / 发送到 Kindle`

Every action is keyed by the long-pressed cover's `volumeId`. Download uses state-aware labels without changing its stable menu position. Change Media Type corrects classification metadata only and does not change directory-derived ownership.

## Book task workspace

### Edit book information

Fields are title, author, description, series, series index, and tags. Title is required. Series index is optional and must be a finite number when present. Tags use the existing comma-separated draft mapping. Save remains disabled while validation fails. Leaving a dirty form requires discard confirmation.

### Recognize metadata

1. Load enabled providers for the selected media kind.
2. Select one provider and enter a query prefilled from the work title.
3. Search and select exactly one candidate.
4. Compare current and candidate values.
5. Explicitly select any available fields from cover, title, author, description, tags, series name, publisher, published date, language, and ISBN.
6. Optionally apply supported volume fields to all volumes through the existing `applyToAllVolumes` input.
7. Apply only the selected fields, refresh detail, and show a compact success Snackbar.

Search loading, no-results, provider unavailable, network failure, and apply failure stay inline and preserve the user's provider, query, candidate, and field selection.

### Cover management

- Show the current cover preview.
- **Upload cover** hands off to the platform picker and accepts JPEG, PNG, or WebP up to 10 MiB.
- **Regenerate cover** requires confirmation because it replaces the visible cover.
- On failure, keep the previous cover visible and show the stable error inline.

No crop editor, camera capture promise, or image-generation controls are added.

### Send to Kindle

- Load readiness from the existing Kindle settings response.
- When ready, show recipient and sender addresses and list eligible existing EPUB/PDF files with volume, filename, format, and size.
- Selecting a file enables **Add to send queue**. Completion reports queued or already queued.
- When not ready, explain that Kindle or SMTP is not configured and keep send disabled. Do not add a settings shortcut here.

There is no conversion, generated Kindle file, scheduled send, or new file-size rule.

### Reading status

- For a single-volume work, show one control; for a multi-volume work, list visible volumes.
- The management mutation exposes only the supported values **Unread** and **Finished**.
- Save per volume and confirm through a Snackbar. Reading progress and download state remain unchanged.

## Volume task workspace

### Managed download

The first section shows the selected volume's managed download state:

- absent: **Download to device**;
- queued/downloading: progress plus the actions currently available for that platform, and a blocking notice for content-classification correction;
- paused: **Resume**;
- retryable failure: stable failure summary plus **Retry**;
- terminal failure: stable failure summary without a false retry action;
- completed: local size, **Open**, and **Remove local download** with confirmation.

Download progress uses a 4 pt transfer indicator and never reuses reading-progress placement or styling. While the state is queued or downloading, content-classification correction is disabled. That correction changes server metadata only and never rewrites local manifest ownership.

### Edit volume information

Fields are publisher, language, ISBN, identifier, and narrator. All fields are optional metadata. Directory-derived title, version membership, volume index, and sort order are read-only. Generated character counters and additional required markers shown in exploratory boards are not part of the specification.

### Change media type

Show the current type and exactly three choices: e-book, comic, and audiobook. Require explicit confirmation. This changes classification metadata only; it does not change Work, Version, Volume, local download ownership, content, or files.

### Volume-level Kindle

Use the same readiness and file-selection behavior as book-level Kindle, limited to eligible EPUB/PDF files belonging to the selected volume.

## Shared interaction states

- Capability unknown: centered progress; no mutation controls yet.
- Unsupported server: explain that native management is unavailable; do not call mutation endpoints.
- Unauthorized: hide entry points rather than showing disabled administrative tasks.
- Busy: show a thin top progress indicator and disable repeated submission, close, and conflicting navigation.
- Validation failure: attach messages to the relevant fields and preserve drafts.
- Conflict from an active transfer: keep the user in context and direct them to pause or cancel before correcting content classification.
- Network/server failure: show the stable error code without exposing internal details; preserve draft and local artifacts.
- Success: return to Work Detail, issue a fresh affected work/volume request, and show the updated server result.

## Board index

1. `01-entry-and-task-workspace.png` — entry, book scope, volume list, volume task root.
2. `02-book-info-and-metadata.png` — book form and explicit metadata application flow.
3. `03-cover-kindle-status-delete.png` — cover, Kindle, and reading status; the historical deletion panel is excluded.
4. `04-volume-info-and-structure.png` — volume metadata and content classification; the historical split/transfer panels are excluded.
5. `05-volume-download-kindle-delete.png` — managed download and volume Kindle; the historical deletion panel is excluded.

## Generated-board exclusions

The following incidental text visible in exploratory images is explicitly non-authoritative and must not be implemented: a 50 MB Kindle limit, SMTP host/port/TLS details, generated form character limits, required volume index, provider settings, Kindle format generation, Work/Version/Volume create/delete/split/move/merge controls, and any operation not listed in this document.
