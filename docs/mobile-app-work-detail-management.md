# Mobile Work Detail Management Contract

## Scope

Android and iOS expose the Web work-detail management capability from native Work Detail. This is detail-page parity, not a replacement for global library-governance pages or Web batch selection.

The entry is permission-gated by `authorization.canManageSystem` and server-gated by `/api/mobile/compatibility` capability `workDetailManagement`. Older servers decode the missing capability as `false` and the app does not attempt unsupported mutations.

## Entry hierarchy

- Work Detail has no top-right overflow or management action. The top bar keeps only normal navigation semantics.
- Tapping **More** in the quick-action row below the primary reading action opens the contextual **Book control menu** over Work Detail. It does not navigate to a standalone management page.
- The normal Work Detail quick-action row is **Download / Reading Status / Add / More**. **Add** opens the shelf picker and replaces the former inline edit position; book editing is never duplicated in this row.
- Long-pressing a visible volume **cover** opens the contextual **Volume control menu** for that exact volume. A normal tap on the cover continues to select the volume; the title remains presentational. The same intent must be exposed as a named VoiceOver/TalkBack custom action and through equivalent keyboard/switch-control activation so long press is not the only accessible path.
- Operations that require forms, search, file picking, or comparison open a task-specific Sheet from the control menu. They do not create a parallel management navigation tree.
- Users without management permission retain the existing download affordances and cannot see mutation actions.

## Book control menu

The menu shows a compact work/selected-volume context header and these operations in this order:

1. **Add to Series** — opens a focused series-name and series-index editor for the work.
2. **Add to Shelf** — opens the existing shelf picker for the work.
3. **Mark as Unread** — sets the currently selected volume to `UNREAD`.
4. **Download** — controls the currently selected volume's managed download; its visible label may become Pause, Retry, or Remove Download as required by the real state.
5. **Edit** — opens the work-information editor.
6. **Recognize** — opens the existing provider search, comparison, and explicit field-application flow.
7. **Upload Cover** — opens the platform image picker for the work cover.
8. **Regenerate Cover** — requires confirmation before replacing the work cover.
9. **Send to Kindle** — sends an eligible EPUB/PDF file belonging to the currently selected volume.
`Mark as Unread`, `Download`, and `Send to Kindle` are disabled with a truthful reason when no volume is selected. Kindle is hidden when the selected volume has no eligible file. Administrative operations are hidden for actors without `canManageSystem`; shelf, reading-status, and download actions continue to follow their existing user permissions.

## Volume control menu

The menu is keyed by the long-pressed cover's `volumeId`, even when another volume was previously selected. It contains:

1. **Mark as Unread**.
2. **Download** — state-aware as above.
3. **Edit** — opens the volume-information editor.
4. **Change Media Type** — corrects content classification metadata without changing directory ownership.
5. **Send to Kindle** for an eligible file in this volume.

Active downloads continue to block change-media-type while the local artifact is being prepared.

## Book operation sheets

- Edit title, author, description, series, series index, and tags.
- Search configured metadata providers and apply explicitly selected candidate fields.
- Upload JPEG, PNG, or WebP covers, with a 10 MiB client boundary, or regenerate a cover.
- Choose an eligible EPUB/PDF file and enqueue Send to Kindle after validating Kindle/SMTP readiness.
- Set reading status.

## Per-volume operation sheets

- Edit publisher, language, ISBN, identifier, and narrator metadata.
- Correct one volume's content classification as e-book, comic, or audiobook without changing its directory-derived identity.
- Send an eligible EPUB/PDF file to Kindle.
- Start, pause, retry, or inspect its managed offline download.

Batch selection is intentionally Web-only in this phase.

## Mutation and offline invariants

1. Active (`queued` or `downloading`) transfers block content-classification correction. The user must pause or cancel first.
2. The server mutation completes before local state changes.
3. Content-classification correction changes metadata only; it never changes Work, Version, Volume, file ownership, or the local manifest.
4. A failed server mutation leaves local manifests and files unchanged.
5. Every successful mutation returns to Work Detail and triggers a fresh detail/volume request.

## Shared boundary

`shared/modules/workmanagement` owns typed request models, outcomes, error taxonomy, repository port, Ktor adapter, and the Swift-friendly context constructor. Platform UI does not construct URLs or parse API envelopes.

The following existing endpoints are used without contract changes:

- `/api/works/{workId}` and cover/metadata children
- `/api/works/{workId}/volumes/{volumeId}` and its metadata-only `reclassify` child
- `/api/kindle-settings` and `/api/kindle-send-tasks`
- `/api/reader/v4/volumes/{volumeId}/reading-status`

All user-visible copy is maintained in both `zh-CN`/Simplified Chinese and `en-US`/English catalogs.

## Acceptance

- An authorized user can complete every operation above from Work Detail on Android and iOS.
- A non-authorized user sees no mutation controls.
- An incompatible server causes no mutation call and shows an unsupported message.
- Work Detail exposes no Work, Version, or Volume merge, split, move, create, or delete control.
- Content-classification corrections preserve directory-derived identities and completed offline artifacts.
- Android and KMP compile/test gates pass; final runtime acceptance is performed on physical Android and iOS devices according to `AGENTS.md`.
