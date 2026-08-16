# Work Detail v6 visual issue ledger

Target lock: `work-detail-selected-volume-metadata-light-dark-v6.png` at SHA-256 `E899B9DF249711C67EE65C7082A53B90C692EB333A9C194886CD1A478D640460`.

| Area | Previous implementation deviation | v6 implementation decision | Status |
|---|---|---|---|
| Header and identity | Side-by-side identity and custom page hierarchy | Normal detail navigation with centered cover and identity | Verified on physical Android v6.1 capture |
| Actions | Two competing primary buttons and persistent edit affordance | One full-width primary CTA plus Download / Reading Status / Add / More | Verified on physical Android v6.1 capture; interaction tests remain covered separately |
| Description/media | First-level tabs split a single task flow | One continuous scroll | Implemented |
| Volumes | Grid/single-volume fallback and no bounded tail paging | Always-present horizontal rail, about three Compact items, deterministic bounded paging with retry and stale-result rejection | Verified on physical Android single-volume state; multi-volume pagination remains automated/fixture evidence |
| Metadata | Work-level/static rows | Six fixed rows sourced only from selected volume, localized date, truthful missing values | Verified on physical Android v6.1 below-fold capture |
| Management | Persistent per-volume edit icon | Authorized long press plus VoiceOver/TalkBack custom action; download icon remains independent | Implemented; physical gesture pending unlock |
| Legacy evidence | v2–v5 images could be mistaken for current truth | Deleted all Work Detail v2–v5 design and verification images and references | Closed |

## v6.1 physical-device correction set

The physical-device review image from 2026-08-16 is the regression baseline for this correction set. The v6 board remains the visual target.

| ID | Physical-device deviation | Locked acceptance rule | Status |
|---|---|---|---|
| WD-V61-01 | Series rendered as a separate identity row | Identity uses one centered `author / series / media kind` line; author and series retain independent Facet actions | Closed by physical Android capture `01-work-detail-v61-top.png` |
| WD-V61-02 | Tags have no visual container | Every identity tag uses the semantic raised-surface fill and compact rounded shape in both themes | Closed by physical Android capture `01-work-detail-v61-top.png` |
| WD-V61-03 | Description uses a trailing text action and exposes HTML markup | Description is normalized to plain text; the only expand/collapse affordance is a centered down/up chevron with an accessibility label | Closed by physical Android capture `01-work-detail-v61-top.png` |
| WD-V61-04 | Volume header reads “All volumes / x volumes” | Header is always left `Media versions` and right the available Ebook/Comic/Audiobook selector; it remains visible for a single media kind | Closed by physical Android captures `01-work-detail-v61-top.png` and `02-work-detail-v61-selected-volume-metadata.png` |
| WD-V61-05 | Book directory appears below the volume rail | Work Detail renders no chapter, track, or page directory; directory navigation belongs to Reader / Now Playing | Closed by physical Android capture and UI hierarchy `02-work-detail-v61-selected-volume-metadata.*` |
| WD-V61-06 | A single Ebook option stretches across the entire selector area | Render only available media kinds and keep each visible option at one fixed 80 dp/pt segment; do not stretch or reserve unavailable placeholders | Closed by physical Android capture and measured UI bounds `03-work-detail-v61-fixed-media-width.*` |

Any future screenshot or UI acceptance test for Work Detail must check all five IDs together. A change that restores any previous label, separate series row, raw HTML, text-only expand action, or directory is a design regression.

Android compilation, unit tests, lint, APK assembly, replace-install, cold-start process checks, and shared `iosArm64` compilation have passed. iOS app installation and visual acceptance require a connected physical iPhone or iPad and remain a separate physical-device gate.
