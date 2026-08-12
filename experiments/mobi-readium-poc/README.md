# libmobi → Readium runtime Publication POC

This experiment validates a no-conversion path for MOBI/KF8/AZW3:

1. Compile libmobi v0.12.
2. Parse libmobi's real MOBI/KF8-oriented test corpus into HTML/CSS/font/media resources.
3. Verify Readium 3.3.0's EPUB-profile navigator consumes a runtime `Publication` rather than requiring an `.epub` package.
4. Compile a minimal Android consumer that constructs such a runtime `Publication` and hands it to `EpubNavigatorFactory`.

This branch is isolated from product code and is not intended for merge as-is.
