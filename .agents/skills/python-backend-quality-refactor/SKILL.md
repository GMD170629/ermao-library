---
name: python-backend-quality-refactor
description: Audit, plan, implement, and verify code-quality refactors for the Shuku Starship Python 3.11 FastAPI backend under apps/api-python. Use when Codex is asked to reduce backend complexity or duplication, split large routes/services/workers, improve typing or error handling, introduce Python quality tooling, reorganize SQLite migrations, or review backend architecture while preserving API, worker, database, authorization, and zh-CN/en-US compatibility.
---

# Python Backend Quality Refactor

Refactor the backend in behavior-preserving increments. Treat API compatibility, SQLite data safety, worker behavior, authorization, and bilingual user-facing contracts as quality requirements rather than follow-up work.

## Start With Evidence

1. Read the repository `AGENTS.md`, `docs/business-code-layering-and-refactoring.md`, and the matching files under `.cursor/rules/` (especially `architecture.mdc`, `python-backend.mdc`, `python-orm-migrations.mdc`, `refactoring.mdc`).
2. Read `apps/api-python/pyproject.toml`, the affected modules, and their tests.
3. Run `python scripts/quality_snapshot.py` from this skill directory for a read-only hotspot snapshot.
4. Read [references/project-map.md](references/project-map.md) when choosing module boundaries.
5. Inspect `git status` without modifying or discarding unrelated work. If the intended hotspot overlaps existing user changes, inspect the diff and either work around it or choose another safe slice; do not overwrite, reformat, or absorb it silently.
6. State the intended behavior surface and expected adjacent variants before editing. Follow the repository's broad capability audit rule when the request reports a broken interaction.

Do not use line count alone to justify extraction. Identify business capability, dependencies, state ownership, transaction boundary, error contract, and tests first.

## Classify the Task

- For analysis or review, report evidence, risks, and a staged recommendation; do not edit application code.
- For tooling setup, add quality checks gradually and keep the existing test/runtime commands working.
- For a behavior-preserving refactor, add or strengthen characterization tests before moving logic.
- For a bug plus refactor, establish the failing behavior and adjacent capability variants, fix them, then improve structure without mixing unrelated redesign.
- For schema or data migration work, treat backup, repeat execution, upgrades from older versions, and partially migrated databases as explicit test cases.

## Establish the Baseline

Run the narrowest relevant tests first, then the broader gates. Record pre-existing failures separately from regressions. See [references/quality-gates.md](references/quality-gates.md) for commands and escalation rules.

For read-only audits, do not let a test command install or synchronize dependencies. Discover the existing environment first and use the no-sync form documented in the quality gates. If the environment is unavailable, report the command that would be run instead of mutating it.

Before changing public behavior, capture:

- route path, method, status, response envelope, field names, and error codes;
- authentication and authorization behavior for admin, scoped, ordinary, and anonymous users;
- transaction and filesystem side effects;
- worker retry, lease, shutdown, and recovery behavior;
- locale-sensitive or user-visible messages;
- database versions and upgrade paths affected.

Prefer API-level characterization tests for route extraction and focused unit tests for pure logic. Do not make snapshot tests so broad that intentional internal changes become impossible.

## Refactor in Safe Slices

Use one bounded capability per slice:

1. Define the target boundary and invariants.
2. Add characterization coverage for happy path, validation, authorization, not-found, conflict, and failure behavior as applicable.
3. Extract pure normalization, parsing, mapping, or policy logic first.
4. Move database access behind a clearly named query/repository function when it reduces duplication or clarifies transaction ownership.
5. Move orchestration into a service only when the service owns a coherent use case.
6. Keep FastAPI route functions responsible for HTTP translation and dependency acquisition.
7. Preserve commits/rollbacks and avoid hidden commits inside low-level helpers.
8. Run focused tests after each move; run broad gates after completing the slice.

Do not create generic `utils.py`, `helpers.py`, or a universal repository. Prefer domain names such as `works`, `monitor_folders`, `metadata`, `imports`, or `reader_progress`.

## Project-Specific Boundaries

- Split `app/api/routes/compat.py` by API capability while preserving the mounted paths and response envelope. Do not rename it away in one large change.
- Split `app/worker/importer.py` by pipeline stage: eligibility/identity, media parsing, conversion, persistence, cover handling, and event reporting. Keep import idempotency and recovery visible.
- Split `app/db/bootstrap.py` into ordered version migrations and post-migration backfills only with tests for fresh databases and supported upgrade paths.
- Discover the supported SQLite upgrade matrix from migration code, fixtures, tests, and release/migration documentation before editing migrations; do not invent or silently narrow it.
- Replace `dict[str, Any]` selectively at stable boundaries with Pydantic models, dataclasses, TypedDicts, or protocols. Do not type unstable database-shaped dictionaries merely to satisfy a checker.
- Narrow `except Exception` where recovery differs by failure type. Keep broad catches at worker/process containment boundaries when they record context and preserve liveness.
- Treat EPUB.js as immutable; backend reader work must not patch or vendor it.
- Preserve application-owned version consistency when release metadata is touched.

## Introduce Quality Tooling Gradually

Prefer Ruff for formatting and linting, a gradual mypy or Pyright configuration for stable modules, and pytest-cov for visibility. Introduce each as a separate, reviewable change:

1. Configure deterministic versions and commands.
2. Measure the existing baseline.
3. Fix high-signal violations in touched modules.
4. Use narrow, documented exclusions for legacy hotspots.
5. Add CI enforcement only after the repository passes the agreed baseline.

Never hide broad areas with blanket `noqa`, `type: ignore`, or disabled rule families. Every suppression must be local and explain why the checker cannot model the code safely.

## Verify and Report

Run all applicable gates from [references/quality-gates.md](references/quality-gates.md). For user-visible or generated messages, audit both locales and run the Web i18n check.

Report:

- the capability area and invariants preserved;
- files and boundaries changed;
- tests and gates run with results;
- remaining hotspots or deliberately deferred risks;
- any pre-existing failures that prevented a full green baseline.

Do not claim improved quality solely from smaller files. Tie the claim to reduced responsibility, clearer dependency direction, stronger typing at a boundary, fewer duplicated rules, or better executable coverage.
