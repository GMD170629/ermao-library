# ADR 0015: Mobile v1 verified-session restoration without an offline mode

- Status: Accepted
- Date: 2026-08-15
- Updated: 2026-08-26
- Owner: Mobile authentication and content capabilities

## Context

Mobile v1.0.0 needs a resilient normal App Shell, completed downloads, and local
Reader data. It does not define a separately named offline product mode. Network
fluctuation must not switch navigation modes, extend authorization through a
client-defined grace period, or make an old server response look current.

The server session Cookie has its own server-defined lifetime (currently 30 days by
default). That Cookie lifetime is transport authentication, not a client-side
entitlement, grace window, remaining-days counter, or authorization to synthesize
server pages.

## Identity and persistence boundary

- `profileId` is the stable local identity of a saved server profile. It owns the
  Cookie slot, profile record, active-profile selection, and verified-session record.
- `serverIdentity` is the identity proved by the compatibility endpoint. It prevents
  one server from inheriting another server's private namespace when an address is
  reused or changed.
- Exactly one saved profile may be active. A new connection, edit, or switch must
  complete health, compatibility, setup, and session preflight before replacing the
  previous active private Shell. Failed preflight preserves the previous profile and
  navigation state.
- Shared KMP owns the session state machine and the `ServerProfileRepository`,
  `CookieVault`, and `VerifiedSessionRepository` ports. Android and Swift provide
  platform persistence adapters and observe flat snapshots; Swift must not recreate
  expiry, recovery, or invalidation policy outside Shared.

`VerifiedSessionRecord` is scoped by `profileId` and records the verified
`serverIdentity`, user identity, authorization snapshot and version, and
`lastValidatedAt`. It has no expiry or status field. It is evidence of a prior
successful `/api/auth/me`, not an independent authorization grant.

## Decision

1. A successful `GET /api/auth/me` atomically writes the current
   `VerifiedSessionRecord`. A matching saved profile and record may immediately
   publish the ordinary `Authenticated` Shell on cold start while compatibility and
   `/api/auth/me` validation continue.
2. Network unavailability, timeout, TLS failure, `5xx`, and response-parsing failure
   preserve an already restored Shell. They do not create an offline state, a global
   blocking page, or a second navigation tree.
3. Explicit `401`, `ACCOUNT_DISABLED`, or compatibility proof that the server identity
   changed clears the affected Cookie and verified-session record and removes the
   private Shell. First use without a matching record still requires online setup or
   login followed by successful `/api/auth/me`.
4. Logout, server deletion, base-address change, and restoring system TLS trust clear
   the affected verified-session record. Server switching remains an online preflight
   operation; failure leaves the previous active profile intact.
5. Home, Library, Facet, and Work Detail never persist GET response/page snapshots.
   An initial load or explicit refresh failure replaces only that page's result area
   with a network error. A next-page failure keeps pages already loaded during the
   current request generation and shows inline retry.
6. Library has no `downloaded-only` filter. Download Center is the only discovery
   entry for completed local downloads. There is no offline, cached-content, stale,
   or remaining-days route, state, banner, filter, or Shell.
7. Completed download manifests and files, authenticated cover performance cache,
   Reader navigation/range/render caches, local progress, bookmarks, and Reader
   preferences remain. They neither authorize first use nor reconstruct server GET
   pages. Permission revalidation must obscure private content that is no longer
   authorized.
8. v1.0.0 has no network mode monitor, automatic mode switch, manual offline entry,
   page-snapshot migration, outbox, or new background synchronization contract.

## Consequences

- `Authenticated` has one UI meaning whether its facts were restored locally or just
  verified online.
- Temporary server failure may leave authorization controls based on the last
  successful `/api/auth/me`; an explicit invalidation response ends that state.
- A completed local publication can remain readable when synchronization is
  unavailable, while progress and bookmark synchronization continue best effort.
- A future independent offline mode or versioned GET-page cache requires a new
  product decision and ADR.

## Verification

- Shared auth tests cover a non-expiring record, immediate cold-start restoration,
  Shell retention on transient network/TLS/`5xx` failures, and clearing on explicit
  `401`, account disablement, or server-identity change.
- Shared Library tests cover request-generation rejection, no initial-page fallback,
  next-page preservation, permission revalidation, and query identity without a
  download filter.
- Android and iOS tests cover local network errors, pagination retry, cover-cache
  namespace/LRU behavior, and deletion of the legacy page-cache directory.
- The Mobile offline-contract verification task rejects removed entitlement,
  page-snapshot, stale, and download-filter symbols and assets.
- Runtime acceptance uses physical Android and iOS devices under repository policy.
