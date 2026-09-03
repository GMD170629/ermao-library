# Android Reader Settings visual contract v2

Status: frozen for implementation

Authoritative direction: the user-approved Android-only plan from 2026-09-03. Preserve the Reader settings catalog, order, behavior, persistence, and capability decisions. Change only Android presentation.

## Primary checkpoint

- Physical Xiaomi M2102K1AC, Android 12, 1440x3200, portrait.
- zh-CN, light Reader theme, font/display scale 1.0.
- Reflowable publication, Reader controls opened through the product shell, Reading Settings sheet at the top and with Advanced Settings expanded.

## Target structure

1. The sheet title is the sole page-level title and uses the WarmPage `title` role.
2. Every regular and advanced setting section has one `headline` title above one `surfaceRaised` card.
3. Cards use the shared 16dp task radius, no elevation, 16dp content axis, 54dp row minimum, 48dp control minimum, and inset hairline dividers.
4. Setting titles use `body`, supporting explanations use `callout`, and values/statuses use `label`.
5. Available switches, segmented choices, choice sheets, and number controls retain their current interactions while sharing the same item shell and vertical rhythm.
6. Read-only capability rows remain at readable contrast and expose no disabled-switch affordance.
7. Fixed-on swipe shows `Always on` / `始终开启` only when Swipe is `NotImplemented`; generic unimplemented controls show `Not adjustable` / `暂不可调整`; temporary states show `Temporarily unavailable` / `暂不可用` plus the catalog reason.
8. `Fixed for this reader` / `由当前阅读器确定` and misleading saved on/off values are absent from unavailable controls.
9. Advanced Settings remains the only collapsible group and uses the same `headline` role as section titles.

## Must-match axes

- Section order and setting order are unchanged.
- Group boundaries are visible without relying on whitespace alone.
- Page title, section title, setting title, supporting copy, and value each have one stable typography role.
- Item content shares one left and right axis; segmented controls do not collide with dividers.
- Read-only status and reason are understandable without SDK or implementation terminology.
- The sheet, system bars, Reader content, bottom controls, dismissal, scrolling, and preference submission behavior do not regress.

## Platform-adapted and excluded

- Android retains its current modal sheet, predictive back, system-bar, and TalkBack behavior.
- Web and iOS presentation are excluded.
- Reader contracts, generated bindings, controller/session behavior, preference schema, and other Android settings pages are excluded.

## Candidate 01 hypothesis

One lightweight surface per section plus a typed read-only presentation mapping will make group membership and status meaning immediately legible without increasing navigation steps or changing the settings contract.
