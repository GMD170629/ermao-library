# Shuku PDFium candidate artifacts

This directory owns the native PDF renderer used by Android and iOS. The lock is deliberately
`candidate`, not `frozen`: commit `875172eae557a308d0c5b2be43822814c8a885bb` must build and pass
the shared corpus on Android and a physical iOS device before binaries can be accepted.

Build requirements:

- Chromium `depot_tools` and a checkout whose `HEAD` exactly matches the lock commit.
- Release/static PDFium with V8/JavaScript, XFA, Skia, Fontations and component builds disabled.
- Android outputs for `arm64-v8a`, `armeabi-v7a` and `x86_64`.
- iOS output for physical-device `ios-arm64` only. Simulator slices are rejected.

Run `scripts/configure-android.sh <pdfium-checkout> <output-root>` on Linux for each Android
architecture. Run `scripts/configure-ios.sh <pdfium-checkout> <output-root>` on macOS. These
scripts fail if the checkout revision or host is wrong; they never select a different revision.

After the platform packages and corpus reports exist, populate `artifacts` with repository-relative
paths, SHA-256 values, sizes and license paths, change `status` to `frozen`, then run
`scripts/verify-lock.py`. Binary artifacts are tracked by Git LFS.

Both platform build scripts regenerate `artifacts/licenses/PDFIUM_LICENSE.txt` and the deterministic
`artifacts/licenses/THIRD_PARTY_NOTICES.txt`. Lock entries must point at the notice bundle and may not
be frozen when either license file is missing.

The wrapper ABI exports `shuku_pdfium_revision()` and `shuku_pdfium_wrapper_abi_version()` so both
applications can assert at runtime that they loaded the same revision.
