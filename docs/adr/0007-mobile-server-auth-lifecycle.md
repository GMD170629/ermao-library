# ADR 0007: Mobile server and authentication lifecycle

- Status: Accepted
- Date: 2026-08-12

> The 30-day entitlement, entitlement repository, and restricted offline-shell decisions in items 4–8 are superseded for v1.0.0 by [ADR 0015](0015-mobile-v1-verified-session-without-offline-mode.md). Profile identity, switching, TLS, and Swift-boundary decisions remain active.

## Context

Stage 0 proved the KMP transport, native shells, compatibility handshake, profile-scoped
cookies, and the basic bootstrap gate. Stage 1 turns that skeleton into the product
closure defined by Mobile Phases 1–6: multiple saved servers, initial setup, login,
reauthentication, a 30-day offline entitlement, and explicit private-data lifecycle
transitions.

The Stage 0 implementation used `serverIdentity` as the local profile identifier and
allowed a single runtime object to own transport wires, server validation, profile
persistence, and authentication orchestration. Extending those choices would risk
cross-profile cookies and make the Swift/Android seams depend on transport details.

## Decision

1. A server profile has a locally generated stable `profileId`. `serverIdentity` remains
   the identity returned by the compatibility endpoint. They are never interchangeable.
2. Profile persistence uses a versioned aggregate containing `schemaVersion`,
   `activeProfileId`, and `profiles`. Stage 0 arrays migrate without changing their old
   IDs so existing encrypted cookies remain addressable.
3. Only one profile is active. Switching preflights the target through health,
   compatibility, setup status, and session verification before activation. A connection
   or compatibility failure preserves the old active profile and shell.
4. The KMP application facade depends on `ServerProbe`, `AuthGateway`, profile storage,
   entitlement storage, a clock, and an ID generator. Ktor and platform persistence are
   adapters wired only by composition roots.
5. Setup and login success never authorize the shell directly. A successful
   `GET /api/auth/me` is required and writes an entitlement bound to profile, server,
   user, and authorization version.
6. The offline entitlement expires exactly 30 days after validation. The exact expiry
   instant is invalid, persisted wall-clock rollback is treated as expiry, and local use
   never extends it. Logout, account disablement, profile deletion, or server identity
   mismatch revokes access.
7. A `401` hides the private shell and enters full-screen reauthentication. The same
   server/user/authorization namespace may restore the selected tab; a changed user,
   server, or authorization version resets all stacks to Home.
8. Stage 1 offline UI is a real restricted empty shell. It does not claim downloads,
   bookmarks, outbox, Reader, audio, or library data that are not implemented yet.
9. The Swift boundary exposes immutable snapshots and structured operation results. It
   does not expose Ktor, coroutines, exceptions, passwords, cookies, or localized backend
   messages.

## Consequences

- Existing Stage 0 profiles preserve their Cookie key during migration; newly added
  profiles receive UUID-v4 IDs.
- Saving the same `serverIdentity` twice is rejected with `SERVER_ALREADY_SAVED`.
- Editing a profile to a different server identity is rejected; the user must add the
  server as a new profile. Changing an origin/base path clears that profile's Cookie and
  requires authentication again.
- Restoring `systemTrust` is persisted immediately and never silently falls back to
  `insecureSkipAllValidation`.
- There is no synthetic switch/outbox coordinator before real Reader, download, audio,
  or outbox capabilities exist. Those capabilities must add their own public lifecycle
  ports and extend the switch acceptance matrix when implemented.
- Stage 1 cannot be declared complete until the same candidate revision passes KMP iOS,
  Xcode, XCTest, Simulator real-server smoke, and physical-iPhone acceptance. Linux and
  Android evidence may only establish conditional completion.
