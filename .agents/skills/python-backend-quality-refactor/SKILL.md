---
name: python-backend-quality-refactor
description: Guide maintainable architecture and bounded refactors for the Shuku Starship Python 3.11 FastAPI backend under apps/api-python. Use when changing backend code organization, capability layering, typing and error boundaries, SQLAlchemy ORM persistence, or SQLite schema migrations while preserving established application contracts.
---

# Python Backend Quality Refactor

Follow the repository's [minimum-fix policy](../../../AGENTS.md) and [targeted verification policy](../../../docs/testing/test-execution-policy.md). When failure, cause and scope are clear, fix the existing owner directly; do not start an architecture migration merely because legacy code is touched. Use the refactoring steps below only for requested refactoring or structure changes necessary to fix the direct cause.
Preserve unrelated user changes in the worktree.

## Organize by Business Capability

- Prefer `app/modules/<capability>/` with `domain`, `application`, `infrastructure`, and `presentation` layers. Add directories only when they contain real code.
- Keep dependencies directed from presentation to application to domain. Infrastructure implements application ports and maps persistence or external-system data into explicit domain or application types.
- Put dependency construction and process lifecycle in composition roots. Do not hide dependency wiring in routes, models, or import-time side effects.
- Collaborate across capabilities through a named public API, stable contract, or application port. Do not deep-import another capability's private files or introduce circular/runtime imports.
- Do not create generic dumping grounds such as `utils`, `helpers`, `managers`, or a universal repository/service module. Shared code must have stable, business-neutral meaning and real consumers.

## Keep Responsibilities Explicit

- Domain code owns deterministic entities, value objects, invariants, policies, and state transitions without FastAPI, SQLAlchemy, filesystem, queue, or network dependencies.
- Application code owns named user intentions, authorization policy calls, orchestration, transaction boundaries, and side-effect ordering.
- FastAPI handlers validate transport input, acquire the actor and dependencies, invoke one application command or query, and map named outcomes to the established HTTP contract.
- Workers and CLIs call application use cases rather than route code. Keep polling, leases, retry decisions, shutdown, and containment at the process boundary.
- Use Python 3.11 typing throughout public boundaries. Prefer explicit dataclasses, value objects, DTOs, protocols, and Pydantic boundary models over `dict[str, Any]` or ORM-shaped data.
- Prefer pure functions for pure behavior and classes only for injected dependencies, lifecycle, or meaningful state. Avoid boolean mode flags that combine unrelated workflows.
- Translate errors only when adding context or mapping them to a named domain/application outcome, and preserve the original exception as the cause. Never expose secrets, internal paths, SQL details, or stack traces to clients.

## Use SQLAlchemy ORM and Typed Expressions

- New database capabilities use SQLAlchemy 2.x ORM models or typed expressions. A diagnosed legacy SQL defect may receive a necessary in-place correction under the [controlled exception](../../../docs/engineering-standards.md#数据库与受控遗留-sql); do not copy its pipeline, add generic raw-SQL tools, bypass parameter binding or relax authorization. Published migrations remain immutable.
- Define models with `Mapped[...]` and `mapped_column()`. Express reads with `select()`, relationships, loader options, `Session.scalars()`, and typed projections.
- Encapsulate persistence behind capability-specific repositories or query objects named after aggregates or use cases. Return domain objects or explicit DTOs; ORM entities must not escape into HTTP schemas or unrelated capabilities.
- Prevent N+1 access deliberately and give pagination a deterministic order and a documented maximum page size.
- Let repositories `flush()` when needed, but keep `commit()` and `rollback()` ownership in the application use case through an explicit unit-of-work boundary.
- Scope queries by the authenticated actor and preserve anti-enumeration behavior where forbidden and missing resources are intentionally indistinguishable.

## Evolve SQLite Safely

- Implement schema changes with SQLAlchemy schema objects and migration operations, including explicit tables, columns, indexes, constraints, foreign keys, and defaults.
- For SQLite table rebuilds, use supported batch/table-copy operations or SQLAlchemy schema APIs instead of manual DDL, `INSERT ... SELECT`, or PRAGMA strings.
- Keep migrations ordered, deterministic, restart-aware, and immutable after release. Do not import runtime application services into migration code.
- Separate expensive data backfills from schema changes. Use typed ORM or SQLAlchemy expressions, bounded batches, and explicit progress or recovery state.
- Discover the supported SQLite upgrade matrix from existing migration code, fixtures, release documentation, and deployed compatibility requirements before changing it.

## Refactor Legacy Code in a Bounded Slice

- Inventory the affected entry points, callers, contracts, state changes, authorization, persistence, and side effects before choosing a boundary.
- Extract pure rules and explicit types first, then introduce capability-specific ports and adapters, move orchestration into an application use case, and leave routes or workers as thin adapters.
- For a diagnosed legacy SQL defect, verify the corrected query output, necessary counterexamples and affected contract. Schedule ORM migration separately; it is not a prerequisite for completing a sufficiently verified local fix.
- Treat `app/api/routes/compat.py`, `app/worker/importer.py`, and `app/db/bootstrap.py` as legacy migration surfaces, not templates for new code. Preserve their mounted API paths, import recovery behavior, and supported database upgrade contracts without automatically moving touched responsibilities into new modules.
- Preserve API envelopes, authorization behavior, worker coordination, filesystem safety, user data, and `zh-CN`/`en-US` contracts unless the user explicitly requests a contract change.

Judge an improvement by clearer ownership, valid dependency direction, explicit types, and controlled persistence boundaries—not by file count or line count alone.


## Targeted Verification and Completion

Reuse existing tests and inspect command prerequisites before running them. Select the original failure, actual affected boundaries and necessary module checks; no new test tooling for each patch. Related small fixes can share one module validation, and unchanged code/dependency/configuration/environment evidence can be reused. Apply the linked verification policy's expansion triggers and stopping conditions; do not equate a local fix with final RC acceptance. Stop once the failure and key adjacent behavior are verified and no concrete related risk remains.
