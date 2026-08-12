# ADR 0009: Stable opaque libmobi C ABI for Mobile Reader

Status: Accepted for R5 implementation; R4 freeze, fuzz safety, physical iOS and license release gates remain open
Date: 2026-08-12

## Context

Android and iOS need equivalent access to original MOBI-family publications,
while libmobi exposes process-local structures, pointers, platform-sized fields
and upstream error values. The earlier iOS POC copied every reconstructed
resource into a second whole-book allocation and directly shaped a Readium
container. That ownership model is not a production boundary.

R5 must not change the EPUB reader, shared Reader domain/progress JSON, backend
contracts or user-visible format availability. Readium publication adapters are
separate R6/R7 decisions.

## Decision

The repository has one pinned libmobi v0.12 source tree at
`apps/mobile/native/mobi-core`. Its only public native contract is
`ermao_mobi_*` ABI v1.

- `ErmaoMobiBook` is opaque and permits serialized access only.
- Public structs begin with `struct_size` and use fixed-width integers.
- Publication strings use UTF-8 caller-buffer copy-out.
- Resources expose stable indices, source UID/name, category, media type,
  decoded length and reads bounded to 256 KiB.
- Reading order and flat pre-order TOC refer only to resource indices; TOC
  identity never depends on a localized title.
- Stable Ermao status/warning codes translate all libmobi outcomes.
- Hybrid selects valid KF8 and records a warning when MOBI6 fallback is needed.
- Android JNI and the iOS actor wrapper are infrastructure adapters. Neither UI,
  shared domain nor Activity/View code may call the C ABI directly.

Pinned libmobi loads all PDB records and reconstructs complete RAWML. The ABI
removes the additional POC copy and bounds consumer reads, but it cannot claim
that upstream parsing is streaming. The 512 MiB input limit, large-file device
tests and phase-blocking OOM policy make that cost explicit.

## Consequences

R6/R7 receive equivalent metadata, resource, reading-order, TOC, warning and
chunk-read interfaces without inheriting libmobi pointers. Source resource names
remain available for later Kindle-link rewriting; R5 does not define virtual
Readium hrefs.

The LGPL source, provenance and local-change record ship with the core. A formal
license conclusion is required before distribution; the project does not assume
static linking is automatically compliant.
