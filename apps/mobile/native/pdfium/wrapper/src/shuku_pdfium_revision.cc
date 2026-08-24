#include "shuku_pdfium_revision.h"

#ifndef SHUKU_PDFIUM_RELEASE
#define SHUKU_PDFIUM_RELEASE "875172eae557a308d0c5b2be43822814c8a885bb"
#endif

const char* shuku_pdfium_revision(void) {
  return SHUKU_PDFIUM_RELEASE;
}

int shuku_pdfium_wrapper_abi_version(void) {
  return 1;
}
