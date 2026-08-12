# Vendored libmobi provenance

- Upstream: <https://github.com/bfabiszewski/libmobi>
- Version: `v0.12`
- Commit: `85dcfe803fc2a21020ddcf15c3eb66b93d388add`
- License: LGPL-3.0-or-later; the unmodified upstream license is retained as `LICENSE`.

The vendored source is the repository's only libmobi copy. Host CMake, Android
NDK/CMake and the iOS local Swift Package compile this directory. CLI programs,
the bundled miniz fallback, DRM decryption, random-byte and SHA-1 implementations
are excluded; system zlib and libmobi's internal XML writer are used.

Local production changes are isolated to:

- `Sources/CLibMobi/public/ermao_mobi.h`, the stable opaque C ABI v1;
- `Sources/CLibMobi/src/ermao_mobi.c`, validation, normalization, indexing,
  caller-buffer copy-out and bounded reads;
- build/test/package metadata outside upstream source files.

No upstream libmobi implementation file was modified. Formal distribution must
still receive a license review covering the selected static/dynamic linking
method, relinking/replacement obligations and source offer. Static linking is
not assumed compliant by default.
