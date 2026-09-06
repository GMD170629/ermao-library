# Android lint classification

Scope: read-only comparison of `apps/mobile/androidApp/build/reports/lint-results-debug.xml` and `.txt` against the current working-tree diff. No Android source, resource, manifest, build, device, or browser changes were made for this check.

## Snapshot

- Report: 46 errors (`lint-results-debug.xml` and `.txt`, current debug report).
- Newly introduced issues in the current visual-polish/page/menu diff: **0 found**.
- No reported issue is in the touched page/menu files (`HomeScreen.kt`, `LibraryScreen.kt`, `WorkDetailScreen.kt`, `ContentComponents.kt`, `AdministrativeCoreScreens.kt`, `WarmPageMenus.kt`, or the related shared UI/theme files).

| Lint id | Count | Locations | Diff classification |
| --- | ---: | --- | --- |
| `UnsafeOptInUsageError` | 34 | `features/audio/infrastructure/AndroidAudioPlaybackService.kt` (5), `AuthenticatedAudioDataSource.kt` (29) | Existing audio infrastructure; neither file is changed in the current diff. |
| `PluralsCandidate` | 2 | `src/main/res/values/strings.xml`: `reader_bookmark_count`, `reader_pdf_page_count_detail` | Existing declarations; current diff only removes unrelated string entries and does not change these keys. |
| `UnusedResources` | 9 | `src/main/res/values/strings.xml`: `reader_contents_current`, `reader_restore_warning`, `reader_restore_warning_dismiss`, `work_open_player`, and five `reader_setting_*` entries | Existing declarations; none of these keys is added or changed by the current diff. |
| `ExportedService` | 1 | `src/main/AndroidManifest.xml:34` | Existing manifest entry; Manifest is unchanged in the current diff. |

The current diff does remove `work_metadata_missing` and several obsolete reader copy entries; those deletions are not reported by this lint snapshot and do not account for any of the 46 locations above. The line-number shift in `strings.xml` is therefore from unrelated deletions, not a new lint finding.

These are static lint findings, not evidence of a new visual defect. This check does not establish runtime behavior, accessibility behavior, or screenshot results.

## Fixed Web toolchain and start locations

- Node executable: `C:\Program Files\nodejs\node.exe` (`v22.23.1`).
- Pinned pnpm invocation: `C:\Program Files\nodejs\corepack.cmd pnpm`, resolving `9.12.2` from the root `package.json` `packageManager` field. The fallback `pnpm.cmd` resolves `11.19.0` and was not used for the fixed checks.
- Web scripts: `apps/web/package.json`.
  - `dev` at line 7: `next dev --webpack -H 0.0.0.0 -p 3000`; from repository root use `corepack pnpm --filter @shuku/web dev`.
  - `start` at line 12: `next start -p 3000` after a Web build.
  - `start:ios` at line 13 binds `0.0.0.0`.

No Web server was started for this classification.
