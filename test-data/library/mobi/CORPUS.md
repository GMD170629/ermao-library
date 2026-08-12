# Shared MOBI corpus

The ten self-authored Calibre fixtures and their original SHA-256 manifest were
migrated from the isolated iOS POC. `12-basic.prc` and `13-basic.azw` are exact
extension variants of the self-authored MOBI6 fixture; they verify that parsing
uses the Palm/MOBI container rather than filename heuristics.

Two fixtures come unchanged from the pinned libmobi v0.12 repository and are
covered by its LGPL-3.0-or-later distribution:

- `11-upstream-huff-cdic.mobi`: SHA-256
  `560dda58429878a64f73381ffddfcf1a59809e7c669a5222666257df8976a68f`;
  it is a Hybrid publication whose selected KF8 text uses HUFF/CDIC.
- `negative-upstream-drm-v1.mobi`: SHA-256
  `631e7afe719c04a91744c22f3021a2af1cafe541f93612a27d629ab74645494`;
  it is error-path data only and must return `drm_protected`.

`generate_negative_corpus.py` deterministically derives extension variants,
truncated, pseudo-format, no-content, corrupt-record-offset and synthetic
DRM-header cases from the self-authored MOBI6 fixture. `GENERATED-SHA256SUMS`
pins those results. The generator contains no book text.

`01-basic-mobi6.abi-v1.snapshot` and
`11-upstream-huff-cdic.abi-v1.snapshot` are canonical line-oriented ABI v1
goldens. They pin the ABI/parser/normalization identifiers, format, direction,
metadata, resource category/type/length/SHA-256, reading order, hierarchical
TOC parent/target/title/fragment and warnings. Host C generates them; Android
instrumentation compares both byte-for-byte, and the physical-device iOS
XCTest performs the same comparison.

KFX and AZW4 are intentionally unsupported format classes. The deterministic
`negative-synthetic-kfx.kfx` and `negative-synthetic-azw4.azw4` pseudo-format
files verify that extension spoofing returns stable `unsupported`; they are not
claimed as genuine format coverage. Legally redistributable real KFX/AZW4
samples remain required before release acceptance and must also fail without a
crash.
