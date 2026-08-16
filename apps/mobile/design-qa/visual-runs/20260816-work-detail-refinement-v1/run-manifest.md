# Work Detail refinement run manifest

- Run id: `20260816-work-detail-refinement-v1`
- Repository HEAD at baseline: `de3d303e4a7eb692e622c33bb29e748b4637e9ac`
- Working tree: dirty/shared; no pre-existing changes were reset or claimed.
- Device: `9e896bbc`, Xiaomi `M2102K1AC`, Android 12 / API 31, physical (`ro.kernel.qemu` unset)
- Display: 1440 x 3200 px, 560 dpi, portrait
- Primary locale/theme/font: zh-CN / light / `fontScale=1.0`
- Package: `com.ermao.library`, versionCode `1`, versionName `0.1.0`
- Baseline APK SHA-256: `fa75e0da2c1b77c63cc8afca3b2b427e60f188ca79616ee0ddf3da20406ff3bf`
- Baseline deployment: data-preserving replace-install, force-stop, cold launch, resumed `.MainActivity`, no crash/ANR signature in the post-launch scan.
- Baseline product journey: Home -> Library bottom tab -> first visible work -> Work Detail.
- Deterministic evidence: fresh physical instrumentation capture of `work-about`, `work-volumes`, and `work-single-ebook`.
- Directional reference: `target/reference-direction.png`; not a pixel-equality source.
- Explicitly out of scope: 200% font scale, dark theme, en-US visual matrix, feature redesign, golden promotion.
