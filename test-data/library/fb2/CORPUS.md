# FB2 Reader corpus

## `source_test_book_fb2.fb2`

- Source: <https://github.com/clach04/sample_reading_media>
- Upstream commit: `472634007deea9fc2a7ace050309c8fc01230413`
- Upstream path: `source_test_book_fb2.fb2`
- License: LGPL-2.1, as declared by the upstream repository
- SHA-256: `309f2293575c8165291e89165ed77a57095cd20727a57eb1ba227364ae79a693`
- Expected import: one READY `FB2` readable resource in the FLAT electronic-book library
- Expected Reader adapters: `shuku-fb2-parser-v1` and `shuku-fb2-publication-v1`

The file is kept byte-for-byte identical to upstream. It is imported through the
normal filesystem scan queue and is never inserted into the catalog database directly.

## `reader-contract.fb2` and `reader-contract-bodies.json`

- Original project test content, available under the repository license. No external book text.
- Exercises bilingual metadata, nested sections, mixed inline content, CDATA, PNG, tables, poetry, notes and return links.
- SHA-256: `e3dd86210fb2da80aaa5393a32a5e9959a9ef2ca49e6fbcecc713c3ffc66165d`.
- The body golden was generated with the existing server `shuku-fb2-publication-v1` adapter. Android and iOS must produce these exact bodies and hrefs before platform head-only security decoration.
- Both files are shared test inputs, not derived Reader artifacts. Production persists only the original FB2.
