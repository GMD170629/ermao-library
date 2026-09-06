# Android core tabs polish — approved target v1

Status: frozen by the user's implementation request, 2026-09-05.

The approved plan in this task supersedes older screenshot anchors for the specific changes below. The existing installed APK and the current audit are comparison baselines, not the target. No further design approval is required to implement these decisions.

## Environment and evidence

- Android physical device `9e896bbc`, Xiaomi M2102K1AC, portrait, 1440 × 3200, density 560, font scale 1.0, zh-CN, App Light.
- Web: compact viewport near Android's 411 × 914 logical size; compare semantic colors while preserving Web layout and platform geometry.
- Original captures remain in the task's private `core-tabs-polish-v1` artifact directory. Do not commit account identifiers, server details, or private originals.
- Full product shell screenshots prove page and navigation layout; component fixtures prove isolated bounds and input/menu states only.

## Fixed visual target

| Surface | Approved final composition and dimensions |
| --- | --- |
| Palette | Contract v1.2.0; actionAccent and brandAccent #FF4F2A; canvas #FBFAF8; navigation #F3F1EE; surface #FFFDFA; surfaceRaised #FFFFFF; accentSoft #FCE6DF. No contrast-driven recoloring. |
| Page shell | Root headings retain the common large-title role. A page owns its top system inset; navigation owns its bottom inset. Settings and book details share a compact bar, Android back arrow, title role and icon slots. Settings tabs remain pinned below that bar. |
| Inputs | Search and settings use the same 12dp control radius and theme colors. All form text including numeric fields is leading-aligned. Password controls retain a stable slot and existing behavior. |
| Popup | Retain native Material popup shell. Item horizontal padding 12dp on each side; minimum item height 48dp; icon slots 24dp. A selection check never changes available label width. Floating menus, sheets, tabs and segmented controls keep distinct roles. |
| Home | Continue reading → Recent reading → Recent additions. Exactly one recent-reading item uses the existing 64dp-cover BookListItem. Multiple recent-reading items retain the horizontal cover list. No data deduplication or removed section. |
| Library | Search → scope → statistics → three-column covers. Statistics have 8dp top/bottom padding. Book titles allow two lines; blank authors do not create empty lines. |
| Shelves / Me | Preserve rows, section order, titles and actions. Shared gutters, icon weight, text axes and trailing slots remain consistent. A one-shelf empty remainder is data-dependent, not a defect. |
| Directory root | Retain vertical cover, identity, reading action, secondary actions and directory. Directory cover width 96dp, aspect 2:3; identity gaps 8dp, no blank metadata rows. The audit's four-child directory must expose a distinguishable child title in the initial viewport. |
| Directory content | Default grid and existing list toggle remain. Grid titles allow three lines and resources retain a separate format caption. Do not parse user titles or invent cover images. |
| Resource detail | Preserve the 120dp resource hero and primary reading action. Secondary action sizes/gaps remain consistent. Omit missing optional metadata rows; omit the whole metadata section when no value exists. |
| SMTP / Kindle | SMTP order: connection, sender identity, delivery limits, test action. No field or operation removed. Empty sender summary says Not configured / 未设置. All added text has zh-CN/en-US values. |

## Verification and boundaries

- Primary: four tabs, directory root, resource detail, password settings and SMTP/Kindle summary. Flow: relevant menus, selected first/middle/last options, focused/filled/empty/disabled inputs, password visibility, search, sort, view toggle, back restoration.
- Color values and input radii must use their authoritative owner. Symmetric geometry may differ by at most one physical pixel due to rounding. Native font rasterization and system popup placement are platform-adapted.
- Excluded: contrast assessment, large-font/TalkBack/rotation matrices, Reader UI, backend/API/persistence changes and iOS UI implementation. Existing semantics and behavior remain intact.
- Tests must not send mail, change credentials, clear app data or submit real configuration changes. Test component fixtures may use synthetic state.
- Each candidate is compared with this fixed target and the preceding accepted build. A regression is repaired before promotion. Compilation is not visual acceptance; the final installed APK requires fresh captures and independent review.
- Reuse owners: canonical visual token JSON/generator; WarmPage components; content BookListItem/BookGridItem; existing detail and settings presentation. Web changes replace colors in current owners without creating parallel components.

The accompanying `target-blueprint.svg` illustrates the approved proportions and role relationships. It is an annotated plan, not a screenshot or a cross-platform system-control pixel target.
