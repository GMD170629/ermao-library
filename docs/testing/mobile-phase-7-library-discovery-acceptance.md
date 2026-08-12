# Mobile Phase 7 Library Discovery acceptance

Date: 2026-08-12

## Implemented scope

- Shared Works, Series, Authors, Search, Facet, filter, sort/view, pagination, scroll restoration, cache provenance, permission states, and stable routes.
- KMP owns query identities, request generation, state phases, serialized page snapshots, five-minute stale policy, three-page retention, and private namespace isolation.
- Series facet is fixed to `series_index`; Author facet is fixed to `recent_read`; Series/Authors root scopes do not expose Works-only sort/view actions.
- The Downloaded filter is visible but disabled in zh-CN and en-US. Owner and removal condition are recorded in ADR 0008.
- iOS uses native NavigationStack, Search, Menu, and Sheet. Android uses Navigation 3, Material Menu and ModalBottomSheet; NavDisplay owns system/predictive back.

## Automated evidence

Evidence collected on 2026-08-12:

- Backend Library focused contract/integration suite: 24 passed for `/api/works`, groupings, and facets.
- Backend full Pytest: 1081 passed, 5 skipped, 2 failed. Both failures are unrelated global route-count baselines (`210`/`207` expected versus `208`/`205` registered); they do not exercise Library Discovery. Ruff and Mypy are not installed in the backend environment, so those gates have no evidence.
- KMP Android-host suite: 95 passed, including discovery runtime, cache isolation, auth, persistence, and personal-settings coverage.
- Android app unit suite: 24 passed. `lintDebug` and `assembleDebug` passed with warnings-as-errors and no lint baseline.
- Android emulator, physical-device instrumentation, and device visual testing were intentionally not run per the current implementation instruction.
- `xcodebuild -showdestinations` exposed one physical destination: `00008150-0011112211A0C01C` (`Xiaomi 17 Pro Max`, iPhone 17 Pro Max).
- Signed physical-device `iphoneos` build passed.
- Physical-device XCTest/UI evidence: the final full run passed all 46 tests with zero failures and zero skips. During an earlier combined run, a system notification interrupted one UI process with `signal kill`; that journey also passed when rerun alone. No Simulator was used.

## Visual matrix

The checked-in Phase 7 PNGs remain the composition baseline. Manual capture is required for both platforms across:

- Compact and Expanded.
- Light and Dark.
- zh-CN and en-US.
- Default and maximum supported text size.
- initial loading, empty, ordinary network failure, offline cached, pagination failure, permission revalidation, and stale refresh.

Android SDK-backed host compilation is complete, but Android device and the full visual matrix remain deferred. Therefore this record does not claim final cross-platform visual acceptance. Cached discovery metadata must not be interpreted as offline-open eligibility.
