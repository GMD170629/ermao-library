# Catalog header and navigation target v1

Scope: Android Library and Shelves root headers; Book entry identity and return/context isolation. User request is authoritative for this header revision. Existing Warm Page semantic tokens, list/grid density, native shell and actions remain unchanged.

Primary: physical Android, zh-CN, light, normal font, top scroll, All selected. Compare each page against its own baseline. Book counts/covers and empty shelves are data-dependent; no server fixture writes.

Annotated target blueprint:
[Native large title + existing actions]
[Native search input, full content width, existing library gutter]
[Native Material secondary tabs: All | library names OR All | Shelves | Collections]
[Existing count/filter summary where applicable]
[Existing grid/list/empty state]
[Existing four-destination native navigation]

Must match: identical search/tabs layout and gutters on both root pages; search uses native text field minimum and tabs use native sizing, no undersized chip labels, no forced fixed-height text; tabs use indicator/selected semantics instead of chip backgrounds. Native components own geometry. Content stays primary. Preserve localized names, search values per scope, filter behavior, source identity, cover density, navigation and return stack. No Reader/backend/Web/iOS changes.

Candidate hypothesis: one shared native search-and-tabs header removes independent chip sizing/padding drift. Book routes carry Book and authorization namespace identity through saved navigation and ViewModel ownership.

Baseline B0 is the installed current build (comparison reference, not accepted final UX). Runtime proof, original screenshots, candidate comparisons and checks will be recorded here. No visual PASS without current physical-device evidence and independent review.
