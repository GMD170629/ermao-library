#ifndef SHUKU_PDFIUM_H_
#define SHUKU_PDFIUM_H_

#include <stddef.h>
#include <stdint.h>

#if defined(__GNUC__)
#define SHUKU_PDFIUM_EXPORT __attribute__((visibility("default")))
#else
#define SHUKU_PDFIUM_EXPORT
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ShukuPdfiumDocument ShukuPdfiumDocument;

typedef enum ShukuPdfiumStatus {
  SHUKU_PDFIUM_OK = 0,
  SHUKU_PDFIUM_NEED_DATA = 1,
  SHUKU_PDFIUM_INVALID_ARGUMENT = 2,
  SHUKU_PDFIUM_INVALID_DOCUMENT = 3,
  SHUKU_PDFIUM_ENCRYPTED = 4,
  SHUKU_PDFIUM_PAGE_LOAD_FAILED = 5,
  SHUKU_PDFIUM_RENDER_FAILED = 6,
  SHUKU_PDFIUM_OUT_OF_MEMORY_RISK = 7,
} ShukuPdfiumStatus;

// All callbacks are invoked synchronously on the calling PDFium thread.
// read_cached_block() must only copy already-cached bytes and must never wait
// for the network. request_range() only schedules asynchronous acquisition.
typedef struct ShukuPdfiumByteSource {
  uint64_t length;
  void* user_data;
  int (*is_range_cached)(void* user_data, uint64_t offset, uint64_t size);
  int (*read_cached_block)(void* user_data, uint64_t offset, void* destination, uint64_t size);
  void (*request_range)(void* user_data, uint64_t offset, uint64_t size);
} ShukuPdfiumByteSource;

typedef struct ShukuPdfiumPageSize {
  float width_points;
  float height_points;
} ShukuPdfiumPageSize;

// The process must balance initialize/shutdown calls. Documents must be
// closed before the final shutdown.
SHUKU_PDFIUM_EXPORT ShukuPdfiumStatus shuku_pdfium_initialize(void);
SHUKU_PDFIUM_EXPORT void shuku_pdfium_shutdown(void);

SHUKU_PDFIUM_EXPORT ShukuPdfiumStatus shuku_pdfium_document_create(
    const ShukuPdfiumByteSource* source,
    ShukuPdfiumDocument** output);
SHUKU_PDFIUM_EXPORT void shuku_pdfium_document_close(ShukuPdfiumDocument* document);

// Re-run after every completed Range acquisition. NEED_DATA means one or more
// request_range() hints were emitted and the caller should retry later.
SHUKU_PDFIUM_EXPORT ShukuPdfiumStatus
shuku_pdfium_document_step(ShukuPdfiumDocument* document);
SHUKU_PDFIUM_EXPORT ShukuPdfiumStatus
shuku_pdfium_page_step(ShukuPdfiumDocument* document, int page_index);
SHUKU_PDFIUM_EXPORT int
shuku_pdfium_page_count(const ShukuPdfiumDocument* document);
SHUKU_PDFIUM_EXPORT ShukuPdfiumStatus shuku_pdfium_page_size(
    ShukuPdfiumDocument* document,
    int page_index,
    ShukuPdfiumPageSize* output);

// Renders into caller-owned BGRA memory. max_pixels is an explicit OOM guard.
SHUKU_PDFIUM_EXPORT ShukuPdfiumStatus shuku_pdfium_render_page_bgra(
    ShukuPdfiumDocument* document,
    int page_index,
    int width,
    int height,
    int stride,
    uint64_t max_pixels,
    void* destination);

#ifdef __cplusplus
}
#endif

#endif  // SHUKU_PDFIUM_H_
