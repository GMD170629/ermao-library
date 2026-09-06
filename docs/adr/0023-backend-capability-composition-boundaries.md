# ADR 0023: Backend capability composition boundaries

- Status: Accepted
- Date: 2026-08-26

## Context

The backend has independent capabilities for Library, Publications, Auth, System,
Backup and OPDS. Their application contracts must remain reusable from HTTP,
workers and maintenance processes without exposing ORM implementation details or
presentation helpers.

## Decision

Cross-capability collaboration uses immutable application DTOs and protocols
exported by the owning capability's `public.py`, or a deliberately shared
contract under `app/contracts`.  ORM models remain capability-private and are
never returned through these boundaries.

Publication source facts and Library navigation projections are separate ports.
Publications owns parsing and cache identity; Library owns readable-resource and
navigation projection persistence.  One Publications application unit of work
coordinates both adapters when atomic replacement is required.

Backup is allowed to enumerate the complete database schema only through an
injected schema-participation registry assembled in a composition root.  Backup
application plans contain validated scalar records, never SQLAlchemy statements
or mapped classes.

Bootstrap modules may import every layer only to construct dependencies, attach
routers, and own process lifecycle.  They may not contain authorization,
queries, mapping, persistence, or transaction behavior.

## Consequences

- Capability ORM changes require updating only the owning adapter and its
  contract tests.
- HTTP, worker, and CLI entry points invoke the same application use cases.
- Architecture tests detect new private imports and layer violations globally; a
  capability may expose only its stable public ports and contracts.
- External HTTP/OPDS contracts, SQLite schema, and backup format version remain
  unchanged by this refactor.
