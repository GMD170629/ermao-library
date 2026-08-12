# Mobile Native Settings v1

Status: **product and visual design approved on 2026-08-12**.

This package expands the Mobile settings scope to provide native functional
equivalents for the Web settings capabilities. The user-approved scope takes
precedence over the earlier Web-only placement for these capabilities.

## Non-negotiable constraints

- Every destination is an App-native page, Sheet, Menu, Dialog, or System UI.
- Settings must not open a server-rendered page, `WebView`, `WKWebView`, custom
  browser, or system browser.
- The current server row is identity-only and has no chevron or management
  action.
- API paths, authorization, validation, conflict behavior, cancellation, and
  destructive-result semantics remain equivalent to the Web capability.
- iOS and Android use their native navigation and controls. Pixel-identical
  platform chrome is not required.
- Light, Dark, large text, `zh-CN`, and `en-US` use semantic tokens; colors are
  not sampled from these images.

## Design boards

| Board | Destinations and key states |
| --- | --- |
| `01-account-core.png` | Me root, profile, account and security, logout confirmation |
| `02-language-email-kindle.png` | Language, Kindle preferences, SMTP configuration/test |
| `03-kindle-queue-users.png` | Kindle queue, user list, user editor, password reset |
| `04-library-imports.png` | Library sources, server directory picker, import tasks, import preferences |
| `05-organize-metadata.png` | Organize queue/candidates, duplicates merge/undo, provider pipelines |
| `06-opds-data-tab-order.png` | OPDS, backup/download/restore/delete, work-detail order |
| `07-health-logs-about.png` | Health run/restart, logs/filter/export/capacity, About/releases |
| `08-recognition-categories-provider.png` | Recognition policy, category governance, provider configuration/test |
| `09-management-source-access.png` | Management index, source editor/delete, user scope picker |

The boards freeze composition, hierarchy, action priority, and state placement.
Exact system control geometry follows the target platform.

## Route tree and authorization

```text
tab.me
├── account.profile                                      authenticated
├── account.security                                     authenticated
├── preferences.language                                 authenticated
├── settings.email-kindle
│   ├── settings.kindle                                  authenticated
│   └── settings.smtp                                    canManageSystem
├── settings.kindle-queue                                authenticated, own tasks
├── settings.management                                  filtered by permission
│   ├── settings.users                                   isAdmin
│   │   ├── settings.user.create                         isAdmin
│   │   ├── settings.user.edit                           isAdmin
│   │   ├── settings.user.scope                          isAdmin
│   │   └── settings.user.password                       isAdmin, Sheet
│   ├── settings.library-sources                         canManageSystem
│   │   ├── settings.library-source.create               canManageSystem
│   │   ├── settings.library-source.edit                 canManageSystem
│   │   └── settings.server-directory                    canManageSystem, Sheet
│   ├── settings.import-tasks                            canManageSystem
│   │   ├── settings.import-task                         canManageSystem
│   │   └── settings.import-scans                        canManageSystem
│   ├── settings.import-preferences                      canManageSystem
│   ├── settings.organize-queue                          canManageSystem
│   │   └── settings.recognition-candidates              canManageSystem, Sheet
│   ├── settings.organize-runs                           canManageSystem
│   ├── settings.recognition-policy                      canManageSystem
│   ├── settings.duplicates                              canManageSystem
│   │   └── settings.duplicate-merge                     canManageSystem, Sheet
│   ├── settings.library-operations                      canManageSystem
│   ├── settings.categories                              canManageSystem
│   │   ├── settings.category-rename                     canManageSystem, Sheet
│   │   └── settings.category-merge                      canManageSystem, Sheet
│   ├── settings.metadata-providers                      canManageSystem
│   │   ├── settings.metadata-provider                   canManageSystem
│   │   └── settings.provider-pipeline                    canManageSystem
│   ├── settings.opds                                    canManageSystem
│   ├── settings.data-backups                            canManageSystem
│   │   └── settings.backup-restore                      canManageSystem, Dialog+Sheet
│   ├── settings.work-detail-order                       canManageSystem
│   ├── settings.health                                  canManageSystem
│   └── settings.logs                                    canManageSystem
└── about.app                                            authenticated
```

An authorization change immediately removes unavailable routes and rejects
their in-flight results. A `401` uses the existing full-screen reauthentication
flow. A `403` keeps the native stack intact, removes protected data, and returns
to the nearest still-authorized parent.

## API equivalence matrix

| Native capability | Real server operations |
| --- | --- |
| Profile/security/language/about | `/api/auth/account/*`, `/api/auth/preferences`, `/api/mobile/compatibility` |
| Kindle settings | `GET/PUT /api/kindle-settings` |
| Kindle queue | `GET/POST /api/kindle-send-tasks`, cancel/retry/delete task operations |
| SMTP | `GET/PUT /api/email-settings`, `POST /api/email-settings/smtp-test` |
| Users and scopes | `GET/POST /api/admin/users`, `GET/PATCH/DELETE /api/admin/users/{id}`, `PUT /api/admin/users/{id}/password`, monitor-folder query |
| Library sources | monitor-folder list/create/read/update/delete and `/api/monitor-folders/tree` |
| Directory scan | `POST /api/import-tasks/scan-directory` plus returned operation status/cancel contract |
| Import tasks | list/read/logs/retry/delete, clear and rescan operations under `/api/import-tasks` |
| Import preferences | `GET/PATCH /api/system-settings` using the existing import-preference keys |
| Organize queue | organize jobs/pending/runs, recognize and delete job operations |
| Recognition policy | `GET/PUT /api/organize/policy`, `GET /api/metadata/opf-sync/status` |
| Duplicates | `GET /api/library/duplicates`, merge, operation history, operation undo |
| Categories | list/rename/delete/merge under `/api/library/categories` |
| Metadata providers | provider list/read/update/test and media-kind pipeline update |
| OPDS | `GET/PUT /api/system-settings/opds` |
| Backups | list/read/create/download/restore/delete under `/api/backups` |
| Work-detail order | `GET/PUT /api/system-settings` key `workDetail.tabOrder` |
| Health | health runs/read/event polling and safe import-queue restart operation polling |
| Logs | management-event query/clear and system log-capacity read/update |

Stable Mobile repositories expose typed intent methods rather than paths or raw
JSON. Server-localized `message` values never control UI branches.

## Native interaction contract

- Persistent forms use **Save**; immediate switches reflect server success and
  roll back on failure.
- Search/filter drafts use a Sheet and **Apply** when more than one field is
  involved. Queue status refreshes through cancellable polling.
- Photo input uses the system photo picker. Backup download/export uses the
  system file/share UI without navigating to a browser.
- Delete, merge, restore, queue restart, account disable, password reset, and
  logout use an object-specific native confirmation. Backup restore additionally
  requires the `RESTORE` confirmation literal.
- Passwords, SMTP credentials, and provider secrets are never echoed back,
  cached in view state after submission, logged, or included in diagnostics.
- Lists have loading, empty, cached/stale where applicable, inline retry, partial
  failure, pagination, cancellation, and permission-loss states.

## Acceptance

- No Mobile source contains a settings Web URL builder or settings browser
  callback.
- Every route above has a native iOS and Android destination and a real typed
  repository operation for each enabled control.
- Visibility and resource authorization are tested for authenticated, admin,
  and system-manager actors.
- Destructive operations verify cancel, confirm, error, stale result, and
  success state.
- UI evidence covers both platforms, both locales, Light/Dark, large text, and
  the relevant dialogs/sheets. iOS evidence uses a physical device only.
