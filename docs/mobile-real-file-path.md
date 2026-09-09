# Mobile detail file paths

The resource asset response exposes nullable `path`: the existing physical file
under its library root, as seen by the server (the container mount for Docker).
`url` and `downloadUrl` remain transport addresses. No database migration or file
mutation is involved. Deploy the backend change before expecting populated paths
from updated mobile clients; older servers produce the existing empty-path UI.

The Library asset ORM projection owns this field for book detail, resource lists
and resource queries. Its existing asset query now joins the library root, without
adding a query per asset. Library's existing resource-detail file resolver was
extracted into `infrastructure/source_paths.py`; both projections use that owner.
It retains the existing missing-file and containment behavior. No independent
path resolver was introduced in either mobile client.

KMP already carries `Asset.path`. iOS now maps that value instead of URL fallback;
Android retains its existing path mapping. Selection and first-asset ordering are
unchanged. iOS uses an em dash when absent and Android omits the row. Full-path
inspection uses the same value as the truncated detail row. Filenames are not
localized or URL-encoded.

Verification and environment limitations are recorded in the task delivery.

## Verification (2026-09-09)

- Backend: 79 focused contract/schema/path tests pass, including unauthorized
  requests, Unicode/space-containing nested paths, unchanged transport URLs and
  unchanged file bytes. Ruff checks and formatting pass; mypy passes for all four
  touched backend source files. The test client reports its pre-existing httpx
  deprecation warning.
- KMP: 452 Android host tests pass with zero failures/errors/skips, including
  nullable path decoding and preservation of a real path independently of URL.
- iOS: signed Debug build passes; installed over the existing app on the paired
  iPhone 17 Pro Max and confirmed running. The unchanged previously built KMP
  framework was reused for this Swift-only change; the normal project build
  script was restored. Existing Reader test-target compilation blockers prevent
  claiming a full native XCTest run.
- Android build/lint could not complete: dependency resolution stalled on network
  reads; offline retry reports uncached dependencies, including AndroidX Window.
  No dependency versions or quality gates were changed. Native visual checks and
  a phone connected to an updated backend remain unverified.
