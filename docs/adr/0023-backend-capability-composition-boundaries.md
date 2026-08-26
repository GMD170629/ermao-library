# ADR 0023: Backend capability composition boundaries

- Status: Accepted
- Date: 2026-08-26

## Context

Backup, Library/Publications, Auth, System, and OPDS still share behavior through
private ORM modules, presentation helpers, and composition-root functions.  The
HTTP contracts are stable, but those imports make the same use case impossible
to reuse safely from HTTP, workers, and maintenance processes.

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
- Architecture tests detect new private imports and layer violations globally;
  the migration debt list is exact and shrinks to zero for P1-03/P1-04.
- External HTTP/OPDS contracts, SQLite schema, and backup format version remain
  unchanged by this refactor.
