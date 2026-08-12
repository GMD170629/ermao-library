# iOS Content Discovery Polish Audit

Date: 2026-08-12

Status: implementation complete; targeted physical-device XCTest and the critical filter interaction passed. Home and Library post-change screenshots were captured on the physical device.

## Scope and evidence

- User-reported Home comparison: `home-before-and-reference.png`
- User-reported Work Detail comparison: `work-detail-before-and-reference.png`
- Authoritative references:
  - `docs/assets/mobile-app-hifi-v1/home-app-light-v1.png`
  - `docs/assets/mobile-app-hifi-v1/library-app-light-v1.png`
  - `docs/assets/mobile-app-hifi-v1/library-filter-sheet-app-light-v1.png`
  - `docs/assets/mobile-app-hifi-v1/library-series-scope-app-light-v1.png`
  - `docs/assets/mobile-app-hifi-v1/library-authors-scope-app-light-v1.png`
  - `docs/assets/mobile-app-hifi-v1/library-series-facet-app-light-v1.png`
  - `docs/assets/mobile-app-hifi-v1/library-author-facet-app-light-v1.png`
  - `docs/assets/mobile-app-hifi-v1/work-detail-introduction-ios-app-light-v2.png`
  - `docs/assets/mobile-app-hifi-v1/work-detail-media-volumes-ios-app-light-v2.png`
  - `docs/assets/mobile-app-hifi-v1/work-detail-ebook-chapters-ios-app-light-v2.png`
  - `docs/assets/mobile-app-hifi-v1/work-detail-actions-sheet-ios-app-light-v2.png`

## Step health

| Surface | Before | Implemented result | Runtime gate |
| --- | --- | --- | --- |
| Library filter | Applying a filter could terminate the app | Typed media-filter construction, non-throwing Facet decoding and stale-result rejection prevent Kotlin exceptions from crossing the bridge | Physical multi-select Apply passed; no new crash log |
| Series / Authors | Returning to a loaded scope reused stale content | Every scope entry revalidates while preserving the previous result with a refreshing state | Physical XCTest passed; live mutation remains covered by controllable client test |
| Home | Section links competed with headings and ignored the accent hierarchy | Smaller label, accent color, chevron, and a full 44pt target; section/card density retuned | `home-after-physical.png` |
| Library | Weak result/filter hierarchy and undersized grouping imagery | Result header, applied-filter summary, offline/stale states, three-cover grouping rows, spacing and typography retuned | `library-after-physical.png` |
| Filter Sheet | Selection and primary action lacked clarity | Native Sheet/List retained; native checkmarks, draft semantics, clear/cancel and full-width branded Apply restored | Physical tap-through passed |
| Facet | Identity and item hierarchy were too flat | Identity/count/sort header, denser series rows, media/progress details and accessible ordering added | Post-change screenshot pending |
| Work Detail | Description and media structure competed in one long flow; download and reading progress were easy to conflate | Replaced by the v2 hierarchy: hero/status/progress/CTA, first-level About/Media tabs, three media kinds, continuous volumes with progress below the title, single-volume EPUB chapter fallback, and native secondary actions with truthful capability gating | Physical-device XCUITest passed; About and Media/Chapters screenshots archived |

## Root cause and regression coverage

The initial filter crash was caused by cancelling an in-flight Kotlin request from a Swift task. Kotlin `CancellationException` crossed the exported bridge and terminated the process with `SIGABRT`. Home, Library, Facet and Work Detail now keep bridge calls alive and reject stale outcomes with UUID generations. Only the Swift-local search debounce remains cancellable.

Physical retesting then exposed two adjacent bridge/contract defects that unit stubs could not reveal: Swift passed `Set<String>` into Kotlin's erased `Set<MediaKind>`, and an older Facet response could omit `appliedFacet`. The bridge now uses a Swift-friendly typed filter factory, and missing Facet identity becomes a typed protocol failure instead of `requireNotNull` escaping Kotlin and aborting the app.

Added regression coverage:

- `testApplyingFiltersDoesNotCancelInFlightContentRequestAndRejectsItsStaleResult`
- `testReturningToGroupingScopeRevalidatesServerContent`
- `swiftFriendlyFilterFactoryProducesTypedMediaKinds`
- `missingFacetIdentityIsRejectedWithoutThrowingAcrossPlatformBoundary`

## Completed checks

- Shared KMP `iosArm64` compilation
- Design-token verification
- Signed physical-device `iphoneos` build
- Two targeted XCTest cases passed on device `00008150-0011112211A0C01C`
- Swift parsing for the changed visual surfaces
- `en` / `zh-Hans` catalog validation
- `git diff --check`

No iOS Simulator was used. A full dark-mode, maximum Dynamic Type and VoiceOver screenshot matrix remains outside this focused correction pass.
