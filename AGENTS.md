# Agent Working Guidelines

## Target-State Code Quality Standard

This section defines the required target architecture for the repository. It is not a description of the current code and existing legacy code is not a precedent for new work.

All new code must follow this standard. When changing legacy code, migrate the touched capability toward this target instead of extending the legacy pattern. Keep migrations behavior-preserving and bounded to the requested capability. If compliance would require a risky expansion of scope, stop and explain the conflict rather than adding more architectural debt.

The detailed rationale and staged migration plan live in `docs/business-code-layering-and-refactoring.md`. This file is the authoritative implementation policy when an agent writes or reviews code. Cursor project rules under `.cursor/rules/` distill the same policy into always-on and file-scoped agent constraints; prefer those rules for session context, and use this document plus the layering doc when fuller rationale or the staged migration plan is required.

### Architecture Model

Organize code by business capability first and by technical layer inside each capability.

The required dependency direction is:

```text
delivery/presentation -> application -> domain
infrastructure -> application ports and domain types
composition root -> all layers for dependency wiring only
```

The following dependencies are forbidden:

```text
domain -> framework, ORM, HTTP, filesystem, queue, environment, or third-party SDK
application -> FastAPI Request/Response, React, Next.js, SQLAlchemy implementation, or browser globals
infrastructure -> route, page, component, or presentation code
module/feature -> another module/feature's private files
database migration -> runtime application service
new module -> private helpers in a compatibility or legacy module
```

Cross-capability collaboration must use a named public API, an application port, or a stable contract. Never bypass a boundary with deep imports, circular imports, runtime import tricks, or a generic shared helper.

### Target Repository Layout

Create directories only when they contain real code. Do not create empty architecture scaffolding.

Python backend target:

```text
apps/api-python/
├── app/
│   ├── bootstrap/                    # composition roots and process lifecycle
│   ├── core/                         # small, stable cross-cutting primitives
│   ├── contracts/                    # stable cross-capability/API contracts
│   ├── modules/
│   │   └── <capability>/
│   │       ├── domain/
│   │       │   ├── entities.py
│   │       │   ├── value_objects.py
│   │       │   ├── policies.py
│   │       │   └── errors.py
│   │       ├── application/
│   │       │   ├── commands/
│   │       │   ├── queries/
│   │       │   ├── dto.py
│   │       │   └── ports.py
│   │       ├── infrastructure/
│   │       │   ├── persistence/
│   │       │   ├── files/
│   │       │   └── integrations/
│   │       ├── presentation/
│   │       │   ├── http.py
│   │       │   ├── schemas.py
│   │       │   └── mappers.py
│   │       └── public.py
│   ├── infrastructure/              # only genuinely cross-capability adapters
│   └── db/
│       ├── migrations/
│       └── runner.py
└── tests/
    ├── unit/modules/
    ├── integration/modules/
    ├── contract/api/
    └── migration/
```

TypeScript/Web target:

```text
apps/web/
├── app/                              # thin Next.js routes, layouts, metadata
├── features/
│   └── <capability>/
│       ├── api/
│       │   ├── client.ts
│       │   ├── schemas.ts
│       │   └── mappers.ts
│       ├── model/
│       │   ├── types.ts
│       │   ├── rules.ts
│       │   └── selectors.ts
│       ├── application/
│       │   ├── use-queries.ts
│       │   └── use-actions.ts
│       ├── ui/
│       └── public.ts
├── shared/
│   ├── api/
│   ├── i18n/
│   ├── lib/
│   └── ui/
├── generated/                        # generated contracts; never hand-edit
└── e2e/

packages/
├── reader-core/                      # framework-independent reader contracts/state
├── ui/                               # cross-application, business-neutral UI
└── shared/                           # stable contracts genuinely shared by apps
```

Do not add top-level dumping grounds such as `utils`, `helpers`, `managers`, or a universal `services` directory. Shared code must already have at least two real consumers and a stable, business-neutral meaning.

### Python Implementation Standard

#### Domain and application code

- Domain code contains entities, value objects, invariants, policies, and state transitions. It must be deterministic and testable without FastAPI, SQLAlchemy, SQLite, the filesystem, or network access.
- Application code implements named user intentions such as `ImportBook`, `MergeWorks`, or `SaveReaderProgress`. It owns orchestration, authorization policy calls, transaction boundaries, and side-effect ordering.
- Use immutable dataclasses or validated value objects for domain inputs and results. Use Pydantic models at external boundaries.
- Do not pass `Request`, `Response`, ORM models, database rows, or `dict[str, Any]` into domain code.
- Stable boundaries must not use `Any`. At genuinely dynamic external boundaries, accept `object`/unknown input, validate it, and map it immediately to an explicit type.
- Prefer pure functions for pure behavior. Use a class only when it owns injected dependencies, a lifecycle, or meaningful state.
- Avoid boolean mode flags that make one function perform unrelated workflows. Use separate named commands or strategies.
- Do not use mutable module-level business state. Process coordination belongs in an explicit runtime object or persistent store.

#### ORM-only persistence

All application database access must use SQLAlchemy ORM and typed SQLAlchemy expression APIs. Handwritten SQL is prohibited.

Forbidden everywhere in application and migration code:

- SQL strings, including dynamically composed or interpolated SQL;
- `sqlalchemy.text()`;
- `Session.execute()` or `Connection.execute()` with textual SQL;
- `exec_driver_sql()`;
- direct `sqlite3` access;
- raw cursor operations;
- string-based WHERE, JOIN, ORDER BY, column, or table fragments;
- copying existing raw-SQL helpers into new modules;
- using raw SQL as a shortcut for a missing ORM relationship or query model.

Required persistence approach:

- Define tables and relationships with SQLAlchemy 2.x declarative mapped models using `Mapped[...]` and `mapped_column()`.
- Express reads with `select()`, relationships, loader options, `Session.scalars()`, and typed projections.
- Express writes through mapped entities or SQLAlchemy `insert()`, `update()`, and `delete()` expression objects when set-based operations are genuinely required.
- Encapsulate persistence behind capability-specific repositories or query objects. Name them after an aggregate or use case, not a database table collection.
- Return domain objects or explicit DTOs. ORM entities must not escape into HTTP schemas, React contracts, or unrelated capabilities.
- Prevent N+1 behavior intentionally with explicit loading strategies. Do not solve it by returning unbounded object graphs.
- Pagination must have a deterministic order and a documented maximum page size.
- Low-level repositories may `flush()` but must not hide `commit()` or `rollback()`. The application use case owns the transaction.
- Use `with session.begin():` or an equivalent explicit unit-of-work boundary for writes.
- Do not catch integrity errors and treat them as normal control flow unless they are translated into a named domain/application conflict with the original exception preserved.

Legacy raw SQL is migration debt, not an accepted style. When touching a raw-SQL behavior, add characterization coverage and migrate the affected query to ORM within the same bounded capability. If that is unsafe within scope, do not add or modify raw SQL without explicit user direction.

#### Schema migrations

- Migrations must use SQLAlchemy schema objects and migration operations, not handwritten SQL strings.
- Model every schema object explicitly: tables, columns, indexes, foreign keys, unique constraints, and defaults.
- For SQLite table rebuilds, use a migration framework's batch/table-copy operations or SQLAlchemy schema APIs; do not write manual `CREATE TABLE`, `ALTER TABLE`, `INSERT ... SELECT`, or PRAGMA strings.
- Each migration is ordered, deterministic, restart-aware, and immutable after release.
- Separate schema change from expensive data backfill. Backfills use typed ORM models or SQLAlchemy expression objects and support bounded batches and restart.
- Test fresh database creation, every supported upgrade path, repeat invocation, partial completion, and failure recovery.
- Runtime services must never be imported by a migration. Migration-local data transformations must be stable and self-contained.

#### FastAPI delivery

Route handlers are thin adapters. They may:

1. parse and validate transport input;
2. acquire the authenticated actor and injected dependencies;
3. invoke one application command or query;
4. map the result or a named error to the established HTTP contract.

Route handlers must not contain ORM queries, business decisions, filesystem operations, media parsing, queue coordination, or multi-service workflow logic.

- Use explicit Pydantic request and response models for every JSON endpoint.
- Do not return arbitrary dictionaries for stable endpoints.
- Keep path, method, status, error code, response envelope, and authorization behavior backward-compatible unless the user explicitly requests a contract change.
- Program logic branches on stable error codes/types, never on localized message strings.
- Validate resource-level authorization inside the use case even when middleware also protects a route prefix.

#### Workers and integrations

- API routes, workers, schedulers, and CLIs call the same application use cases. They must not call each other's presentation code.
- Worker boundaries own polling, leases, retry/backoff, shutdown, task acknowledgement, and final containment logging.
- Broad `except Exception` is allowed only at a process/task containment boundary that records context and makes an explicit retry, quarantine, or terminal decision.
- External systems, converters, filesystem access, clocks, random IDs, and third-party SDKs are adapters behind application ports.
- Filesystem publication uses a temporary path, validation, and atomic replace where supported. Cross-database/filesystem workflows require an explicit recoverable intermediate state and idempotency key.

#### Python style and maintainability

- Target Python 3.11 and use modern type syntax.
- All public functions, methods, and class attributes are fully typed.
- Use domain-specific names. Avoid abbreviations, vague names such as `data`, `item`, `manager`, and misleading technical names for business concepts.
- A function has one level of abstraction and one reason to change. Extract a named policy or use case when branching represents business variants.
- Prefer early validation and guard clauses over deeply nested control flow.
- Never use mutable default arguments, wildcard imports, hidden monkey patches, or import-time I/O.
- Do not suppress type or lint errors globally. A local suppression requires a comment explaining why the tool cannot model safe code.

### TypeScript and React Implementation Standard

#### Types and contracts

- TypeScript remains in strict mode. Do not weaken compiler options.
- `any`, broad type assertions, non-null assertions, `@ts-ignore`, and unchecked JSON casts are prohibited in business code.
- Treat all network, storage, URL, postMessage, and browser persistence input as `unknown`; validate it at the boundary before mapping it into domain types.
- Generate stable API wire types from OpenAPI where available. Generated files are read-only.
- Keep API DTOs, domain models, view models, and editable form state distinct. Do not reuse one oversized type across all layers.
- Use discriminated unions for state machines and operation results. Model impossible states out instead of coordinating unrelated booleans.

#### API access

- Direct `fetch()` is allowed only inside `shared/api` transport and feature `api/client.ts` adapters.
- Components, pages, providers, reducers, and model code must never call `fetch()` directly.
- The shared transport owns base-path handling, credentials, request cancellation, content type, envelope decoding, session-expiry signaling, and normalized transport errors.
- Feature API adapters own endpoint-specific runtime validation and mapping from wire DTOs to feature models.
- UI code handles named application outcomes, not raw status numbers or localized backend messages.
- Every async effect supports cancellation or stale-result rejection where the initiating view can change or unmount.

#### Features, state, and React

- `app` route files are composition points, not business modules.
- Feature `model` code is framework-independent and contains pure rules, reducers, selectors, and types.
- Feature `application` code coordinates API calls, mutations, server state, optimistic behavior, and use-case hooks.
- Feature `ui` renders models and emits user intentions. It does not parse envelopes or implement persistence rules.
- A feature's internal files may only be imported through its `public.ts` from outside that feature.
- Shared UI is business-neutral, accessible, and does not import features.
- Keep one owner for each state: URL for shareable navigation state, server cache/application layer for server facts, local component for transient visual state, and an explicit store/runtime for cross-page sessions.
- Do not mirror props or server state into local state through effects unless an external synchronization contract requires it.
- `useEffect` is for synchronizing external systems, not for computing derived state or chaining internal business transitions.
- All hook dependencies are correct. Never silence `react-hooks/exhaustive-deps` to force desired timing.
- Prefer reducers or explicit state machines for workflows with multiple phases, cancellation, retries, or concurrent events.
- Components must preserve keyboard, pointer, touch, focus, reduced-motion, and screen-reader behavior where applicable.

#### TypeScript style and maintainability

- Use named exports for feature/public modules unless a framework requires a default export.
- Prefer small cohesive modules, but do not create pass-through files or prop-forwarding components solely to reduce line count.
- Business rules must be named pure functions, not dense inline JSX expressions.
- Avoid boolean prop proliferation. Prefer variants, composition, or explicit state objects.
- Do not access `window`, `document`, storage, or browser APIs from pure model code.
- Timers, subscriptions, observers, object URLs, and event listeners must have explicit cleanup and ownership.
- Memoization is a measured optimization, not a default. Correct state ownership comes before `useMemo`/`useCallback`.

### Cross-Cutting Quality Rules

#### Transactions and side effects

Every write use case must document and test:

1. validation and authorization;
2. current-state read;
3. domain decision;
4. database/file temporary writes;
5. transaction commit;
6. event, queue, or file publication;
7. compensation, retry, or recoverable failure state.

Hidden commits, fire-and-forget promises, and untracked background tasks are prohibited.

#### Error handling

- Define a small, capability-specific error taxonomy.
- Preserve the original exception as the cause when translating infrastructure failures.
- Never expose secrets, credentials, internal paths, SQL details, or stack traces in user-facing errors.
- Do not catch an exception unless the code can add context, translate it, compensate, retry, or contain a process boundary.
- Empty catch blocks and fallback-to-success behavior are prohibited.

#### Security and authorization

- Validate and normalize all external input at the boundary.
- Scope database queries by the authenticated actor; do not load all rows and filter them in memory.
- Preserve anti-enumeration behavior where not-found and forbidden responses are intentionally indistinguishable.
- Never trust client-provided ownership, role, path, MIME type, filename, or content length.
- Filesystem paths must be resolved against configured roots and checked for traversal and symlink escape.
- Secrets never appear in source, logs, fixtures, snapshots, generated artifacts, or error responses.

#### Internationalization

- User-visible text is never used as a programmatic identifier.
- Application error codes and event types are locale-neutral.
- Dates, times, numbers, percentages, and relative time use the active locale.
- User-provided titles, authors, tags, series names, paths, and filenames remain unchanged.
- Every user-visible feature is complete for `zh-CN` and `en-US`, including non-DOM surfaces.

#### Observability

- Emit structured logs/events at process and use-case boundaries with stable event names.
- Include correlation identifiers, actor/tenant scope where safe, target identifiers, stage, and outcome.
- Do not log entire request bodies, book contents, tokens, cookies, passwords, or provider credentials.
- Metrics and logs must distinguish validation failures, authorization failures, conflicts, infrastructure failures, retries, and terminal failures.

### Testing Standard

Tests follow the same capability layout as production code.

- Domain unit tests cover invariants, boundaries, and state transitions without framework or database setup.
- Application tests use fakes for ports and verify orchestration, authorization, transaction outcome, and side-effect ordering.
- Repository integration tests use real SQLite and SQLAlchemy ORM, including constraints, relationships, pagination, eager loading, and rollback behavior.
- API contract tests verify method, path, status, envelope, field names, error codes, and authorization roles.
- Migration tests cover fresh creation and every supported upgrade path.
- Worker tests cover idempotency, retry, lease expiry, shutdown, abandoned work, and recovery.
- Web model tests cover pure rules and reducers; component tests cover interaction and accessibility; E2E covers only critical cross-layer journeys.
- Every defect fix starts with a failing regression test and audits adjacent behavior variants under the functional triage rule below.
- Tests assert observable behavior, not private implementation details. Mock only owned ports, not every internal function.
- Time, randomness, filesystem roots, and external services must be controllable in tests.

No change is complete with newly skipped, flaky, or silently weakened tests.

### Quality Gates

The target CI pipeline must enforce:

```bash
# Python
ruff format --check .
ruff check .
mypy app
pytest --cov=app --cov-report=term-missing

# Web
pnpm lint
pnpm typecheck
pnpm test
pnpm i18n:check
```

Also run capability-appropriate migration, runtime smoke, Playwright, PWA, and worker checks.

Quality requirements:

- Do not lower strictness, coverage thresholds, or rule sets to make a change pass.
- Do not add blanket exclusions, broad `noqa`, `type: ignore`, ESLint disable blocks, or test skips.
- Coverage is a risk signal, not a substitute for boundary and failure-path tests.
- A large module is a review trigger, not automatically a defect. Refactor when responsibilities, dependency direction, state ownership, or testability are unclear.
- New warnings are failures. Pre-existing warnings in touched code must be resolved unless doing so would materially expand scope.

### Refactoring Standard

Refactor one named capability at a time:

1. inventory entry points, callers, roles, contracts, state changes, and side effects;
2. add characterization tests for current public behavior;
3. extract pure rules and explicit types;
4. replace raw SQL in the touched capability with ORM models and typed queries;
5. introduce capability-specific ports and adapters;
6. move orchestration and transaction ownership into an application use case;
7. make routes, workers, and UI thin adapters;
8. remove the legacy implementation after callers switch;
9. run focused and broad gates;
10. record an ADR for durable cross-capability decisions.

Do not combine architecture migration, product redesign, dependency upgrades, broad formatting, and unrelated cleanup in one change.

Temporary compatibility code must have a named owner, protective tests, and an explicit removal condition. “Clean up later” is not an acceptable exit plan.

### Definition of Done

A change is complete only when:

- the business capability and invariants are explicit;
- code resides in the target capability and layer;
- dependency direction is valid and no private cross-feature import was added;
- all database access uses SQLAlchemy ORM or typed expression APIs with no handwritten SQL;
- transaction ownership and failure recovery are explicit;
- HTTP, worker, database, filesystem, authorization, and locale contracts remain compatible unless intentionally changed;
- stable boundaries use explicit validated types;
- both `zh-CN` and `en-US` are complete;
- focused tests and all applicable quality gates pass;
- no duplicate implementation, unexplained compatibility shim, warning, or unowned follow-up remains.

## Functional Bug Triage

When the user reports that a feature does not work, do not treat the named action as an isolated checklist item. Treat it as an example of a broader capability area and audit the adjacent behaviors that a user would naturally expect.

For every reported broken interaction:

1. Identify the underlying user intent and feature surface.
2. List the expected interaction variants for that surface.
3. Check which variants are already implemented, partially implemented, or missing.
4. Fix the reported issue and any closely related missing behaviors unless the scope would become risky or unrelated.
5. In the final response, name the broader capability area that was checked, not only the literal symptom.

Example: if the user says EPUB left/right page turning and swipe page turning do not work, expand the investigation to the full reader navigation surface:

- Keyboard shortcuts: left/right arrows, space/page keys where appropriate, and escape for dismissing overlays if the UI supports it.
- Pointer navigation: left/right page zones, center tap to show or hide controls, toolbar buttons, progress slider, and table-of-contents jumps.
- Touch navigation: horizontal swipe, tap zones, scroll behavior in scrolled mode, and PWA standalone behavior.
- Focus boundaries: whether events are captured by iframes, overlays, controls, or embedded reader content.
- State recovery: whether hidden controls can always be shown again after immersive mode.
- Reader parity: whether EPUB, comic, PDF, and text readers offer comparable navigation affordances where the format allows.

Use this same "reported symptom -> expected capability set -> implementation audit" pattern for other feature areas such as upload/import, search/filtering, library organization, settings, progress sync, offline/PWA behavior, and mobile layouts.

## Internationalization Completeness

The application has complete internationalization support for `zh-CN` and `en-US`. Treat English adaptation as part of the definition of done for every new feature and user-visible change.

For every implementation:

1. Audit all user-visible text, including headings, buttons, form labels, placeholders, validation messages, empty states, errors, toasts, confirmation dialogs, accessibility labels, page metadata, PWA content, emails, downloaded/generated documents, and backend-generated status messages.
2. Use the shared Web i18n APIs in `apps/web/i18n` instead of shipping untranslated UI literals. Add both the Chinese source message and a deliberate English translation to the locale catalogs.
3. Preserve interpolation placeholders exactly across locales. Dynamic values such as book titles, authors, tags, series names, shelf names, file paths, and other user-provided content must remain unchanged and must not be treated as translatable application copy.
4. Use the active locale for dates, times, numbers, percentages, and relative-time formatting. Do not introduce hard-coded `zh-CN` formatting in user-facing features.
5. Keep backend and non-DOM surfaces in scope. When a feature adds API errors, system events, email content, PWA metadata, service-worker responses, or generated files, provide an English-compatible message contract or localized output as appropriate.
6. Update or add tests for both locales when behavior, metadata, interpolation, or generated content changes.
7. Run `pnpm i18n:check` from `apps/web` before considering the work complete. Do not ship with missing catalog entries, Chinese text remaining in the English catalog, stale keys, or mismatched placeholders.

## Mobile App Functional Baseline

### Mobile Reader architecture

`docs/mobile-reader-architecture.md` is the authoritative native Mobile Reader architecture and phase contract. Read it before designing or changing Reader domain models, location/progress persistence, publication storage, native Reader navigation or UI, Readium/libmobi/PDF/Comic engine adapters, or Reader server synchronization. It fixes the reading-morphology boundaries, dependency direction, shared JSON schema, fingerprint and restoration policy, native UI boundary, security rules, Android R2 opening chain, and the interfaces reserved for later phases. It does not override the Mobile phase 1–5 product, navigation, flow, visual, localization, accessibility, or platform-native requirements.

Reader code must preserve the original publication format. It must not create,
cache, advertise, download, or restore from a derived EPUB, ZIP, unpacked
publication directory, or equivalent format-conversion artifact. MOBI-family and
TXT support must use their parser-backed in-memory Publication directly. The
existing dormant import conversion subsystem is not a Reader fallback and must
not be connected to Reader bootstrap, delivery, download, cache, or progress.

### Android Physical-Device-Default Development

Android local development, debugging, test APK installation, instrumentation, visual
inspection, screenshots, performance work, and runtime acceptance default to a connected
physical Android device. Do not automatically start or select an AVD while a physical device
is available.

- Before every install or test, run `adb devices -l`, require the target to be in `device`
  state, and address an exact serial that does not start with `emulator-`. If more than one
  physical device is connected, do not select the first device implicitly.
- After every successful test APK build, use a data-preserving replace-install on the exact
  physical serial, then force-stop and cold-launch the app. Verify the package and version,
  resumed activity, and post-launch crash/ANR logs. Never uninstall the app or clear its data
  as part of normal deployment.
- Run final Compose UI/instrumentation, TalkBack, keyboard, rotation, split-screen,
  predictive-back, real-network/storage, process-death/recovery, screenshot, and core-journey
  checks on the physical device. A compile-only or emulator-only result is not runtime
  acceptance.
- Android Emulator is allowed only when explicitly requested for a supplementary device/API
  matrix or when hardware cannot be attached to CI. Emulator evidence never replaces the
  physical-device installation and final runtime/visual gate.
- If no suitable authorized, unlocked ADB device is available, stop the Android runtime gate
  and report that physical-device evidence is pending. Do not silently fall back to an
  emulator or weaken the gate. Existing conflicting local guidance is migration debt and this
  policy takes precedence.

### iOS Physical-Device-Only Development

iOS development, debugging, testing, visual inspection, screenshots, performance work,
and acceptance must use a connected physical iPhone or iPad. iOS Simulator is prohibited.

- Do not start, create, boot, or target an iOS Simulator. Do not use `simctl`, an
  `iphonesimulator` destination or SDK, `iosSimulatorArm64`, `iosX64`, or simulator-backed
  SwiftUI Preview execution as development or test evidence.
- Build KMP Apple code for `iosArm64` and build Xcode targets for `iphoneos`. Select the
  physical device by the identifier reported by `xcodebuild -showdestinations`; never use
  a generic or named Simulator destination and never disable signing to bypass a device build.
- Before every run or test, verify that the device is connected and paired, Developer Mode
  is enabled, the device is unlocked or otherwise available to Xcode, automatic signing has
  a valid Team, and the device can reach the intended test server without using `localhost`.
- Run XCTest, UI tests, Keychain/TLS/network/process-death checks, accessibility checks,
  screenshots, and runtime smoke journeys on the physical device. A device-target compile
  without installation is not runtime acceptance.
- If no suitable physical iOS device is available, stop the iOS runtime gate and report it as
  awaiting physical-device evidence. Never fall back to Simulator, weaken the gate, or claim
  acceptance from compilation alone.
- New scripts, CI jobs, documentation, and acceptance records must not introduce Simulator
  commands or Simulator-based evidence. Existing conflicting instructions are migration debt
  and this physical-device-only policy takes precedence.

`docs/mobile-app-phase-1-web-to-app-functional-baseline.md` is the authoritative functional baseline for rebuilding `apps/mobile` from scratch. Read and apply it before designing or implementing any Mobile page, flow, navigation model, API adapter, permission rule, reader, player, download behavior, cache, or synchronization feature.

`docs/mobile-app-phase-2-information-architecture.md` is the authoritative Mobile page-tree, hierarchy, navigation, deep-link, state-restoration, and Sheet/Menu/Dialog policy. Read it after the Phase 1 baseline and before creating Mobile routes, navigation state, page layouts, or modal interactions. The Phase 1 baseline owns functional scope, API, data, and permission truth; the Phase 2 specification owns where supported capabilities live and how users move between them.

`docs/mobile-app-phase-3-user-flows-and-wireframes.md` is the authoritative Mobile low-fidelity task-flow and wireframe-composition baseline. Read it after Phase 2 and before producing visual directions, high-fidelity screens, prototypes, or root-page implementations. It fixes the critical user flows, the eight visual anchor screens, content order, action priority, cross-screen state placement, and compact/expanded wireframe acceptance criteria; it intentionally does not define final brand styling.

`docs/mobile-app-phase-4-visual-master.md` is the authoritative Mobile visual specification v1. Direction A, “Warm Page,” is selected. Read it after Phase 3 and apply its exact semantic color mappings, 8pt spacing scale, cover contract, typography hierarchy, progress styles, icon policy, native-component boundary, and motion rules to every high-fidelity screen, prototype, shared component, theme, and visible state. The saved reference image is visual evidence only: it is not a numeric token source and must not add routes, features, or priorities that conflict with Phases 1–3.

`docs/assets/mobile-app-hifi-v1/` is the authoritative source for the current Mobile high-fidelity design artifacts. Before designing or implementing a visible Mobile surface, inspect the relevant PNGs in this directory together with their Phase 5–7 specification. Do not require or treat Figma as a source of truth for this project; if an external design file conflicts with these checked-in artifacts, the checked-in artifacts and repository specifications prevail. The PNGs govern page composition, density, content priority, and App-owned visual treatment only; Phases 1–4 and the global development guidelines remain authoritative for functionality, navigation, semantic tokens, accessibility, native controls, and platform behavior.

`docs/mobile-app-phase-5-high-fidelity-anchors.md` records the authoritative page-level composition anchors after Phase 4. Read it when designing or implementing Home, Library, Work Detail, or any later screen that must inherit their density and visual language. Its PNG assets freeze composition evidence only: they never override the functional, navigation, task-flow, token, accessibility, or native-component rules in Phases 1–4, and implementation must not sample colors or redraw system components from the images.

`docs/mobile-app-phase-6-server-auth-high-fidelity.md` records the authoritative high-fidelity composition baseline for the Mobile bootstrap, server connection, TLS risk, Login, Setup, and Reauthenticate flow. Read it after Phase 5 before designing or implementing BootstrapGate, ServerProfile forms, authentication gates, or offline-grace entry. It freezes page hierarchy and copy placement only; Phases 1–4 remain authoritative for API behavior, navigation, security, entitlement, native controls, localization, and accessibility.

`docs/mobile-app-phase-7-library-discovery-high-fidelity.md` records the authoritative high-fidelity composition and state-restoration baseline for Mobile Library search, series/author grouping, shared Facet pages, return context, Filter Sheet, sort/view Menu, empty and offline cached results, pagination/request failures, permission revalidation, and stale background refresh. Read it after Phase 5 before designing or implementing `library.search`, series/author scopes, `works.facet`, Library overlays, or their transitions to and from Work Detail. Its PNGs freeze compact composition evidence; Phases 1–4 remain authoritative for API, pagination, navigation identity, permissions, localization, accessibility, native controls, and expanded layout.

`docs/mobile-app-development-global-guidelines.md` is the authoritative cross-cutting implementation policy for preserving native iOS/Android behavior while matching the Mobile visual system. Read it after the applicable Phase 1–5 documents and before selecting UI technology, defining shared controls, implementing any visible Mobile surface, or writing visual tests. It owns the A/System-owned, B/Native-themed, C/App-owned, and D/Approved-motion classification; the native-container-plus-branded-content pattern; semantic adapter limits; platform-specific fidelity rules; visual-regression strategy; and exception process. It does not override the product or visual intent defined by Phases 1–5.

- Treat the baseline as a product and contract constraint, not as a request to copy the responsive Web UI.
- Every Mobile surface must map to a baseline decision level, a named user task, real API methods and paths, authorization and resource-scope rules, complete data states, and an appropriate iOS/Android interaction form.
- The P0 information architecture is `Home / Library / Shelves / Me`; search is a native search flow, readers are full-screen stacks, and audio uses a persistent mini player plus Now Playing.
- Each of the four destinations owns an independent navigation stack. Shared work details, Reader, and Now Playing must not be duplicated by source Tab. Mobile routes, typed navigation intents, back behavior, compact/expanded adaptation, and modal ownership must follow the Phase 2 specification.
- P0 supports multiple saved server profiles with one active server. Private data and navigation state must not cross server/user/authorization namespaces, and inactive servers must not play, download, or synchronize.
- The accepted offline policy permits downloaded-content access for 30 days after the last successful `/api/auth/me` response after a `401`, without an extra device unlock. Explicit logout ends the entitlement immediately. Implement this as an explicit entitlement state, not as an inference from cached files.
- TLS defaults to system trust. The explicitly accepted `insecureSkipAllValidation` exception is per server profile, requires the Phase 2 risk disclosure and confirmation, and must never become a global or implicit default.
- Visual and prototype work must begin from the eight Phase 3 anchors: Server Center, Home, Library, Shelves, Work Detail, Reader, Now Playing, and Download Center. Do not select isolated attractive screens or introduce final styling before the connected flows and required states are represented.
- The selected visual system is Phase 4 Direction A, “Warm Page,” specification v1. Paper character must come from warm backgrounds, Chinese typography, covers, content rhythm, and spacing—not faux-paper cards, texture noise, decorative gradients, or repeated elevated surfaces. Preserve the two-tier coral model, system-derived App Dark, Reader Paper/Night, and readable Chinese text. Do not drift into Direction B dark-editorial or Direction C gallery-grid styling unless the product decision is explicitly revised.
- Keep business visuals consistent, but let iOS/Android own general navigation, controls, gestures, feedback, and system motion. Do not create a general-purpose Mobile animation system; only the Phase 4 Reader and progress motions are custom product behavior.
- Classify every visible Mobile component as A/System-owned, B/Native-themed, C/App-owned, or D/Approved-motion before implementation. App-owned regions must closely match semantic tokens and high-fidelity anchors; system-owned and native-themed regions use separate iOS/Android references and must not be judged by cross-platform pixel equality.
- Use native containers with branded content. The platform owns navigation, Tab, Sheet/Menu/Dialog shells, Picker, system permissions, back behavior, control physics, focus, and system motion; the App owns content hierarchy, semantic color, typography, spacing, Cover, business Progress, and state presentation inside those containers.
- Shared Mobile UI adapters expose task semantics, roles, values, content, and accessibility information only. Do not expose or emulate platform-owned geometry or motion such as Sheet corner radius, Slider thumb shape, back animation duration, or system dialog elevation.
- Mobile uses Reader v4 and the ADR 0020 `Book / ReadableResource / ResourceAsset` identity only. Reader ownership is `resourceId`; media and audio ownership use `assetId`. Work/Version/Volume/File, Reader v1–v3, edition APIs, external-source tombstones, OPDS, Web PWA update behavior, and placeholder notes are not Mobile product contracts.
- System administration, server filesystem management, organization/metadata governance, backups, queue operations, and logs remain Web-only unless the baseline is deliberately revised.
- Do not add Mobile functionality that depends only on a visible Web menu or button. The backend contract, `GET /api/auth/me` authorization context, resource-scope enforcement, offline namespace, and failure semantics must all support it first.
- A deviation requires an explicit product decision and must document API, authorization, offline, migration, compatibility, native-behavior, accessibility, platform-upgrade, testing, and removal/review consequences.

## EPUB.js Dependency Boundary

Treat EPUB.js as an immutable third-party dependency:

1. Use the latest official npm release without modifying its source files.
2. Never edit files under `node_modules/epubjs`, vendor modified EPUB.js source, or add a package patch that changes EPUB.js behavior.
3. Do not attribute a reader defect to EPUB.js unless a matching upstream GitHub issue, discussion, fix commit, or release note provides concrete evidence. Without that evidence, treat the defect as an application integration, configuration, lifecycle, or API-usage problem.
4. Fix EPUB reader behavior only through EPUB.js public APIs and this repository's own adapter, controller, presentation, and input code.

## Release Version Consistency

Treat a release as a coordinated application-version update, not only a GitHub tag or GitHub Release operation.

For every versioned release:

1. Choose one semantic version and use it consistently for the GitHub tag, release title, Docker/package artifacts, the Web application, and the backend application.
2. Before creating the release tag, update every application-owned version source, including at least:
   - the root `package.json` version, which is the canonical release version and is displayed by the Web “About” page;
   - `apps/web/package.json`;
   - `apps/api-python/pyproject.toml`;
   - the backend runtime default in `apps/api-python/app/core/config.py`;
   - generated lockfiles such as `pnpm-lock.yaml` and `apps/api-python/uv.lock` when their package-version metadata changes.
3. Verify that the system Web “About” page displays the new version and that backend version responses/runtime metadata report the same version.
4. Verify that the GitHub tag is exactly `v<version>` and matches the root `package.json` version before publishing. Do not publish when any application, page, runtime metadata, lockfile, tag, or artifact still reports the previous or a conflicting version.
5. Fill in the GitHub Release description before publishing. Write a few concise sentences that summarize the release's most important fixes, improvements, and user-visible feature changes; do not publish a release with an empty description or only an auto-generated change list.
6. Include version-consistency checks in the release validation or workflow whenever practical, so a mismatched Web, backend, package, artifact, or GitHub release version fails before publication.
