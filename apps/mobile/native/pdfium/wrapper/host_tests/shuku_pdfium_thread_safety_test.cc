#include "shuku_pdfium.h"

#include <public/fpdf_dataavail.h>
#include <public/fpdfview.h>

#include <assert.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <thread>
#include <vector>

namespace {

std::atomic<int> g_active_pdfium_calls{0};
std::atomic<int> g_max_active_pdfium_calls{0};

void EnterFakePdfiumCall() {
  const int active = g_active_pdfium_calls.fetch_add(1) + 1;
  int observed = g_max_active_pdfium_calls.load();
  while (active > observed &&
         !g_max_active_pdfium_calls.compare_exchange_weak(observed, active)) {
  }
  // Make an accidental missing wrapper lock observable under every scheduler.
  std::this_thread::sleep_for(std::chrono::milliseconds(1));
}

void ExitFakePdfiumCall() {
  g_active_pdfium_calls.fetch_sub(1);
}

struct SourceState {
  std::atomic<int> availability_callbacks{0};
  std::atomic<int> read_callbacks{0};
  std::atomic<int> request_callbacks{0};
};

int IsRangeCached(void* user_data, uint64_t, uint64_t) {
  auto* state = static_cast<SourceState*>(user_data);
  state->availability_callbacks.fetch_add(1);
  return 1;
}

int ReadCachedBlock(void* user_data,
                    uint64_t,
                    void* destination,
                    uint64_t size) {
  auto* state = static_cast<SourceState*>(user_data);
  state->read_callbacks.fetch_add(1);
  std::memset(destination, 0, static_cast<size_t>(size));
  return 1;
}

void RequestRange(void* user_data, uint64_t, uint64_t) {
  auto* state = static_cast<SourceState*>(user_data);
  state->request_callbacks.fetch_add(1);
}

}  // namespace

// This test links shuku_pdfium.cc against the real public PDFium headers but
// replaces the PDFium implementation with deliberately slow fake calls. It
// therefore tests the wrapper's serialization contract without requiring a
// device or a platform PDFium binary.
struct fpdf_avail_t__ {
  FPDF_FILEACCESS* file = nullptr;
};

struct fpdf_document_t__ {};
struct fpdf_page_t__ {};
struct fpdf_bitmap_t__ {};

extern "C" {

void FPDF_CALLCONV FPDF_InitLibraryWithConfig(const FPDF_LIBRARY_CONFIG*) {
  EnterFakePdfiumCall();
  ExitFakePdfiumCall();
}

void FPDF_CALLCONV FPDF_DestroyLibrary() {
  EnterFakePdfiumCall();
  ExitFakePdfiumCall();
}

unsigned long FPDF_CALLCONV FPDF_GetLastError() {
  EnterFakePdfiumCall();
  ExitFakePdfiumCall();
  return FPDF_ERR_SUCCESS;
}

FPDF_AVAIL FPDF_CALLCONV FPDFAvail_Create(FX_FILEAVAIL* file_avail,
                                          FPDF_FILEACCESS* file) {
  EnterFakePdfiumCall();
  auto* availability = new fpdf_avail_t__();
  availability->file = file;
  assert(file_avail != nullptr);
  ExitFakePdfiumCall();
  return availability;
}

void FPDF_CALLCONV FPDFAvail_Destroy(FPDF_AVAIL avail) {
  EnterFakePdfiumCall();
  delete avail;
  ExitFakePdfiumCall();
}

int FPDF_CALLCONV FPDFAvail_IsDocAvail(FPDF_AVAIL avail,
                                       FX_DOWNLOADHINTS* hints) {
  EnterFakePdfiumCall();
  assert(avail != nullptr);
  if (hints != nullptr && hints->AddSegment != nullptr) {
    // This is deliberately synchronous, matching PDFium's callback contract.
    hints->AddSegment(hints, 0, 1);
  }
  ExitFakePdfiumCall();
  return PDF_DATA_AVAIL;
}

FPDF_DOCUMENT FPDF_CALLCONV FPDFAvail_GetDocument(FPDF_AVAIL avail,
                                                   FPDF_BYTESTRING) {
  EnterFakePdfiumCall();
  assert(avail != nullptr);
  auto* document = new fpdf_document_t__();
  ExitFakePdfiumCall();
  return document;
}

int FPDF_CALLCONV FPDFAvail_IsPageAvail(FPDF_AVAIL avail,
                                        int,
                                        FX_DOWNLOADHINTS*) {
  EnterFakePdfiumCall();
  assert(avail != nullptr);
  ExitFakePdfiumCall();
  return PDF_DATA_AVAIL;
}

int FPDF_CALLCONV FPDF_GetPageCount(FPDF_DOCUMENT document) {
  EnterFakePdfiumCall();
  assert(document != nullptr);
  ExitFakePdfiumCall();
  return 1;
}

FPDF_PAGE FPDF_CALLCONV FPDF_LoadPage(FPDF_DOCUMENT document, int) {
  EnterFakePdfiumCall();
  assert(document != nullptr);
  auto* page = new fpdf_page_t__();
  ExitFakePdfiumCall();
  return page;
}

float FPDF_CALLCONV FPDF_GetPageWidthF(FPDF_PAGE page) {
  EnterFakePdfiumCall();
  assert(page != nullptr);
  ExitFakePdfiumCall();
  return 612.0F;
}

float FPDF_CALLCONV FPDF_GetPageHeightF(FPDF_PAGE page) {
  EnterFakePdfiumCall();
  assert(page != nullptr);
  ExitFakePdfiumCall();
  return 792.0F;
}

void FPDF_CALLCONV FPDF_ClosePage(FPDF_PAGE page) {
  EnterFakePdfiumCall();
  delete page;
  ExitFakePdfiumCall();
}

FPDF_BITMAP FPDF_CALLCONV FPDFBitmap_CreateEx(int width,
                                              int height,
                                              int,
                                              void*,
                                              int stride) {
  EnterFakePdfiumCall();
  assert(width > 0);
  assert(height > 0);
  assert(stride >= width * 4);
  auto* bitmap = new fpdf_bitmap_t__();
  ExitFakePdfiumCall();
  return bitmap;
}

FPDF_BOOL FPDF_CALLCONV FPDFBitmap_FillRect(FPDF_BITMAP bitmap,
                                            int,
                                            int,
                                            int,
                                            int,
                                            FPDF_DWORD) {
  EnterFakePdfiumCall();
  assert(bitmap != nullptr);
  ExitFakePdfiumCall();
  return 1;
}

void FPDF_CALLCONV FPDF_RenderPageBitmap(FPDF_BITMAP bitmap,
                                         FPDF_PAGE page,
                                         int,
                                         int,
                                         int,
                                         int,
                                         int,
                                         int) {
  EnterFakePdfiumCall();
  assert(bitmap != nullptr);
  assert(page != nullptr);
  ExitFakePdfiumCall();
}

void FPDF_CALLCONV FPDFBitmap_Destroy(FPDF_BITMAP bitmap) {
  EnterFakePdfiumCall();
  delete bitmap;
  ExitFakePdfiumCall();
}

void FPDF_CALLCONV FPDF_CloseDocument(FPDF_DOCUMENT document) {
  EnterFakePdfiumCall();
  delete document;
  ExitFakePdfiumCall();
}

}  // extern "C"

int main() {
  constexpr int kDocumentCount = 8;
  assert(shuku_pdfium_initialize() == SHUKU_PDFIUM_OK);

  std::vector<ShukuPdfiumDocument*> documents;
  documents.reserve(kDocumentCount);
  std::vector<SourceState> sources(kDocumentCount);
  for (int index = 0; index < kDocumentCount; ++index) {
    ShukuPdfiumByteSource source{
        4096,
        &sources[index],
        IsRangeCached,
        ReadCachedBlock,
        RequestRange,
    };
    ShukuPdfiumDocument* document = nullptr;
    assert(shuku_pdfium_document_create(&source, &document) == SHUKU_PDFIUM_OK);
    assert(document != nullptr);
    documents.push_back(document);
  }

  std::atomic<bool> start{false};
  std::vector<std::thread> workers;
  workers.reserve(kDocumentCount);
  for (int index = 0; index < kDocumentCount; ++index) {
    workers.emplace_back([&, index] {
      while (!start.load(std::memory_order_acquire)) {
        std::this_thread::yield();
      }
      assert(shuku_pdfium_document_step(documents[index]) == SHUKU_PDFIUM_OK);
      assert(shuku_pdfium_page_step(documents[index], 0) == SHUKU_PDFIUM_OK);
      assert(shuku_pdfium_page_count(documents[index]) == 1);

      ShukuPdfiumPageSize page_size{};
      assert(shuku_pdfium_page_size(documents[index], 0, &page_size) ==
             SHUKU_PDFIUM_OK);
      assert(page_size.width_points == 612.0F);
      assert(page_size.height_points == 792.0F);

      std::vector<uint8_t> pixels(4 * 4 * 4);
      assert(shuku_pdfium_render_page_bgra(
                 documents[index], 0, 4, 4, 16, pixels.size(), pixels.data()) ==
             SHUKU_PDFIUM_OK);
    });
  }
  start.store(true, std::memory_order_release);
  for (auto& worker : workers) {
    worker.join();
  }

  std::vector<std::thread> closers;
  closers.reserve(kDocumentCount);
  for (ShukuPdfiumDocument* document : documents) {
    closers.emplace_back([document] { shuku_pdfium_document_close(document); });
  }
  for (auto& closer : closers) {
    closer.join();
  }

  shuku_pdfium_shutdown();

  assert(g_max_active_pdfium_calls.load() == 1);
  for (const SourceState& source : sources) {
    assert(source.request_callbacks.load() > 0);
  }
  std::puts("shuku_pdfium_thread_safety_test: ok (max PDFium calls: 1)");
  return 0;
}
