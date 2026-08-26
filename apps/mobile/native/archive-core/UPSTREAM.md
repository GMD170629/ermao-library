# Archive Core upstream lock

- Upstream: `libarchive/libarchive`
- Version: `3.8.9`
- Release asset: `libarchive-3.8.9.tar.xz`
- SHA-256: `888c934f9d95648ecb9163dc8e23ab80a476ecb81a8f1154704a227b5b676dde`
- License: BSD 2-Clause; the unmodified upstream license is vendored at
  `vendor/libarchive-3.8.9/COPYING`.

The mobile wrapper registers only the no-filter reader plus ZIP, RAR and RAR5
formats. It does not expose extraction-to-disk or archive writing APIs.
