# ADR 0010: Managed mobile downloads and reader access

- Status: Accepted
- Date: 2026-08-13
- Owner: Mobile Downloads capability

## Context

Mobile needs one reliable definition of downloaded content across EPUB-like publications,
PDF, and comics. Discovery metadata caches are not readable publications, the server has
no device download manifest, and `/api/download-tasks` represents server-side ingestion
rather than a user's private device transfers. Reader v4 already exposes the authoritative
reader type, content fingerprint, media file URL, and byte size. Media endpoints support
authenticated single-range responses.

## Decision

The device owns a managed-download manifest and content directory, isolated by
`serverIdentity + userId + authzVersion`. A publication identity additionally contains
`volumeId + contentFingerprint`. Only a response written to a temporary file, validated
against the declared byte count, and atomically published may become a completed artifact.
Partial, cancelled, stale-fingerprint, missing, or invalid files are never readable.

Reader access is decided from Reader v4 `readerType`, not a file extension or media-kind
guess:

- `reflowable` requires a matching completed local artifact before Reader entry;
- `pdf` and `comic` may stream while online and prefer a matching local artifact when one
  exists;
- offline access without a matching completed artifact is unavailable.

The Download Center is the sole downloaded-content discovery surface. It groups completed
artifacts by work and searches local title, author, and volume metadata. Active and failed
tasks remain separate groups. The existing Library `downloadedOnly` network filter remains
unavailable; it is not a second entry point and does not call `/api/works` to infer device
state.

KMP owns the task state machine, reader-access policy, bootstrap mapping, authenticated
chunked transfer contract, and catalog port. Android and iOS own private file storage,
atomic manifest persistence, native navigation, destructive confirmations, and platform
lifecycle coordination.

## Consequences

- The first foreground implementation can reuse existing Reader v4 and media endpoints;
  no backend manifest or new binary endpoint is required.
- Background continuation is not a release claim until Cookie, base-path, TLS, process
  death, and lock-screen behavior pass physical-device tests. A resource-bound short-lived
  download ticket is the fallback if platform background sessions cannot reuse auth safely.
- A weak HTTP ETag is not used as an `If-Range` validator. Resume support requires a tested
  Last-Modified or future strong checksum contract; restarting an interrupted foreground
  transfer is correct until then.
- Logout and namespace purge remove the manifest, partial files, and readable artifacts.
  Authorization revocation remains bounded by revalidation and the documented offline
  entitlement window because a server cannot recall an already stored device file.
