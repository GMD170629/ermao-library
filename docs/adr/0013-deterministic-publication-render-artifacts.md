# ADR 0013: Deterministic publication render artifacts

- Status: Accepted
- Date: 2026-08-14
- Supersedes: the whole-publication markup failure and no-derivative constraints in the Mobile Reader architecture and ADR 0012

## Context

Many valid EPUB packages have a legal EPUB 3 Navigation Document or EPUB 2 NCX but
contain ordinary, browser-recoverable HTML errors in one or more spine resources.
Requiring every body resource to pass strict XML validation before exposing the TOC
made Work Detail report no chapters and prevented Readium from opening otherwise
usable books. Platform-local recovery also produced different DOM trees and therefore
different exact Locators.

## Decision

Navigation and rendering are independent products. EPUB navigation is parsed from a
legal Nav document, with legal NCX fallback, and only local manifest/spine targets are
projected. Invalid nodes are discarded without discarding legal siblings. Body markup
is not read while generating navigation. MOBI-family, TXT and FB2 retain their native
directory sources with the same independence.

The original library publication is immutable. At Reader bootstrap the server may
generate a disposable standard-EPUB render artifact for EPUB, MOBI-family and TXT;
FB2 has the server capability but is not advertised as a client-readable format. The
artifact is keyed separately from progress by original source hash, parser identity
and render-normalization version. It is stored below the cache root, excluded from
library backup/export, and may be deleted and rebuilt.

Strict XML is preserved when it is valid. Ordinary markup failures use one server-side
WHATWG HTML5 recovery implementation followed by deterministic XHTML serialization.
An unrecoverable body keeps its original reading-order href and becomes a marked error
resource recorded in `META-INF/shuku-render.json`. ZIP entry order, timestamps,
compression settings and JSON serialization are fixed so identical input and versions
produce identical SHA-256 output.

Only exploit-capable input is rejected as a security failure: archive traversal or
symlink escape, resource-exhaustion archives, active DTD/entity declarations, or remote
package-structure references. Script, refresh, external subresources, forms, frames and
embedded objects are disabled by CSP/resource policy rather than causing a whole-book
rejection. Invalid ZIP, missing OPF and empty spine are structure failures, not security
failures.

Reader v4 keeps `fileUrl` and the original Publication fingerprint. Its optional
`publication.renderArtifact` supplies schema version, authenticated URL, MIME type,
size and content hash. New clients prefer it and verify its hash independently. They
open Readium immediately after package opening without reading the whole spine first.
A marked page is visible and retains previous, next and contents navigation; it is not
automatically skipped and never becomes a progress or bookmark location.

## Consequences

- A broken body no longer removes chapters parsed from legal navigation.
- All first-party clients consume the same recovered DOM and exact-location projection.
- A render-normalization upgrade invalidates only the disposable artifact, not existing
  progress, whose ownership remains work plus volume.
- Old clients remain protocol-compatible through `fileUrl`, but do not gain sidecar
  recovery behavior.
- Package corruption and explicit security rejection remain whole-artifact failures;
  an isolated marked body is a page-level condition.
