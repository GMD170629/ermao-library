# 全量 OpenAPI 真实请求执行矩阵

- 日期：2026-08-11（Asia/Shanghai）
- Live OpenAPI：152 paths / 209 operations
- 覆盖：209/209，遗漏 0，重复归属 0
- 方法：真实 uvicorn TCP 请求、真实 SQLite、真实 Worker；每项均核对响应和相关表前后状态。
- `Status` 是主流程或已发布退役契约的实测状态；额外的锁竞争、冷启动和空 body 缺陷见各模块报告。

## auth（15）

| Method | Path | Status | 数据库/契约断言 |
|---|---|---:|---|
| PATCH | `/api/auth/account/email` | 200 | updates normalized email without altering role or preferences |
| PATCH | `/api/auth/account/name` | 200 | updates only owner name and updatedAt |
| PATCH | `/api/auth/account/password` | 200 | updates hash and set-deletes every owner session atomically |
| DELETE | `/api/auth/avatar` | 200 | clears avatarPath and removes owned avatar file |
| GET | `/api/auth/avatar` | 200 | streams persisted WebP avatar; User row unchanged |
| POST | `/api/auth/avatar` | 200 | valid image is normalized, atomically published and User.avatarPath updated |
| GET | `/api/auth/capabilities` | 200 | password reset capability and isolated local file path returned |
| POST | `/api/auth/login` | 200 | valid credentials create a second persisted session |
| POST | `/api/auth/logout` | 200 | deletes only current session token and clears cookie |
| GET | `/api/auth/me` | 200 | authenticated projection matches User and preferences without DML |
| POST | `/api/auth/password-reset/confirm` | 200 | atomically updates hash, marks tokens used and removes all sessions |
| POST | `/api/auth/password-reset/request` | 202 | creates one hashed reset token then atomically publishes local reset file |
| POST | `/api/auth/session/refresh` | 200 | single conditional UPDATE extends only current session and preserves session count |
| POST | `/api/auth/setup` | 201 | atomically creates admin, locale preference and first session |
| GET | `/api/auth/setup/status` | 200 | fresh database reports initialized=false; no User/Session rows |

## download（9）

| Method | Path | Status | 数据库/契约断言 |
|---|---|---:|---|
| GET | `/api/download-tasks` | 200 | DownloadTask list reflects persisted row and monitor-folder autoImport projection |
| POST | `/api/download-tasks` | 201 | DownloadTask+last target setting+SystemEvent commit atomically |
| DELETE | `/api/download-tasks/{task_id}` | 200 | Task delete and audit event commit together; sibling tasks remain |
| GET | `/api/download-tasks/{task_id}` | 200 | DownloadTask detail matches ORM status |
| PUT | `/api/download-tasks/{task_id}` | 200 | Set update changes supplied task fields and event together; createdAt is preserved |
| POST | `/api/download-tasks/{task_id}/cancel` | 200 | Cancel conditionally changes only selected task and appends event |
| POST | `/api/download-tasks/{task_id}/import` | 400 | Retired manual-import action does not mutate the downloaded task |
| POST | `/api/download-tasks/{task_id}/retry` | 200 | Retry atomically resets queued/progress/error without touching other DownloadTask rows |
| POST | `/api/download-tasks/{task_id}/start` | 200 | Claim commits before network; real HTTP file publish occurs outside transaction; terminal update commits after |

## download,download-sources（17）

| Method | Path | Status | 数据库/契约断言 |
|---|---|---:|---|
| GET | `/api/source-search-records` | 200 | Retired source tombstone performs zero DML |
| POST | `/api/source-search-records` | 404 | Retired source tombstone performs zero DML |
| POST | `/api/source-search-records/create-download-task` | 404 | Retired source tombstone performs zero DML |
| DELETE | `/api/source-search-records/{record_id}` | 404 | Retired source tombstone performs zero DML |
| GET | `/api/source-search-records/{record_id}` | 404 | Retired source tombstone performs zero DML |
| PUT | `/api/source-search-records/{record_id}` | 404 | Retired source tombstone performs zero DML |
| POST | `/api/source-search-records/{record_id}/create-download-task` | 404 | Retired source tombstone performs zero DML |
| POST | `/api/source-search-records/{record_id}/ignore` | 404 | Retired source tombstone performs zero DML |
| POST | `/api/source-search-records/{record_id}/save` | 404 | Retired source tombstone performs zero DML |
| GET | `/api/sources` | 200 | Retired source tombstone performs zero DML |
| POST | `/api/sources` | 410 | Retired source tombstone performs zero DML |
| DELETE | `/api/sources/{source_id}` | 404 | Retired source tombstone performs zero DML |
| GET | `/api/sources/{source_id}` | 404 | Retired source tombstone performs zero DML |
| PATCH | `/api/sources/{source_id}` | 404 | Retired source tombstone performs zero DML |
| PUT | `/api/sources/{source_id}` | 404 | Retired source tombstone performs zero DML |
| POST | `/api/sources/{source_id}/search` | 404 | Retired source tombstone performs zero DML |
| POST | `/api/sources/{source_id}/test` | 404 | Retired source tombstone performs zero DML |

## health（10）

| Method | Path | Status | 数据库/契约断言 |
|---|---|---:|---|
| GET | `/api/__db-ping` | 200 | typed SELECT database probe succeeds without DML |
| GET | `/api/health` | 200 | live service health reflects real runtime; GET performs no DML |
| GET | `/api/system/health` | 200 | returns detailed real DB/storage/worker health projection without DML |
| POST | `/api/system/health/runs` | 201 | creates one persisted health run and starts external-check thread after commit |
| GET | `/api/system/health/runs/{run_id}` | 200 | reads completed persisted health snapshot/version without DML |
| GET | `/api/system/health/runs/{run_id}/events` | 200 | real SSE stream emits terminal persisted health snapshot without DML |
| GET | `/api/system/log-settings` | 200 | reads event storage limits and usage without DML |
| PUT | `/api/system/log-settings` | 200 | atomically upserts max log bytes and settings.updated audit event |
| GET | `/api/system/queue-operations/{operation_id}` | 200 | reads worker-completed queue operation without DML |
| POST | `/api/system/queues/import/restart` | 202 | persists restart operation for live worker; worker claims and completes it |

## imports（11）

| Method | Path | Status | 数据库/契约断言 |
|---|---|---:|---|
| GET | `/api/import-tasks` | 200 | Paged ImportTask projection joins logs/folder without writes |
| GET | `/api/import-tasks/{task_id}` | 200 | Single ImportTask view matches persisted status/workId |
| GET | `/api/import-tasks/{task_id}/logs` | 200 | ImportLog rows remain linked and ordered; no mutations |
| GET | `/api/monitor-folders` | 200 | MonitorFolder list reflects existing folder and GET is read-only |
| POST | `/api/monitor-folders` | 201 | MonitorFolder and matching SystemEvent commit atomically |
| GET | `/api/monitor-folders/tree` | 200 | Filesystem traversal happens after the read Session is closed |
| DELETE | `/api/monitor-folders/{folder_id}` | 200 | Folder/access rows delete as a set and sibling monitor remains |
| PATCH | `/api/monitor-folders/{folder_id}` | 200 | PATCH changes only supplied columns and preserves createdAt |
| PUT | `/api/monitor-folders/{folder_id}` | 200 | PUT reuses prepared set update and preserves immutable ID/createdAt |
| GET | `/api/tracking/release-title-parser` | 200 | Pure parser executes after Session close and makes no DML |
| POST | `/api/tracking/release-title-parser` | 200 | POST parser is also DB read/write free |

## imports,imports-write（10）

| Method | Path | Status | 数据库/契约断言 |
|---|---|---:|---|
| GET | `/api/import-scan-jobs` | 200 | ScanJob list includes the pending manual job |
| GET | `/api/import-scan-jobs/{job_id}` | 200 | ScanJob detail status agrees with ORM row |
| POST | `/api/import-scan-jobs/{job_id}/cancel` | 200 | Cancel performs conditional status update and leaves terminal ScanJob for audit |
| DELETE | `/api/import-tasks` | 200 | Terminal ImportTask IDs are projected then deleted as a set; LibraryWork rows are unaffected |
| POST | `/api/import-tasks/clear` | 409 → 202 | Worker 离线时拒绝且不落操作；Worker 在线后创建 QueueControlOperation 并最终完成集合清理 |
| POST | `/api/import-tasks/rescan` | 202 | All enabled folders are projected first, then ScanJob/WorkItem rows are inserted as a set |
| POST | `/api/import-tasks/scan-directory` | 202 | ImportScanJob+ImportWorkItem+SystemEvent are inserted in one short set write |
| DELETE | `/api/import-tasks/{task_id}` | 200 | Prepared deletion removes task/log rows only; LibraryWork/Volume/File survive when deleteLibraryRecord=false |
| POST | `/api/import-tasks/{task_id}/retry` | 200 | Retry atomically resets status/lease/error and inserts event while source identity is preserved |
| POST | `/api/works/import` | 200 | Multipart file is published outside DB transaction; only last-upload setting is changed |

## kindle（10）

| Method | Path | Status | 数据库/契约断言 |
|---|---|---:|---|
| GET | `/api/email-settings` | 200 | Public email projection masks password and performs no DML |
| PUT | `/api/email-settings` | 200 | All SMTP keys and settings event are written in one set transaction |
| POST | `/api/email-settings/smtp-test` | 200 | Real SMTP connection occurs with Session closed; no setting mutation |
| GET | `/api/kindle-send-tasks` | 200 | User-scoped task list matches one queued row and is read-only |
| POST | `/api/kindle-send-tasks` | 201 | KindleSendTask+masked SystemEvent commit atomically; SMTP snapshot is precomputed |
| DELETE | `/api/kindle-send-tasks/{task_id}` | 200 | Terminal Kindle row is deleted atomically with audit event; LibraryFile remains |
| POST | `/api/kindle-send-tasks/{task_id}/cancel` | 200 | CAS cancel changes queued→cancelled and event in one transaction |
| POST | `/api/kindle-send-tasks/{task_id}/retry` | 200 | CAS retry changes cancelled→queued and resets attempts without altering snapshot fields |
| GET | `/api/kindle-settings` | 200 | GET joins user preference with global SMTP projection and performs no DML |
| PUT | `/api/kindle-settings` | 200 | Kindle recipient UserPreference UPSERT is atomic and isolated from global SMTP settings |

## library（47）

| Method | Path | Status | 数据库/契约断言 |
|---|---|---:|---|
| GET | `/api/dashboard/continue-reading` | 200 | tracked DB tables unchanged |
| GET | `/api/dashboard/recent-books` | 200 | tracked DB tables unchanged |
| GET | `/api/dashboard/recent-reading` | 200 | tracked DB tables unchanged |
| GET | `/api/dashboard/summary` | 200 | tracked DB tables unchanged |
| GET | `/api/library/categories` | 200 | tracked DB tables unchanged |
| POST | `/api/library/categories/merge` | 200 | source facet removed; links remapped/deduplicated; operation recorded |
| DELETE | `/api/library/categories/{facet_id}` | 200 | facet/link removed and only linked work metadata changed |
| PATCH | `/api/library/categories/{facet_id}` | 200 | facet display/normalized name and aliases updated without changing unrelated Work.updatedAt |
| GET | `/api/library/duplicates` | 200 | tracked DB tables unchanged |
| POST | `/api/library/duplicates/merge` | 200 | source work removed, volume moved to target media group, duplicate media group deduplicated |
| GET | `/api/library/facets` | 200 | tracked DB tables unchanged |
| GET | `/api/library/filter-options` | 200 | tracked DB tables unchanged |
| GET | `/api/library/filter-schema` | 200 | tracked DB tables unchanged |
| GET | `/api/library/groupings` | 200 | tracked DB tables unchanged |
| GET | `/api/library/operations` | 200 | tracked DB tables unchanged |
| POST | `/api/library/operations/{operation_id}/undo` | 200 | deleted facet/link/tag restored and operation moved to UNDONE |
| GET | `/api/management/folders` | 200 | tracked DB tables unchanged |
| GET | `/api/management/overview` | 200 | tracked DB tables unchanged |
| GET | `/api/series` | 200 | tracked DB tables unchanged |
| GET | `/api/works` | 200 | tracked DB tables unchanged |
| POST | `/api/works/bulk` | 200 | two Work rows and facet links changed in one bounded write; all other Work.updatedAt unchanged |
| POST | `/api/works/bulk/cover` | 200 | cover prepared outside transaction, DB path set, file atomically published |
| POST | `/api/works/bulk/find-replace/preview` | 200 | preview is read-only |
| POST | `/api/works/merge` | 200 | new merged aggregate created; source aggregates removed; files preserved; operation/writeback intents consistent |
| POST | `/api/works/merge/preview` | 200 | preview read-only |
| DELETE | `/api/works/{work_id}` | 200 | work/media/volume/file/link rows cascade consistently; source file retained by policy |
| GET | `/api/works/{work_id}` | 200 | tracked DB tables unchanged |
| PATCH | `/api/works/{work_id}` | 200 | target Work + facet links + explicit writeback intent only; other Work.updatedAt unchanged |
| POST | `/api/works/{work_id}/cover/regenerate` | 200 |  |
| POST | `/api/works/{work_id}/cover/upload` | 200 | single-cover publication updates target work/volumes only |
| PUT | `/api/works/{work_id}/detail-preference` | 200 | one WorkDetailPreference UPSERT; work metadata timestamp preserved |
| PATCH | `/api/works/{work_id}/editions/{edition_id}` | 410 |  |
| POST | `/api/works/{work_id}/editions/{edition_id}/primary` | 410 |  |
| POST | `/api/works/{work_id}/editions/{edition_id}/split` | 410 |  |
| GET | `/api/works/{work_id}/media-versions/{media_version_id}/volumes` | 200 | tracked DB tables unchanged |
| POST | `/api/works/{work_id}/metadata/apply` | 200 | Work/Volume set write + facet sync + explicit MetadataWritebackPreparation; unrelated rows preserved |
| POST | `/api/works/{work_id}/metadata/search` | 200 | real local provider HTTP call outside write transaction; cache write may be recorded |
| POST | `/api/works/{work_id}/volumes/batch` | 200 | batch TRANSFER removes emptied source and preserves target existing data |
| DELETE | `/api/works/{work_id}/volumes/{volume_id}` | 200 | last volume deletion removes empty work/media/file aggregate and records operation |
| PATCH | `/api/works/{work_id}/volumes/{volume_id}` | 200 | only selected LibraryVolume updated; owning Work.updatedAt and File unchanged |
| POST | `/api/works/{work_id}/volumes/{volume_id}/move` | 200 | two sibling sortOrder values swapped in one write |
| POST | `/api/works/{work_id}/volumes/{volume_id}/move-to` | 200 | source aggregate removed when emptied; volume/file moved to target without data loss |
| GET | `/api/works/{work_id}/volumes/{volume_id}/reading-units` | 200 | tracked DB tables unchanged |
| POST | `/api/works/{work_id}/volumes/{volume_id}/reclassify` | 200 | volume moved to real COMIC media version; old empty media version removed |
| POST | `/api/works/{work_id}/volumes/{volume_id}/split` | 200 | new work/media aggregate created and selected volume/files transferred |

## media（10）

| Method | Path | Status | 数据库/契约断言 |
|---|---|---:|---|
| GET | `/api/files/{file_id}` | 200 | tracked DB tables unchanged |
| HEAD | `/api/files/{file_id}` | 200 | tracked DB tables unchanged |
| GET | `/api/metadata/cover-proxy` | 200 | real local HTTP image fetched through configured provider origin; tracked DB tables unchanged |
| GET | `/api/volumes/{volume_id}/cover` | 200 | tracked DB tables unchanged |
| GET | `/api/volumes/{volume_id}/file` | 200 | tracked DB tables unchanged |
| HEAD | `/api/volumes/{volume_id}/file` | 200 | tracked DB tables unchanged |
| GET | `/api/volumes/{volume_id}/pages` | 200 | 缺持久索引时关闭读 Session 后解析 archive；ReadingUnit、Volume.updatedAt 均不变 |
| GET | `/api/volumes/{volume_id}/pages/{page_index}` | 200 | tracked DB tables unchanged |
| GET | `/api/works/{work_id}/cover` | 200 | tracked DB tables unchanged |
| POST | `/api/works/{work_id}/volumes/download` | 200 | ZIP streamed from selected real volume files; DB unchanged |

## metadata（8）

| Method | Path | Status | 数据库/契约断言 |
|---|---|---:|---|
| GET | `/api/metadata/opf-sync/status` | 200 | 返回 pendingTargets/pendingPreparations/capacity/utilization；查询零 DML |
| PUT | `/api/metadata/provider-pipelines/{media_kind}` | 200 | EBOOK pipeline rows are replaced as a set; COMIC rows remain byte-equivalent |
| GET | `/api/metadata/providers` | 200 | Source/MetadataProviderPipeline projections readable; GET performs no DML |
| GET | `/api/metadata/providers/{provider_id}` | 200 | Persisted provider projection matches PUT/PATCH |
| PATCH | `/api/metadata/providers/{provider_id}` | 200 | PATCH persists priority without replacing config/secrets |
| PUT | `/api/metadata/providers/{provider_id}` | 200 | Only bangumi Source config/version changes and one SystemEvent is atomically added |
| POST | `/api/metadata/providers/{provider_id}/test` | 200 | Network call occurs outside transaction; Source lastTestStatus is persisted afterward |
| GET | `/api/metadata/writebacks/{operation_id}` | 200 | Explicit writeback Operation is visible as PENDING with accepted preparation |

## organize（9）

| Method | Path | Status | 数据库/契约断言 |
|---|---|---:|---|
| GET | `/api/organize/candidates` | 200 | Eligibility projection reads works/policy without writes |
| GET | `/api/organize/jobs` | 200 | Paginated job projection includes provider names and status counts |
| DELETE | `/api/organize/jobs/{job_id}` | 200 | OrganizeJob and related lookup/provider execution rows delete atomically; Work survives |
| GET | `/api/organize/jobs/{job_id}` | 200 | Job detail joins lookup/provider executions/writeback without mutation |
| POST | `/api/organize/jobs/{job_id}/recognize` | 200 | Prior lookup/executions are replaced and new PENDING lookup is inserted in one transaction |
| GET | `/api/organize/pending` | 200 | Pending projection is consistent with terminal job status |
| GET | `/api/organize/policy` | 200 | GET returns initialized non-null createdAt/updatedAt values |
| PUT | `/api/organize/policy` | 200 | OrganizePolicy set update is atomic and initializes timestamps |
| GET | `/api/organize/runs` | 200 | Worker-created OrganizeRun terminal counters match jobs |

## preferences（2）

| Method | Path | Status | 数据库/契约断言 |
|---|---|---:|---|
| GET | `/api/auth/preferences` | 200 | reads persisted preference projection without DML |
| PATCH | `/api/auth/preferences` | 200 | set-upserts six allowed keys without touching User.updatedAt |

## reader-v1-retired（13）

| Method | Path | Status | 数据库/契约断言 |
|---|---|---:|---|
| GET | `/api/editions/{edition_id}/cover` | 410 | tracked DB tables unchanged |
| GET | `/api/editions/{edition_id}/file` | 410 | tracked DB tables unchanged |
| HEAD | `/api/editions/{edition_id}/file` | 410 | tracked DB tables unchanged |
| GET | `/api/editions/{edition_id}/progress` | 410 | tracked DB tables unchanged |
| PATCH | `/api/editions/{edition_id}/progress` | 410 | tracked DB tables unchanged |
| POST | `/api/editions/{edition_id}/progress` | 410 | tracked DB tables unchanged |
| PUT | `/api/editions/{edition_id}/progress` | 410 | tracked DB tables unchanged |
| GET | `/api/reader/preferences` | 410 | tracked DB tables unchanged |
| PUT | `/api/reader/preferences` | 410 | tracked DB tables unchanged |
| GET | `/api/reader/preferences/{reader_type}` | 410 | tracked DB tables unchanged |
| PATCH | `/api/reader/preferences/{reader_type}` | 410 | tracked DB tables unchanged |
| PUT | `/api/reader/preferences/{reader_type}` | 410 | tracked DB tables unchanged |
| GET | `/api/reader/{edition_id}/bootstrap` | 410 | tracked DB tables unchanged |

## reader-v2-retired（7）

| Method | Path | Status | 数据库/契约断言 |
|---|---|---:|---|
| GET | `/api/reader/v2/editions/{edition_id}/bookmarks` | 410 | tracked DB tables unchanged |
| PUT | `/api/reader/v2/editions/{edition_id}/bookmarks` | 410 | tracked DB tables unchanged |
| GET | `/api/reader/v2/editions/{edition_id}/bootstrap` | 410 | tracked DB tables unchanged |
| GET | `/api/reader/v2/editions/{edition_id}/progress` | 410 | tracked DB tables unchanged |
| PATCH | `/api/reader/v2/editions/{edition_id}/progress` | 410 | tracked DB tables unchanged |
| POST | `/api/reader/v2/editions/{edition_id}/progress` | 410 | tracked DB tables unchanged |
| PUT | `/api/reader/v2/editions/{edition_id}/progress` | 410 | tracked DB tables unchanged |

## reader-v3（5）

| Method | Path | Status | 数据库/契约断言 |
|---|---|---:|---|
| GET | `/api/reader/v3/volumes/{volume_id}/bookmarks` | 200 | tracked DB tables unchanged |
| PUT | `/api/reader/v3/volumes/{volume_id}/bookmarks` | 200 | one set replacement creates one ReaderBookmark |
| GET | `/api/reader/v3/volumes/{volume_id}/bootstrap` | 200 | volume/media/file/reading-unit projection only; tracked DB tables unchanged |
| PUT | `/api/reader/v3/volumes/{volume_id}/progress` | 200 | Progress/Cursor/History set writes; LibraryWork/Volume updatedAt preserved |
| PUT | `/api/reader/v3/volumes/{volume_id}/reading-status` | 200 | progress reaches 100 without altering library metadata timestamps |

## shelf（5）

| Method | Path | Status | 数据库/契约断言 |
|---|---|---:|---|
| GET | `/api/shelves` | 200 | tracked DB tables unchanged |
| POST | `/api/shelves` | 201 | Shelf + two ShelfWork rows created atomically |
| DELETE | `/api/shelves/{shelf_id}` | 200 | Shelf and remaining ShelfWork links deleted atomically |
| GET | `/api/shelves/{shelf_id}` | 200 | tracked DB tables unchanged |
| PATCH | `/api/shelves/{shelf_id}` | 200 | Shelf updated; membership set retained |

## system（15）

| Method | Path | Status | 数据库/契约断言 |
|---|---|---:|---|
| GET | `/api/app-config` | 200 | public locale/version projection has no database writes |
| GET | `/api/backups` | 200 | lists newly created backup archive without DML |
| POST | `/api/backups` | 201 | creates validated ZIP snapshot from live SQLite and storage metadata |
| DELETE | `/api/backups/{backup_id}` | 200 | removes only selected backup archive; database snapshot remains intact |
| GET | `/api/backups/{backup_id}` | 200 | returns validated archive metadata without DML |
| GET | `/api/backups/{backup_id}/download` | 200 | streams actual ZIP archive bytes without database writes |
| POST | `/api/backups/{backup_id}/restore` | 200 | maintenance-barrier live restore removes post-backup marker and preserves snapshot settings/session |
| GET | `/api/dashboard/system-status` | 200 | aggregates health/import projections without DML |
| DELETE | `/api/management/events` | 200 | set-deletes existing events then inserts events.cleared audit row atomically |
| GET | `/api/management/events` | 200 | lists persisted authorization/system audit rows and facets without DML |
| GET | `/api/system-settings` | 200 | returns public settings with sensitive value redacted and no DML |
| PATCH | `/api/system-settings` | 200 | patch set-upserts restore marker while preserving unrelated settings |
| PUT | `/api/system-settings` | 200 | set-upserts normal/import/sensitive settings with one audit event |
| GET | `/api/system-settings/opds` | 200 | reads resolved OPDS configuration without DML |
| PUT | `/api/system-settings/opds` | 200 | atomically upserts OPDS keys and opds.settings.updated event |

## users（6）

| Method | Path | Status | 数据库/契约断言 |
|---|---|---:|---|
| GET | `/api/admin/users` | 200 | lists both users in deterministic order without DML |
| POST | `/api/admin/users` | 201 | atomically creates member, locale preference and user.created event |
| DELETE | `/api/admin/users/{user_id}` | 200 | deidentifies owned references, cascades personal data and writes anonymous audit event |
| GET | `/api/admin/users/{user_id}` | 200 | returns persisted member permissions and locale without DML |
| PATCH | `/api/admin/users/{user_id}` | 200 | atomically updates authorization, locale and audit event while preserving active session |
| PUT | `/api/admin/users/{user_id}/password` | 200 | updates password hash, removes all member sessions and records audit event |
