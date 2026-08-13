# Readium Web MOBI runtime POC — technical conclusion

Date: 2026-08-13

## Result

The POC demonstrates that the already validated libmobi runtime Publication model can be hosted as an EPUB-profile Readium Web Publication Manifest and rendered by the real Readium TypeScript Navigator. No EPUB conversion is involved.

Observed in Chrome against the native POC server:

| Capability | Fixture / action | Result |
| --- | --- | --- |
| Real Readium body rendering | `08-zh-hans.azw3` | Pass; Navigator iframe displayed reconstructed XHTML |
| CJK / non-BMP | `08-zh-hans.azw3` | Pass; `ZH_TEXT_MARKER`, `𠮷`, and `𪚥` visible |
| Paginated / scroll | preference switch | Pass; content remained visible in both modes |
| Publisher CSS | `03-css.azw3` | Pass; 37 px left margin and `rgb(32, 78, 121)` computed color |
| Embedded font | `04-font.azw3` | Pass; `"Shuku Test Font", serif` loaded and applied |
| Images | `05-images.azw3` | Pass; 2/2 PNG/JPEG images decoded |
| Web Locator self round-trip | CJK chapter title | Pass; `#chapter-title` + `中文` restored and classified `exact-block` |
| iOS Locator self round-trip | physical iPhone, CJK fixture | Pass; focused XCTest copied `firstVisibleElementLocator()` and restored it with `go(to:)` |

The iOS target was built for and installed on a connected physical iPhone 17 Pro Max; the focused physical-device XCTest passed. No Simulator evidence was used.

## Cross-platform precision conclusion

Block-level exact synchronization is implementable when all of the following are true:

1. iOS and Web consume the same libmobi-derived virtual resource tree.
2. `href` normalization and the structured original-hash/parser/normalization fingerprint match.
3. The full Readium Locator is exchanged, including `cssSelector` and bounded text context.
4. The target verifies the post-navigation first-visible anchor instead of treating `go()` success as proof.

Only progression/position is approximate. Whole-publication progression is a final fallback. Page number and pixel coordinates are never cross-device exact for reflowable content.

The two sides now share a compatible envelope:

```json
{
  "engine": "readium",
  "platform": "ios | web",
  "version": "readium-swift:3.11.0 | readium-ts:2.8.2",
  "publication": {
    "originalFileHash": "f2b9fdd883430568c161995e80e52fc337ceb417222884c3c782af8202f4c581",
    "parser": "libmobi:0.12@85dcfe803fc2a21020ddcf15c3eb66b93d388add",
    "normalization": "ermao-mobi-core-v1"
  },
  "payload": {
    "href": "part00000.html",
    "type": "application/xhtml+xml",
    "locations": {
      "cssSelector": "#chapter-title",
      "progression": 0,
      "position": 1
    },
    "text": { "highlight": "中文" }
  }
}
```

## Remaining acceptance gate

The Web and iOS halves, their wire compatibility, and self round-trips are proven. A literal iOS-export -> Web-import -> Web-export -> iOS-import run across two devices still requires one manual Universal Clipboard or server-sync session. It should be recorded as a separate physical-device evidence artifact before claiming the full bidirectional journey accepted in production.

The POC enforces the renderer-neutral fingerprint check. Production integration must preserve it in the v4 progress contract and must not route Readium payloads through the current Foliate-only Web progress mapper.
