# Vendored libmobi provenance

- Upstream: `https://github.com/bfabiszewski/libmobi`
- Version: `v0.12`
- Commit: `85dcfe803fc2a21020ddcf15c3eb66b93d388add`
- License: LGPL-3.0-or-later (see `LICENSE`)

The local Swift Package compiles the upstream parser and XML writer as a C target with system zlib. CLI programs, bundled miniz, DRM decryption implementation, random bytes and SHA-1 helpers are excluded. `mobi_parse_rawml` reconstructs markup, flows and resources and invokes `mobi_decode_font_resource` for FONT records. The bridge copies all returned values into owned buffers, rejects encrypted/unsupported input, and releases both `MOBIData` and `MOBIRawml` on every exit path.
