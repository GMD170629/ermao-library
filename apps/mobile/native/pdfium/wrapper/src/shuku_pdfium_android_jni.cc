#include <jni.h>

#include <cstdint>
#include <new>

#include "shuku_pdfium.h"
#include "shuku_pdfium_revision.h"

namespace {

JavaVM* g_vm = nullptr;

struct JniDocument {
  jobject source = nullptr;
  jmethodID is_range_cached = nullptr;
  jmethodID read_cached_block = nullptr;
  jmethodID request_range = nullptr;
  ShukuPdfiumDocument* document = nullptr;
};

class ScopedEnvironment {
 public:
  ScopedEnvironment() {
    if (g_vm == nullptr) {
      return;
    }
    if (g_vm->GetEnv(reinterpret_cast<void**>(&environment_), JNI_VERSION_1_6) ==
        JNI_EDETACHED) {
      if (g_vm->AttachCurrentThread(&environment_, nullptr) == JNI_OK) {
        attached_ = true;
      } else {
        environment_ = nullptr;
      }
    }
  }

  ~ScopedEnvironment() {
    if (attached_) {
      g_vm->DetachCurrentThread();
    }
  }

  JNIEnv* get() const { return environment_; }

 private:
  JNIEnv* environment_ = nullptr;
  bool attached_ = false;
};

bool ClearCallbackException(JNIEnv* environment) {
  if (!environment->ExceptionCheck()) {
    return false;
  }
  environment->ExceptionClear();
  return true;
}

int IsRangeCached(void* user_data, uint64_t offset, uint64_t size) {
  auto* document = static_cast<JniDocument*>(user_data);
  ScopedEnvironment scoped_environment;
  JNIEnv* environment = scoped_environment.get();
  if (document == nullptr || environment == nullptr) {
    return 0;
  }
  const jboolean available = environment->CallBooleanMethod(
      document->source, document->is_range_cached, static_cast<jlong>(offset),
      static_cast<jlong>(size));
  return ClearCallbackException(environment) ? 0 : available == JNI_TRUE;
}

int ReadCachedBlock(void* user_data,
                    uint64_t offset,
                    void* destination,
                    uint64_t size) {
  auto* document = static_cast<JniDocument*>(user_data);
  ScopedEnvironment scoped_environment;
  JNIEnv* environment = scoped_environment.get();
  if (document == nullptr || environment == nullptr || destination == nullptr ||
      size > static_cast<uint64_t>(INT32_MAX)) {
    return 0;
  }
  jobject buffer = environment->NewDirectByteBuffer(destination, static_cast<jlong>(size));
  if (buffer == nullptr) {
    ClearCallbackException(environment);
    return 0;
  }
  const jboolean read = environment->CallBooleanMethod(
      document->source, document->read_cached_block, static_cast<jlong>(offset), buffer);
  environment->DeleteLocalRef(buffer);
  return ClearCallbackException(environment) ? 0 : read == JNI_TRUE;
}

void RequestRange(void* user_data, uint64_t offset, uint64_t size) {
  auto* document = static_cast<JniDocument*>(user_data);
  ScopedEnvironment scoped_environment;
  JNIEnv* environment = scoped_environment.get();
  if (document == nullptr || environment == nullptr) {
    return;
  }
  environment->CallVoidMethod(document->source, document->request_range,
                              static_cast<jlong>(offset), static_cast<jlong>(size));
  ClearCallbackException(environment);
}

JniDocument* FromHandle(jlong handle) {
  return reinterpret_cast<JniDocument*>(static_cast<intptr_t>(handle));
}

}  // namespace

extern "C" JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM* vm, void*) {
  g_vm = vm;
  return JNI_VERSION_1_6;
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_ermao_library_pdfium_ShukuPdfiumNative_nativeRevision(JNIEnv* environment,
                                                               jclass) {
  return environment->NewStringUTF(shuku_pdfium_revision());
}

extern "C" JNIEXPORT jint JNICALL
Java_com_ermao_library_pdfium_ShukuPdfiumNative_nativeWrapperAbiVersion(JNIEnv*,
                                                                        jclass) {
  return shuku_pdfium_wrapper_abi_version();
}

extern "C" JNIEXPORT jint JNICALL
Java_com_ermao_library_pdfium_ShukuPdfiumNative_nativeInitialize(JNIEnv*, jclass) {
  return shuku_pdfium_initialize();
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_ermao_library_pdfium_ShukuPdfiumNative_nativeCreateDocument(
    JNIEnv* environment,
    jclass,
    jlong length,
    jobject source) {
  if (length <= 0 || source == nullptr) {
    return 0;
  }
  auto* document = new (std::nothrow) JniDocument();
  if (document == nullptr) {
    return 0;
  }
  document->source = environment->NewGlobalRef(source);
  jclass source_class = environment->GetObjectClass(source);
  if (document->source == nullptr || source_class == nullptr) {
    if (document->source != nullptr) {
      environment->DeleteGlobalRef(document->source);
    }
    delete document;
    return 0;
  }
  document->is_range_cached = environment->GetMethodID(source_class, "isRangeCached", "(JJ)Z");
  document->read_cached_block = environment->GetMethodID(
      source_class, "readCachedBlock", "(JLjava/nio/ByteBuffer;)Z");
  document->request_range = environment->GetMethodID(source_class, "requestRange", "(JJ)V");
  environment->DeleteLocalRef(source_class);
  if (ClearCallbackException(environment) || document->is_range_cached == nullptr ||
      document->read_cached_block == nullptr || document->request_range == nullptr) {
    environment->DeleteGlobalRef(document->source);
    delete document;
    return 0;
  }
  ShukuPdfiumByteSource byte_source{
      static_cast<uint64_t>(length), document, IsRangeCached, ReadCachedBlock,
      RequestRange};
  if (shuku_pdfium_document_create(&byte_source, &document->document) !=
      SHUKU_PDFIUM_OK) {
    environment->DeleteGlobalRef(document->source);
    delete document;
    return 0;
  }
  return static_cast<jlong>(reinterpret_cast<intptr_t>(document));
}

extern "C" JNIEXPORT void JNICALL
Java_com_ermao_library_pdfium_ShukuPdfiumNative_nativeCloseDocument(JNIEnv* environment,
                                                                    jclass,
                                                                    jlong handle) {
  JniDocument* document = FromHandle(handle);
  if (document == nullptr) {
    return;
  }
  shuku_pdfium_document_close(document->document);
  environment->DeleteGlobalRef(document->source);
  delete document;
}

extern "C" JNIEXPORT jint JNICALL
Java_com_ermao_library_pdfium_ShukuPdfiumNative_nativeStepDocument(JNIEnv*,
                                                                   jclass,
                                                                   jlong handle) {
  JniDocument* document = FromHandle(handle);
  return document == nullptr ? SHUKU_PDFIUM_INVALID_ARGUMENT
                             : shuku_pdfium_document_step(document->document);
}

extern "C" JNIEXPORT jint JNICALL
Java_com_ermao_library_pdfium_ShukuPdfiumNative_nativeStepPage(JNIEnv*,
                                                               jclass,
                                                               jlong handle,
                                                               jint page_index) {
  JniDocument* document = FromHandle(handle);
  return document == nullptr
             ? SHUKU_PDFIUM_INVALID_ARGUMENT
             : shuku_pdfium_page_step(document->document, page_index);
}

extern "C" JNIEXPORT jint JNICALL
Java_com_ermao_library_pdfium_ShukuPdfiumNative_nativePageCount(JNIEnv*,
                                                                jclass,
                                                                jlong handle) {
  JniDocument* document = FromHandle(handle);
  return document == nullptr ? -1 : shuku_pdfium_page_count(document->document);
}

extern "C" JNIEXPORT jfloatArray JNICALL
Java_com_ermao_library_pdfium_ShukuPdfiumNative_nativePageSize(JNIEnv* environment,
                                                               jclass,
                                                               jlong handle,
                                                               jint page_index) {
  JniDocument* document = FromHandle(handle);
  ShukuPdfiumPageSize size{};
  if (document == nullptr ||
      shuku_pdfium_page_size(document->document, page_index, &size) != SHUKU_PDFIUM_OK) {
    return nullptr;
  }
  jfloat values[] = {size.width_points, size.height_points};
  jfloatArray result = environment->NewFloatArray(2);
  if (result != nullptr) {
    environment->SetFloatArrayRegion(result, 0, 2, values);
  }
  return result;
}

extern "C" JNIEXPORT jint JNICALL
Java_com_ermao_library_pdfium_ShukuPdfiumNative_nativeRenderPage(
    JNIEnv* environment,
    jclass,
    jlong handle,
    jint page_index,
    jint width,
    jint height,
    jint stride,
    jlong max_pixels,
    jobject destination) {
  JniDocument* document = FromHandle(handle);
  void* pixels = destination == nullptr ? nullptr
                                        : environment->GetDirectBufferAddress(destination);
  const jlong required_capacity =
      stride > 0 && height > 0 ? static_cast<jlong>(stride) * height : -1;
  if (document == nullptr || width <= 0 || height <= 0 || stride <= 0 ||
      max_pixels <= 0 || pixels == nullptr || required_capacity < 0 ||
      environment->GetDirectBufferCapacity(destination) <
          required_capacity) {
    return SHUKU_PDFIUM_INVALID_ARGUMENT;
  }
  return shuku_pdfium_render_page_bgra(
      document->document, page_index, width, height, stride,
      static_cast<uint64_t>(max_pixels), pixels);
}
