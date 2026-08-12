# Ermao MOBI Core v1

`mobi-core` is the single production libmobi core consumed by Android JNI and
iOS Swift/C interoperability. Its public surface is only
`Sources/CLibMobi/public/ermao_mobi.h`; libmobi structures, errors and data
pointers are private.

## Contract

- ABI version: `1`
- parser: `libmobi:0.12@85dcfe803fc2a21020ddcf15c3eb66b93d388add`
- normalization: `ermao-mobi-core-v1`
- input: readable regular MOBI/PRC/AZW/AZW3/KF8 files, at most 512 MiB
- resource reads: offset based, at most 256 KiB per call, EOF is success with
  zero bytes
- ownership: one opaque handle, serialized access, idempotent close through a
  pointer-to-handle

The handle retains libmobi's loaded records and reconstructed RAWML. It does not
make the former POC's additional whole-publication resource copy. Pinned
libmobi still loads all PDB records and reconstructs complete RAWML internally;
this is an explicit memory baseline, not a claim of lazy parsing. R6/R7 may read
individual normalized resources lazily through this ABI but may not create an
EPUB conversion.

## Builds

Host:

```bash
cmake -S apps/mobile/native/mobi-core -B build/mobi-core
cmake --build build/mobi-core
ctest --test-dir build/mobi-core --output-on-failure
build/mobi-core/ermao_mobi_memory_probe upstream <publication>
build/mobi-core/ermao_mobi_memory_probe abi <publication>
```

Host golden snapshots are produced with `ermao_mobi_snapshot`. Sanitizer and
fuzzer builds use `ERMAO_MOBI_ENABLE_SANITIZERS=ON` and
`ERMAO_MOBI_BUILD_FUZZER=ON`; a release gate passes only when both complete
without a sanitizer, crash, OOM or leak finding.

Android builds through `apps/mobile/mobiCore/src/main/cpp/CMakeLists.txt` for
`arm64-v8a` and the selected test ABI. iOS consumes `Package.swift` as the local
`ErmaoMobiCore` package and imports the `CLibMobi` C module. iOS runtime evidence
is physical-device-only.

## Non-goals

R5 does not expose a MOBI UI entry, create a Readium `Publication`, change
`ReaderFormat`, Reader JSON/progress, backend APIs or user-visible copy. Those
integration responsibilities remain R6/R7.
