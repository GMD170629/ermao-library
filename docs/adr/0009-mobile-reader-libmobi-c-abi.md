# ADR 0009: Stable opaque libmobi C ABI for Reader

Status: Accepted for the current Reader implementation. Distribution licensing
and physical-device release evidence remain release gates.

## Decision

The pinned libmobi source and the only public native boundary live under
`apps/mobile/native/mobi-core`. Consumers use `ermao_mobi_*` ABI v1:

- `ErmaoMobiBook` is opaque and access is serialized;
- public records use `struct_size` and fixed-width integers;
- strings are UTF-8 caller-buffer copy-outs;
- resources expose stable indices, source names, category, media type, decoded
  length and reads bounded by the ABI's `ERMAO_MOBI_MAX_READ_BYTES` constant;
- reading order and TOC identity use resource indices, never localized titles;
- libmobi outcomes are translated into stable Ermao status and warning codes.

The ABI is an infrastructure adapter. Android JNI, the iOS wrapper and the
backend `MobiPublicationAdapter` may call it; UI, Reader domain code and Activity /
View code may not. The backend checks `ermao_mobi_abi_version() == 1` before use.

The upstream parser may load the PDB and reconstruct RAWML in memory. The ABI
bounds consumer reads but does not claim streaming parsing or remove the existing
input and parser resource budgets. It exposes an in-memory parser-backed
Publication and never creates a persisted EPUB or ZIP.

## Current evidence

`apps/api-python/app/modules/publications/infrastructure/mobi_adapter.py` loads
the ABI and enforces the 256 KiB read bound. The C header and implementation define
the v1 contract and native wrappers keep the boundary outside shared domain and UI
code.

## Consequences

Web, Android and iOS can share the same opaque-resource semantics while retaining
platform-specific wrappers. ABI, upstream license and physical-device evidence
must be checked before distribution; compilation alone is not release acceptance.
