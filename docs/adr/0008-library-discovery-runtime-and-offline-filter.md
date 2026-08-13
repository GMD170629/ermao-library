# ADR 0008: Library Discovery runtime and unavailable download filter

- Status: Accepted
- Date: 2026-08-12
- Owner: Mobile Library Discovery capability

## Context

Library discovery spans Works, Series, Authors, Search, Facets, filters, pagination, cached results, permission changes, and compact/expanded navigation. The first mobile implementation duplicated query identity, cache provenance, and persistence schemas in Swift and Android code. It also exposed a downloaded-only filter before a managed download manifest existed.

## Decision

KMP owns the stable Library Discovery state and route contracts, query identity, request generations, mutually exclusive content/refresh/pagination phases, cache serialization, staleness, and private namespace key. Platform code owns lifecycle-aware coroutines and native presentation only.

Persistent discovery pages cross the platform boundary as opaque strings through `LibrarySnapshotPayloadStore`. The namespace is `serverIdentity + userId + authzVersion`; each query keeps at most the most recent three pages and becomes stale after five minutes. Authorization changes therefore cannot read an older namespace. Logout, server removal, and explicit content invalidation clear the associated namespace.

Works is the only root scope with sort, grid/list, and filters. Series and Authors use the server's stable grouping order. Series facets use `series_index`; Author facets use `recent_read`.

`downloadedOnly` remains in the server-backed filter contract with a default of `false`, but production reports `OfflineFilterAvailability.Unavailable("MANAGED_DOWNLOADS_UNAVAILABLE")` and must reject an attempted `downloadedOnly=true` request. Cached metadata is never presented as proof that a work can be opened offline. ADR 0009 establishes the separate, local-manifest-backed Download Center as the downloaded-content discovery and search surface; Library must not expose this unavailable filter as a second entry point.

## Consequences

- A stale or offline response has one explicit provenance; protocol and authorization failures never fall back to private cached data.
- Search and pagination can reject obsolete or duplicate responses by stable request identity.
- Scope snapshots preserve independent query and scroll anchors.
- Platform UI remains responsible for native Search, Menu, Sheet, predictive back, focus restoration, and compact/expanded containers.
- The unavailable Library filter row may be hidden once the Download Center is available. It may become an interactive Library filter only after a separate product decision defines how the local manifest is joined into Library discovery; server capability alone is insufficient.
