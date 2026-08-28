# Reader archive fixtures

`reader-pages.zip`, `.cbz`, `.rar` and `.cbr` are deterministic original test
publications containing the two existing `starship-pages/*.png` resources.
Run `python3 generate_archive_fixtures.py` here to reproduce them. RAR/CBR use
RAR5 stored members with header and member CRCs, following the
[RARLab format specification](https://www.rarlab.com/technote.htm).

The native libarchive 3.8.9 host test and Android instrumentation consume these
tracked fixtures without a private `books` directory. These small fixtures test
opening, original bytes and page indexing; large/compressed archive performance
and device rendering require separate acceptance evidence. The generator is not
part of Reader bootstrap, delivery or download.
