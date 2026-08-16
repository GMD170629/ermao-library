# ADR 0015: Mobile v1 verified-session restoration without an offline mode

- Status: Accepted
- Date: 2026-08-15
- Owner: Mobile authentication and content capabilities
- Supersedes: ADR 0007 decisions 4–8 concerning the 30-day offline entitlement and restricted offline shell; ADR 0008 decisions concerning persistent Library Discovery snapshots and cache fallback

## Context

Mobile v1.0.0 needs a resilient normal App Shell, completed downloads, and local Reader data, but it does not need a separately named offline product mode. Network fluctuation must not switch navigation modes, extend authorization through a client-defined grace period, or make stale server pages look current. The first release is not yet in production, so development-only entitlement payloads do not require migration.

## Decision

1. A successful `GET /api/auth/me` writes a non-expiring `VerifiedSessionRecord` scoped to `profileId + serverIdentity`. It contains the last verified profile identity, authorization snapshot, and validation time.
2. On cold start, a matching record immediately publishes the ordinary `Authenticated` Shell. Compatibility and `/api/auth/me` validation continue in the startup operation after the Shell becomes observable.
3. Network, timeout, TLS, `5xx`, and response parsing failures preserve an already restored Shell. They do not create an offline state or a global blocking page.
4. Explicit `401`, `ACCOUNT_DISABLED`, or a compatibility response proving that `serverIdentity` changed clears the Cookie and verified-session record and leaves the private Shell.
5. First use without a matching verified record still requires successful online connection, login, and `/api/auth/me`. Server switching remains an online preflight operation and preserves the previous server when it fails.
6. Logout, server deletion, base-address changes, and restoring system TLS trust clear the affected verified-session record. Existing product rules continue to govern downloaded artifacts and other private local data.
7. Home, Library, Facet, and Work Detail do not persist GET page snapshots or fall back to old server responses. Failures render within the affected page. `ContentSource.Cache`, cached-content phases, banners, and platform restore APIs are removed.
8. Completed download manifests and files, authenticated cover/HTTP performance caches, Reader navigation/range/render caches, local progress, bookmarks, and Reader preferences remain. They do not authorize first use and do not synthesize server page data.
9. v1.0.0 has no network mode monitor, automatic mode switch, manual offline entry, outbox, or new background synchronization contract.

## Consequences

- `Authenticated` has one UI meaning regardless of whether its data was restored locally or freshly verified.
- Temporary server failures may leave displayed authorization controls based on the last successful `/me`; an explicit invalidation response ends that state.
- Users can keep reading a completed local artifact after a network send fails, while normal progress/bookmark synchronization remains best effort.
- A future independent offline mode or versioned GET-cache strategy requires a new product decision and ADR; `mobile-app-offline-strategy-options.md` is not an implementation contract for v1.0.0.

## Verification

- Shared runtime tests cover immediate restoration, refresh, transient failure retention, and explicit invalidation.
- Content tests assert that failed GET requests do not restore persistent snapshots.
- Android and iOS UI contracts contain no offline root route, grace-period control, or cached-server-data banner.
- Runtime acceptance must use physical Android and iOS devices under the repository policy.
