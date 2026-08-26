# Mobile Phase 7 Library Discovery acceptance

Date: 2026-08-26
Contract: ADR 0015

## Current acceptance scope

- Shared owns query identity, request generation, initial/refresh failure, pagination
  failure, permission revalidation, and stable routes. Query identity has no local-download
  filter.
- Home, Library, Facet, and Work Detail do not serialize or restore server GET pages.
  Initial load or explicit refresh failure replaces only the current result area with a
  network error.
- A next-page failure preserves pages already accepted by the current generation and
  exposes one inline retry. A late response from an older generation is rejected.
- Permission revalidation obscures old private results before requesting the new
  authorization namespace.
- Download Center is the only local-download discovery surface. Completed publications,
  authenticated covers, Reader caches, progress, and bookmarks are outside Library query
  identity.
- iOS uses native NavigationStack, Search, Menu, and Sheet. Android uses Navigation 3,
  Material Menu and ModalBottomSheet; system/predictive back remains platform-owned.

## Required automated evidence

- `verifyMobileOfflineContract` rejects the removed authorization, page-cache, stale-state,
  filter, and deleted visual-asset identifiers.
- Shared tests prove generation rejection, no first-page fallback, page preservation after
  pagination failure, permission masking, and query identity without a download filter.
- Android/iOS tests remove old cache/freshness/filter expectations and prove local network
  error, pagination preservation/retry, authenticated-cover namespace/LRU behavior, and
  best-effort deletion of the legacy page-cache directory.
- Both `zh-CN` and `en-US` have equivalent error and retry copy, with no stale-result,
  separate-Shell, or remaining-days copy.

## Runtime and visual evidence

The checked-in Phase 7 PNGs remain composition evidence only for current states. Manual
capture is required on both physical platforms across Compact/Expanded, Light/Dark,
`zh-CN`/`en-US`, default/large text, initial loading, empty, ordinary network failure,
pagination failure, and permission revalidation.

Android acceptance requires an explicitly addressed non-emulator physical device, a
data-preserving replace-install, force-stop/cold-launch, resumed-activity verification,
crash/ANR log inspection, and the focused UI/instrumentation journeys. iOS acceptance
requires a paired, unlocked, signed `iphoneos` physical device and XCTest/UI network-failure
journeys; Simulator evidence is prohibited.

## Historical evidence

The 2026-08-12 backend, Shared, Android-host, signed iPhone, XCTest, and UI results predate
ADR 0015. They remain historical evidence only for the behaviors they actually executed and
must not be used to claim the removed page-snapshot, freshness, or local-download-filter
contract. A new passing conclusion may be recorded only after the current automated and
physical-device gates pass on the same candidate revision.
