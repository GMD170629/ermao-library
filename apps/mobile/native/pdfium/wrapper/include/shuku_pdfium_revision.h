#ifndef SHUKU_PDFIUM_REVISION_H_
#define SHUKU_PDFIUM_REVISION_H_

#if defined(__GNUC__)
#define SHUKU_PDFIUM_REVISION_EXPORT __attribute__((visibility("default")))
#else
#define SHUKU_PDFIUM_REVISION_EXPORT
#endif

#ifdef __cplusplus
extern "C" {
#endif

SHUKU_PDFIUM_REVISION_EXPORT const char* shuku_pdfium_revision(void);
SHUKU_PDFIUM_REVISION_EXPORT int shuku_pdfium_wrapper_abi_version(void);

#ifdef __cplusplus
}
#endif

#endif  // SHUKU_PDFIUM_REVISION_H_
