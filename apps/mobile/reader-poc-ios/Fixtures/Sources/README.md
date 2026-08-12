# Fixture source contract

`Tools/GenerateFixtureSources.swift` is the authoritative, self-authored generator for all ten publications. It emits the checked-in EPUB source trees under `Generated/`. `Tools/generate-fixtures.sh` packages those trees in the ignored `.fixture-build` directory and invokes exactly Calibre 9.11.0 to compile the checked-in MOBI6/KF8 files. `SHA256SUMS` covers every generated source file.

Calibre is a fixture compiler only. The iOS target neither links nor invokes Calibre, never generates an EPUB at runtime, and passes libmobi's reconstructed resources directly to an in-memory Readium `Publication`.

`Assets/Literata-Regular.ttf` is a pinned OFL test font sourced from the Google Fonts Literata project. Its license is stored alongside the font.

- Font source: `https://github.com/google/fonts/tree/main/ofl/literata`
- Font SHA-256: `b41138c9373112f32abb589cc22e8674b06ed4048b0c513be922bdd26f274440`
- OFL license SHA-256: `8742963604cd89dc81437811a850018fc03b2bfad686d7422c8235967c87614e`
