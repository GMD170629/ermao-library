# Agent Working Guidelines

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
5. Include version-consistency checks in the release validation or workflow whenever practical, so a mismatched Web, backend, package, artifact, or GitHub release version fails before publication.
