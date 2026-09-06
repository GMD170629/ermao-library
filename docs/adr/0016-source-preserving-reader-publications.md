# ADR 0016: Source-preserving Reader Publications

Status: Accepted for source preservation. Complete-original delivery is detailed
in [ADR 0025](0025-reflowable-original-download-before-reading.md), safety in
[ADR 0026](0026-versioned-reader-safety-policy-contract.md) and progress in
[ADR 0028](0028-reader-v5-opaque-position-report.md).

## Decision

Every reflowable Reader consumes the verified original format through its local
parser. The original remains the only persisted Reader body in Downloads, Web
Cache Storage and local imports. Reader must not create, cache, advertise or
download a derived EPUB, ZIP or unpacked publication directory.

MOBI, AZW, AZW3 and PRC use the pinned libmobi ABI; TXT and FB2 use their
format-specific parser adapters. These adapters expose an in-memory
parser-backed Publication. They are not conversion pipelines and do not alter
the original bytes. Safety may sanitize a recoverable authored hazard in the
in-memory Publication under ADR 0026; it must never persist that sanitized result
or replace the verified original.

Reader v5 exchanges the active engine's complete position/Locator inside the opaque
`ReaderPositionReport`, including the native format engine's position for PDF,
comic and audio readers. The server does not require an EPUB container, derive
Locator fields or reopen the source to validate engine anchors.

## Current evidence

The backend MOBI adapter is
`apps/api-python/app/modules/publications/infrastructure/mobi_adapter.py`; the
Reader v5 publication route is under `app/modules/reader/presentation/v5.py`.
The shared format capability contract maps reflowable formats to
`DOWNLOAD_ORIGINAL`.

## Consequences

Parser failures remain visible at the format boundary. Download, Reader, progress
and cache paths have one original-source owner and no hidden derived-publication
fallback.
