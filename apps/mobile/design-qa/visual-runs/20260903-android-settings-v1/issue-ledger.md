# Android Settings Visual Issue Ledger

Status: SCOPED PASS; repository-wide gates documented below

| ID | Baseline issue | Required outcome | Current state |
|---|---|---|---|
| SET-01 | Root large title clips or restores incorrectly | Collapsible `LargeTopAppBar` remains visible and restores safely | Closed: nested scroll fixed; collapse and saved-state restoration covered on device |
| SET-02 | Secondary pages retain bottom navigation and mini-player shell | Hide navigation chrome without stopping audio | Closed: navigation shell hidden for every Me secondary route; root-only shell test passes |
| SET-03 | Rows, typography, icons, and dividers vary by feature | One generated-token-backed Warm Settings component family | Closed for all current routes; retired routes remain excluded by contract |
| SET-04 | Tabs scroll away or have inconsistent dimensions | Equal 48dp tabs pinned below the title bar | Closed: security and SMTP device evidence plus equal-width/height tests |
| SET-05 | Inputs are inconsistently aligned and passwords lack visibility controls | Text starts left; numeric values trail; passwords expose localized visibility actions | Closed: security/SMTP screens and semantics tests verified |
| SET-06 | Aggregate editors use icon-only or unclear save affordances | Visible text save with dirty/loading/disabled states | Closed: shared save action and feature tests preserve existing commands |
| SET-07 | Filter semantics are confused with page tabs | Queue, users, and logs use horizontally scrollable filters | Closed: shared filter bar used by all current admin lists |
| SET-08 | Internal fields, server paths, and technical reader copy leak into UI | Show user-facing permission, catalog, library-count, and format capability copy | Closed: source paths and internal permission names removed from presentation copy |
| SET-09 | Reader settings use nested cards and technical disabled controls | Flat sections with shared rows and compact read-only capability status | Closed: PDF/EPUB/comic physical captures; fixed capabilities show value + reader-owned status |
| SET-10 | Empty/error/loading and dangerous actions vary by page | Shared state and danger primitives with confirmation retained | Closed: shared primitives and focused interaction tests pass |

## Gate notes

- Physical device: Xiaomi M2102K1AC, Android 12, serial `9e896bbc`.
- Settings-focused instrumentation: 31/31 passed (30-test suite plus the large-font segmented-control regression).
- Reader physical capture test: 1/1 passed and produced 16 PNGs across comic, PDF, and EPUB.
- Build, shared host tests, Android unit tests, debug APK, and AndroidTest APK pass.
- `lintDebug` remains blocked by 36 pre-existing findings outside the changed settings Kotlin files: Media3 opt-in findings, one exported-service manifest finding, and the pre-existing unused `work_open_player` resource.
- The repository-wide connected suite previously reported 99/114 with 15 unrelated failures in library, reader navigator, cover-menu, and legacy visual-fixture tests. The settings-focused suite is green.
