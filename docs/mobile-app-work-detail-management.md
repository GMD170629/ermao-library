# Mobile Book Detail Management Status

This document is superseded by [ADR 0020](adr/0020-mobile-book-resource-asset-cutover.md).

The Book / ReadableResource / ResourceAsset cutover does **not** ship native
book-detail administration. `/api/mobile/compatibility` therefore publishes
`bookDetailManagement=false`, and Android/iOS must not expose or invoke those
management mutations. Global governance and batch administration remain Web-only.

The shared management adapter may retain current Book/Resource/Asset request models
for a later product decision, but it is capability-gated and must not restore any
Work/Version/Volume/File route or compatibility mapping. Shelf membership, Reader
reading status, managed offline downloads, and Kindle sending are independent user
flows; they continue to use their current Book/Resource/Asset contracts where the
native UI already supports them.

Enabling native book-detail administration later requires a separate product-scope
decision and physical-device acceptance for both Android and iOS.
