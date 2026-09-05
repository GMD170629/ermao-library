# Android settings visual contract v1

Status: frozen for implementation

Authoritative direction: Material 3 Expressive behavior with the existing WarmPage colors and numeric tokens. The current physical-device screenshots in `artifacts/audits/android-settings-2026-09-03` are the baseline, not the target.

## Primary checkpoints

The annotated structural targets are in `target-blueprints.svg`:

1. Me root: collapsing large title, flat grouped rows, root navigation visible.
2. Account security: compact app bar, pinned equal tabs, left-aligned fields, visible text save, danger row at the end, no root navigation.
3. User editor: compact app bar, explicit text save, short enums as equal segmented controls, aggregate fields remain a single draft, no technical identifiers.
4. Reader settings: contextual sheet remains, but uses the same typography, section rhythm and selection vocabulary; unavailable engine capabilities become compact read-only explanations.

## Must-match axes

- Root title collapses with content and never covers a restored scroll position.
- Detail screens hide root navigation chrome and preserve a single compact top bar.
- Page tabs remain pinned and have equal 48dp touch regions.
- Settings rows use the existing 54dp minimum, 16dp horizontal inset, 20dp icon in a 28dp slot, and shared divider alignment.
- Root title uses `display`; detail title uses `sectionTitle`; row title uses `body`; supporting copy uses `callout`; labels and values use `label`.
- Text fields are leading-aligned; password fields have a visibility action.
- Standalone preferences save immediately. Aggregate forms expose a visible text save action.
- Navigation icons come from one rounded semantic registry; non-navigation settings rows do not show decorative icons.
- Flat canvas and spacing define hierarchy. No elevation, card nesting, or per-page geometry overrides.
- Empty, loading, error, read-only, disabled, and destructive states use one shared visual and semantic contract.

## Platform-adapted axes

- Android owns the app bar, system bars, predictive back, dialog and sheet behavior.
- Compact devices use the bottom navigation only on root destinations; expanded devices use the corresponding rail/drawer only on roots.
- Filter chips may use content width, but they must live in a horizontally scrollable filter bar and must never stand in for page tabs or persisted enum selection.

## Data-dependent axes

- Long English strings may wrap only in supporting text. Titles, buttons and segmented labels must select a non-truncating alternative control.
- Permission-dependent management rows may be absent; remaining rows retain section rhythm without empty headings.
- Reader controls vary by publication format; unavailable controls do not reserve a full interactive control footprint.

## Explicit exclusions

- Retired Android administrative routes remain unavailable and are not redesigned.
- Backend APIs, KMP application/domain contracts, authorization rules and persistence transactions remain unchanged.
- Baseline screenshots that contain real email addresses or server paths must not be copied into publishable final evidence.
