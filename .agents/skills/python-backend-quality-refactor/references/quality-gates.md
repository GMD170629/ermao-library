# Quality Gates

Run commands from the repository root unless a command explicitly changes directory. Prefer the WSL/Linux environment used by the project when the host shell cannot execute POSIX scripts.

## Read-Only Environment Check

`uv run --extra dev` may synchronize the environment. During analysis-only work, first check whether the existing environment is usable:

```bash
cd apps/api-python
uv run --no-sync pytest --version
```

If it succeeds, add `--no-sync` to audit-only pytest commands. If it fails, do not sync or install unless the user authorized environment changes; report the unavailable gate. During implementation work, the repository's normal `uv run --extra dev` commands are permitted when dependency synchronization is a routine step within the requested change.

## Fast Feedback

Run the affected file or behavior first:

```bash
cd apps/api-python
uv run --extra dev pytest -q tests/test_relevant_area.py
```

Use a focused `-k` expression when a test module is still too broad.

## Backend Regression

```bash
cd apps/api-python
uv run --extra dev pytest -q
```

## Migration and Runtime Compatibility

```bash
pnpm verify:python-backend
pnpm smoke:python-api
pnpm smoke:python-worker
pnpm smoke:python-worker-import
pnpm smoke:python-sample
```

Run expensive or environment-dependent smoke commands only when relevant dependencies and fixtures are available. Report skipped gates and the concrete reason.

## Internationalization

When response messages, errors, metadata, generated files, PWA content, or any user-visible text changes:

```bash
cd apps/web
pnpm i18n:check
```

Test both `zh-CN` and `en-US`, preserve interpolation placeholders, and keep user-provided values untranslated.

## Proposed Tooling Gates

Use these only after their dependencies and configuration exist in `pyproject.toml`:

```bash
cd apps/api-python
uv run ruff format --check .
uv run ruff check .
uv run mypy app
uv run pytest --cov=app --cov-report=term-missing
```

Do not fail work because a proposed tool is not installed. Adding a tool is a separate authorized implementation step, not an implicit side effect of an unrelated refactor.

## Result Rules

- Compare results with the pre-change baseline.
- Treat a newly failing test as a regression until proven otherwise.
- Do not rewrite tests merely to accept changed behavior unless the user authorized that behavior change.
- Distinguish product defects, environmental failures, missing optional binaries, and pre-existing failures.
- Include the exact commands and concise outcomes in the final response.
