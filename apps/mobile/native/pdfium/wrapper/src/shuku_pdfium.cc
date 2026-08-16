#include "shuku_pdfium.h"

#include <limits.h>

#include <cstdint>
#include <limits>
#include <mutex>
#include <new>

#include "public/fpdf_dataavail.h"
#include "public/fpdfview.h"

namespace {

int g_library_references = 0;

std::mutex& LibraryMutex() {
  // PDFium treats exit-time destructors as build errors. This lock protects a
  // process-wide library lifecycle and intentionally lives until process exit.
  static std::mutex* const mutex = new std::mutex();
  return *mutex;
}

struct FileAvailabilityContext {
  FX_FILEAVAIL api{};
  ShukuPdfiumDocument* owner = nullptr;
};

struct DownloadHintsContext {
  FX_DOWNLOADHINTS api{};
  ShukuPdfiumDocument* owner = nullptr;
};

bool IsValidRange(uint64_t length, uint64_t offset, uint64_t size) {
  return size > 0 && offset <= length && size <= length - offset;
}

ShukuPdfiumStatus LastDocumentError() {
  return FPDF_GetLastError() == FPDF_ERR_PASSWORD ? SHUKU_PDFIUM_ENCRYPTED
                                                   : SHUKU_PDFIUM_INVALID_DOCUMENT;
}

}  // namespace

struct ShukuPdfiumDocument {
  ShukuPdfiumByteSource source{};
  FPDF_FILEACCESS file_access{};
  FileAvailabilityContext availability_context{};
  DownloadHintsContext hints_context{};
  FPDF_AVAIL availability = nullptr;
  FPDF_DOCUMENT document = nullptr;
};

namespace {

FPDF_BOOL IsDataAvailable(FX_FILEAVAIL* interface,
                          size_t offset,
                          size_t size) {
  auto* context = reinterpret_cast<FileAvailabilityContext*>(interface);
  ShukuPdfiumDocument* document = context->owner;
  if (document == nullptr || !IsValidRange(document->source.length, offset, size)) {
    return 0;
  }
  return document->source.is_range_cached(
      document->source.user_data, static_cast<uint64_t>(offset),
      static_cast<uint64_t>(size));
}

int ReadCachedBlock(void* parameter,
                    unsigned long position,
                    unsigned char* destination,
                    unsigned long size) {
  auto* document = static_cast<ShukuPdfiumDocument*>(parameter);
  if (document == nullptr || destination == nullptr ||
      !IsValidRange(document->source.length, position, size)) {
    return 0;
  }
  return document->source.read_cached_block(
      document->source.user_data, static_cast<uint64_t>(position), destination,
      static_cast<uint64_t>(size));
}

void RequestRange(FX_DOWNLOADHINTS* interface, size_t offset, size_t size) {
  auto* context = reinterpret_cast<DownloadHintsContext*>(interface);
  ShukuPdfiumDocument* document = context->owner;
  if (document == nullptr || !IsValidRange(document->source.length, offset, size)) {
    return;
  }
  document->source.request_range(document->source.user_data,
                                 static_cast<uint64_t>(offset),
                                 static_cast<uint64_t>(size));
}

ShukuPdfiumStatus AvailabilityStatus(int status) {
  switch (status) {
    case PDF_DATA_AVAIL:
      return SHUKU_PDFIUM_OK;
    case PDF_DATA_NOTAVAIL:
      return SHUKU_PDFIUM_NEED_DATA;
    default:
      return SHUKU_PDFIUM_INVALID_DOCUMENT;
  }
}

ShukuPdfiumStatus LoadPage(ShukuPdfiumDocument* document,
                           int page_index,
                           FPDF_PAGE* output) {
  if (document == nullptr || document->document == nullptr || output == nullptr ||
      page_index < 0 || page_index >= FPDF_GetPageCount(document->document)) {
    return SHUKU_PDFIUM_INVALID_ARGUMENT;
  }
  const ShukuPdfiumStatus availability =
      AvailabilityStatus(FPDFAvail_IsPageAvail(document->availability, page_index,
                                               &document->hints_context.api));
  if (availability != SHUKU_PDFIUM_OK) {
    return availability;
  }
  *output = FPDF_LoadPage(document->document, page_index);
  return *output == nullptr ? SHUKU_PDFIUM_PAGE_LOAD_FAILED : SHUKU_PDFIUM_OK;
}

}  // namespace

ShukuPdfiumStatus shuku_pdfium_initialize(void) {
  std::lock_guard<std::mutex> lock(LibraryMutex());
  if (g_library_references++ == 0) {
    FPDF_LIBRARY_CONFIG config{};
    config.version = 2;
    FPDF_InitLibraryWithConfig(&config);
  }
  return SHUKU_PDFIUM_OK;
}

void shuku_pdfium_shutdown(void) {
  std::lock_guard<std::mutex> lock(LibraryMutex());
  if (g_library_references <= 0) {
    return;
  }
  if (--g_library_references == 0) {
    FPDF_DestroyLibrary();
  }
}

ShukuPdfiumStatus shuku_pdfium_document_create(
    const ShukuPdfiumByteSource* source,
    ShukuPdfiumDocument** output) {
  if (source == nullptr || output == nullptr || source->length == 0 ||
      source->length > ULONG_MAX || source->is_range_cached == nullptr ||
      source->read_cached_block == nullptr || source->request_range == nullptr) {
    return SHUKU_PDFIUM_INVALID_ARGUMENT;
  }
  *output = nullptr;
  auto* document = new (std::nothrow) ShukuPdfiumDocument();
  if (document == nullptr) {
    return SHUKU_PDFIUM_OUT_OF_MEMORY_RISK;
  }
  document->source = *source;
  document->file_access.m_FileLen = static_cast<unsigned long>(source->length);
  document->file_access.m_GetBlock = ReadCachedBlock;
  document->file_access.m_Param = document;
  document->availability_context.api.version = 1;
  document->availability_context.api.IsDataAvail = IsDataAvailable;
  document->availability_context.owner = document;
  document->hints_context.api.version = 1;
  document->hints_context.api.AddSegment = RequestRange;
  document->hints_context.owner = document;
  document->availability = FPDFAvail_Create(&document->availability_context.api,
                                             &document->file_access);
  if (document->availability == nullptr) {
    delete document;
    return SHUKU_PDFIUM_INVALID_DOCUMENT;
  }
  *output = document;
  return SHUKU_PDFIUM_OK;
}

void shuku_pdfium_document_close(ShukuPdfiumDocument* document) {
  if (document == nullptr) {
    return;
  }
  if (document->document != nullptr) {
    FPDF_CloseDocument(document->document);
  }
  if (document->availability != nullptr) {
    FPDFAvail_Destroy(document->availability);
  }
  delete document;
}

ShukuPdfiumStatus shuku_pdfium_document_step(ShukuPdfiumDocument* document) {
  if (document == nullptr || document->availability == nullptr) {
    return SHUKU_PDFIUM_INVALID_ARGUMENT;
  }
  if (document->document != nullptr) {
    return SHUKU_PDFIUM_OK;
  }
  const ShukuPdfiumStatus availability = AvailabilityStatus(
      FPDFAvail_IsDocAvail(document->availability, &document->hints_context.api));
  if (availability != SHUKU_PDFIUM_OK) {
    return availability;
  }
  document->document = FPDFAvail_GetDocument(document->availability, nullptr);
  return document->document == nullptr ? LastDocumentError() : SHUKU_PDFIUM_OK;
}

ShukuPdfiumStatus shuku_pdfium_page_step(ShukuPdfiumDocument* document,
                                         int page_index) {
  if (document == nullptr || document->document == nullptr || page_index < 0 ||
      page_index >= FPDF_GetPageCount(document->document)) {
    return SHUKU_PDFIUM_INVALID_ARGUMENT;
  }
  return AvailabilityStatus(FPDFAvail_IsPageAvail(
      document->availability, page_index, &document->hints_context.api));
}

int shuku_pdfium_page_count(const ShukuPdfiumDocument* document) {
  return document == nullptr || document->document == nullptr
             ? -1
             : FPDF_GetPageCount(document->document);
}

ShukuPdfiumStatus shuku_pdfium_page_size(ShukuPdfiumDocument* document,
                                         int page_index,
                                         ShukuPdfiumPageSize* output) {
  if (output == nullptr) {
    return SHUKU_PDFIUM_INVALID_ARGUMENT;
  }
  FPDF_PAGE page = nullptr;
  const ShukuPdfiumStatus status = LoadPage(document, page_index, &page);
  if (status != SHUKU_PDFIUM_OK) {
    return status;
  }
  output->width_points = FPDF_GetPageWidthF(page);
  output->height_points = FPDF_GetPageHeightF(page);
  FPDF_ClosePage(page);
  return output->width_points > 0 && output->height_points > 0
             ? SHUKU_PDFIUM_OK
             : SHUKU_PDFIUM_INVALID_DOCUMENT;
}

ShukuPdfiumStatus shuku_pdfium_render_page_bgra(
    ShukuPdfiumDocument* document,
    int page_index,
    int width,
    int height,
    int stride,
    uint64_t max_pixels,
    void* destination) {
  if (width <= 0 || height <= 0 || width > INT_MAX / 4 || stride < width * 4 || destination == nullptr ||
      max_pixels == 0) {
    return SHUKU_PDFIUM_INVALID_ARGUMENT;
  }
  const uint64_t pixels = static_cast<uint64_t>(width) * static_cast<uint64_t>(height);
  if (pixels > max_pixels || pixels > std::numeric_limits<size_t>::max() / 4) {
    return SHUKU_PDFIUM_OUT_OF_MEMORY_RISK;
  }
  FPDF_PAGE page = nullptr;
  const ShukuPdfiumStatus status = LoadPage(document, page_index, &page);
  if (status != SHUKU_PDFIUM_OK) {
    return status;
  }
  FPDF_BITMAP bitmap = FPDFBitmap_CreateEx(width, height, FPDFBitmap_BGRA,
                                           destination, stride);
  if (bitmap == nullptr) {
    FPDF_ClosePage(page);
    return SHUKU_PDFIUM_OUT_OF_MEMORY_RISK;
  }
  FPDFBitmap_FillRect(bitmap, 0, 0, width, height, 0xFFFFFFFF);
  FPDF_RenderPageBitmap(bitmap, page, 0, 0, width, height, 0, FPDF_ANNOT);
  FPDFBitmap_Destroy(bitmap);
  FPDF_ClosePage(page);
  return SHUKU_PDFIUM_OK;
}
