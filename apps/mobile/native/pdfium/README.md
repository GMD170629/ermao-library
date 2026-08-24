# Shuku PDFium candidate artifacts

This directory owns the native PDF renderer used by Android and iOS. The lock is deliberately
`candidate`, not `frozen`: Android uses source commit
`875172eae557a308d0c5b2be43822814c8a885bb`, while iOS uses the pinned
`bblanchon/pdfium-binaries` release `153.0.8009.0`. Both must pass the shared corpus on their
physical-device targets before binaries can be accepted.

Build requirements:

- Android source builds require Chromium `depot_tools` and a checkout whose `HEAD` exactly matches
  the lock commit.
- Android uses release/static PDFium with V8/JavaScript, XFA, Skia, Fontations and component builds
  disabled.
- Android outputs for `arm64-v8a`, `armeabi-v7a` and `x86_64`.
- iOS output for physical-device `ios-arm64` only. Simulator slices are rejected.

Run `scripts/configure-android.sh <pdfium-checkout> <output-root>` on Linux for each Android
architecture. For iOS, run `bash scripts/install-ios-release.sh` on macOS. The iOS installer uses
the pinned `bblanchon/pdfium-binaries` physical-device arm64 release, verifies its SHA-256, requires
the binary's iOS 17.0 minimum deployment target, and compiles only the repository-owned Range
adapter. It does not build PDFium from source and does not package Simulator slices.

After the platform packages and corpus reports exist, populate `artifacts` with repository-relative
paths, SHA-256 values, sizes and license paths, change `status` to `frozen`, then run
`scripts/verify-lock.py`. Binary artifacts are tracked by Git LFS.

The source-build packaging scripts regenerate `artifacts/licenses/PDFIUM_LICENSE.txt` and the deterministic
`artifacts/licenses/THIRD_PARTY_NOTICES.txt`. Lock entries must point at the notice bundle and may not
be frozen when either license file is missing.

The wrapper ABI exports `shuku_pdfium_revision()` and `shuku_pdfium_wrapper_abi_version()` so each
application can assert at runtime that it loaded its platform's pinned PDFium revision.
