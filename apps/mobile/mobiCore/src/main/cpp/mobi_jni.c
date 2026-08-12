#include <jni.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "ermao_mobi.h"

static ErmaoMobiBook *book_from_handle(jlong handle) {
    return (ErmaoMobiBook *) (uintptr_t) handle;
}

static void throw_status(JNIEnv *env, ErmaoMobiStatus status) {
    jclass exception_class = (*env)->FindClass(
        env,
        "com/ermao/library/mobi/infrastructure/MobiCoreException"
    );
    if (exception_class == NULL) {
        return;
    }
    jmethodID constructor = (*env)->GetMethodID(env, exception_class, "<init>", "(I)V");
    if (constructor == NULL) {
        return;
    }
    jobject exception = (*env)->NewObject(env, exception_class, constructor, (jint) status);
    if (exception != NULL) {
        (*env)->Throw(env, (jthrowable) exception);
    }
}

static jstring new_utf8_string(JNIEnv *env, const char *utf8, uint32_t byte_count) {
    if (byte_count == 0u) {
        return (*env)->NewStringUTF(env, "");
    }
    jbyteArray bytes = (*env)->NewByteArray(env, (jsize) byte_count);
    if (bytes == NULL) {
        return NULL;
    }
    (*env)->SetByteArrayRegion(env, bytes, 0, (jsize) byte_count, (const jbyte *) utf8);
    jclass string_class = (*env)->FindClass(env, "java/lang/String");
    if (string_class == NULL) {
        return NULL;
    }
    jmethodID constructor = (*env)->GetMethodID(
        env,
        string_class,
        "<init>",
        "([BLjava/lang/String;)V"
    );
    if (constructor == NULL) {
        return NULL;
    }
    jstring charset = (*env)->NewStringUTF(env, "UTF-8");
    if (charset == NULL) {
        return NULL;
    }
    return (jstring) (*env)->NewObject(env, string_class, constructor, bytes, charset);
}

static jstring copy_string_result(
    JNIEnv *env,
    ErmaoMobiStatus (*copy_function)(
        const ErmaoMobiBook *, uint32_t, char *, uint32_t, uint32_t *
    ),
    const ErmaoMobiBook *book,
    uint32_t index
) {
    uint32_t required = 0u;
    ErmaoMobiStatus status = copy_function(book, index, NULL, 0u, &required);
    if (status == ERMAO_MOBI_NOT_FOUND) {
        return NULL;
    }
    if (status != ERMAO_MOBI_BUFFER_TOO_SMALL || required == 0u) {
        throw_status(env, status);
        return NULL;
    }
    char *buffer = malloc(required);
    if (buffer == NULL) {
        throw_status(env, ERMAO_MOBI_OUT_OF_MEMORY);
        return NULL;
    }
    status = copy_function(book, index, buffer, required, &required);
    jstring result = NULL;
    if (status == ERMAO_MOBI_OK) {
        result = new_utf8_string(env, buffer, required - 1u);
    } else {
        throw_status(env, status);
    }
    free(buffer);
    return result;
}

JNIEXPORT jint JNICALL
Java_com_ermao_library_mobi_infrastructure_MobiCoreNative_abiVersion(
    JNIEnv *env,
    jobject receiver
) {
    (void) env;
    (void) receiver;
    return (jint) ermao_mobi_abi_version();
}

JNIEXPORT jstring JNICALL
Java_com_ermao_library_mobi_infrastructure_MobiCoreNative_parserIdentifier(
    JNIEnv *env,
    jobject receiver
) {
    (void) receiver;
    const char *identifier = ermao_mobi_parser_identifier();
    return new_utf8_string(env, identifier, (uint32_t) strlen(identifier));
}

JNIEXPORT jstring JNICALL
Java_com_ermao_library_mobi_infrastructure_MobiCoreNative_normalizationIdentifier(
    JNIEnv *env,
    jobject receiver
) {
    (void) receiver;
    const char *identifier = ermao_mobi_normalization_identifier();
    return new_utf8_string(env, identifier, (uint32_t) strlen(identifier));
}

JNIEXPORT jlong JNICALL
Java_com_ermao_library_mobi_infrastructure_MobiCoreNative_open(
    JNIEnv *env,
    jobject receiver,
    jbyteArray path
) {
    (void) receiver;
    if (path == NULL) {
        throw_status(env, ERMAO_MOBI_INVALID_ARGUMENT);
        return 0;
    }
    const jsize path_length = (*env)->GetArrayLength(env, path);
    if (path_length <= 0) {
        throw_status(env, ERMAO_MOBI_INVALID_ARGUMENT);
        return 0;
    }
    char *utf8_path = malloc((size_t) path_length + 1u);
    if (utf8_path == NULL) {
        throw_status(env, ERMAO_MOBI_OUT_OF_MEMORY);
        return 0;
    }
    (*env)->GetByteArrayRegion(env, path, 0, path_length, (jbyte *) utf8_path);
    utf8_path[path_length] = '\0';
    if (memchr(utf8_path, '\0', (size_t) path_length) != NULL) {
        free(utf8_path);
        throw_status(env, ERMAO_MOBI_INVALID_ARGUMENT);
        return 0;
    }
    ErmaoMobiBook *book = NULL;
    const ErmaoMobiStatus status = ermao_mobi_open(utf8_path, NULL, &book);
    free(utf8_path);
    if (status != ERMAO_MOBI_OK) {
        throw_status(env, status);
        return 0;
    }
    return (jlong) (uintptr_t) book;
}

JNIEXPORT void JNICALL
Java_com_ermao_library_mobi_infrastructure_MobiCoreNative_close(
    JNIEnv *env,
    jobject receiver,
    jlong handle
) {
    (void) env;
    (void) receiver;
    ErmaoMobiBook *book = book_from_handle(handle);
    ermao_mobi_close(&book);
}

JNIEXPORT jlongArray JNICALL
Java_com_ermao_library_mobi_infrastructure_MobiCoreNative_bookInfo(
    JNIEnv *env,
    jobject receiver,
    jlong handle
) {
    (void) receiver;
    ErmaoMobiBookInfo info = {.struct_size = sizeof(info)};
    const ErmaoMobiStatus status = ermao_mobi_get_book_info(book_from_handle(handle), &info);
    if (status != ERMAO_MOBI_OK) {
        throw_status(env, status);
        return NULL;
    }
    const jlong values[] = {
        (jlong) info.format,
        (jlong) info.reading_direction,
        (jlong) info.resource_count,
        (jlong) info.reading_order_count,
        (jlong) info.toc_count,
        (jlong) info.warning_count,
        (jlong) info.cover_resource_index,
        (jlong) ermao_mobi_abi_version(),
    };
    jlongArray array = (*env)->NewLongArray(env, 8);
    if (array != NULL) {
        (*env)->SetLongArrayRegion(env, array, 0, 8, values);
    }
    return array;
}

JNIEXPORT jstring JNICALL
Java_com_ermao_library_mobi_infrastructure_MobiCoreNative_metadata(
    JNIEnv *env,
    jobject receiver,
    jlong handle,
    jint field
) {
    (void) receiver;
    uint32_t required = 0u;
    ErmaoMobiBook *book = book_from_handle(handle);
    ErmaoMobiStatus status = ermao_mobi_copy_metadata(
        book,
        (ErmaoMobiMetadataField) field,
        NULL,
        0u,
        &required
    );
    if (status == ERMAO_MOBI_NOT_FOUND) {
        return NULL;
    }
    if (status != ERMAO_MOBI_BUFFER_TOO_SMALL || required == 0u) {
        throw_status(env, status);
        return NULL;
    }
    char *buffer = malloc(required);
    if (buffer == NULL) {
        throw_status(env, ERMAO_MOBI_OUT_OF_MEMORY);
        return NULL;
    }
    status = ermao_mobi_copy_metadata(
        book,
        (ErmaoMobiMetadataField) field,
        buffer,
        required,
        &required
    );
    jstring result = NULL;
    if (status == ERMAO_MOBI_OK) {
        result = new_utf8_string(env, buffer, required - 1u);
    } else {
        throw_status(env, status);
    }
    free(buffer);
    return result;
}

JNIEXPORT jlongArray JNICALL
Java_com_ermao_library_mobi_infrastructure_MobiCoreNative_resourceInfo(
    JNIEnv *env,
    jobject receiver,
    jlong handle,
    jint index
) {
    (void) receiver;
    ErmaoMobiResourceInfo info = {.struct_size = sizeof(info)};
    const ErmaoMobiStatus status = ermao_mobi_get_resource_info(
        book_from_handle(handle),
        (uint32_t) index,
        &info
    );
    if (status != ERMAO_MOBI_OK) {
        throw_status(env, status);
        return NULL;
    }
    const jlong values[] = {
        (jlong) info.category,
        (jlong) info.source_uid,
        (jlong) info.decoded_length,
    };
    jlongArray array = (*env)->NewLongArray(env, 3);
    if (array != NULL) {
        (*env)->SetLongArrayRegion(env, array, 0, 3, values);
    }
    return array;
}

JNIEXPORT jstring JNICALL
Java_com_ermao_library_mobi_infrastructure_MobiCoreNative_resourceSourceName(
    JNIEnv *env,
    jobject receiver,
    jlong handle,
    jint index
) {
    (void) receiver;
    return copy_string_result(
        env,
        ermao_mobi_copy_resource_source_name,
        book_from_handle(handle),
        (uint32_t) index
    );
}

JNIEXPORT jstring JNICALL
Java_com_ermao_library_mobi_infrastructure_MobiCoreNative_resourceMediaType(
    JNIEnv *env,
    jobject receiver,
    jlong handle,
    jint index
) {
    (void) receiver;
    return copy_string_result(
        env,
        ermao_mobi_copy_resource_media_type,
        book_from_handle(handle),
        (uint32_t) index
    );
}

JNIEXPORT jbyteArray JNICALL
Java_com_ermao_library_mobi_infrastructure_MobiCoreNative_readResource(
    JNIEnv *env,
    jobject receiver,
    jlong handle,
    jint index,
    jlong offset,
    jint length
) {
    (void) receiver;
    if (offset < 0 || length < 0) {
        throw_status(env, ERMAO_MOBI_INVALID_ARGUMENT);
        return NULL;
    }
    uint8_t *buffer = length == 0 ? NULL : malloc((size_t) length);
    if (length > 0 && buffer == NULL) {
        throw_status(env, ERMAO_MOBI_OUT_OF_MEMORY);
        return NULL;
    }
    uint32_t bytes_read = 0u;
    const ErmaoMobiStatus status = ermao_mobi_read_resource(
        book_from_handle(handle),
        (uint32_t) index,
        (uint64_t) offset,
        buffer,
        (uint32_t) length,
        &bytes_read
    );
    if (status != ERMAO_MOBI_OK) {
        free(buffer);
        throw_status(env, status);
        return NULL;
    }
    jbyteArray result = (*env)->NewByteArray(env, (jsize) bytes_read);
    if (result != NULL && bytes_read > 0u) {
        (*env)->SetByteArrayRegion(env, result, 0, (jsize) bytes_read, (const jbyte *) buffer);
    }
    free(buffer);
    return result;
}

JNIEXPORT jint JNICALL
Java_com_ermao_library_mobi_infrastructure_MobiCoreNative_readingOrderResourceIndex(
    JNIEnv *env,
    jobject receiver,
    jlong handle,
    jint position
) {
    (void) receiver;
    uint32_t resource_index = ERMAO_MOBI_INDEX_NONE;
    const ErmaoMobiStatus status = ermao_mobi_reading_order_resource_index(
        book_from_handle(handle),
        (uint32_t) position,
        &resource_index
    );
    if (status != ERMAO_MOBI_OK) {
        throw_status(env, status);
        return -1;
    }
    return (jint) resource_index;
}

JNIEXPORT jlongArray JNICALL
Java_com_ermao_library_mobi_infrastructure_MobiCoreNative_tocInfo(
    JNIEnv *env,
    jobject receiver,
    jlong handle,
    jint index
) {
    (void) receiver;
    ErmaoMobiTocInfo info = {.struct_size = sizeof(info)};
    const ErmaoMobiStatus status = ermao_mobi_get_toc_info(
        book_from_handle(handle),
        (uint32_t) index,
        &info
    );
    if (status != ERMAO_MOBI_OK) {
        throw_status(env, status);
        return NULL;
    }
    const jlong values[] = {(jlong) info.parent_index, (jlong) info.target_resource_index};
    jlongArray array = (*env)->NewLongArray(env, 2);
    if (array != NULL) {
        (*env)->SetLongArrayRegion(env, array, 0, 2, values);
    }
    return array;
}

JNIEXPORT jstring JNICALL
Java_com_ermao_library_mobi_infrastructure_MobiCoreNative_tocTitle(
    JNIEnv *env,
    jobject receiver,
    jlong handle,
    jint index
) {
    (void) receiver;
    return copy_string_result(
        env,
        ermao_mobi_copy_toc_title,
        book_from_handle(handle),
        (uint32_t) index
    );
}

JNIEXPORT jstring JNICALL
Java_com_ermao_library_mobi_infrastructure_MobiCoreNative_tocFragment(
    JNIEnv *env,
    jobject receiver,
    jlong handle,
    jint index
) {
    (void) receiver;
    return copy_string_result(
        env,
        ermao_mobi_copy_toc_fragment,
        book_from_handle(handle),
        (uint32_t) index
    );
}

JNIEXPORT jlongArray JNICALL
Java_com_ermao_library_mobi_infrastructure_MobiCoreNative_warningInfo(
    JNIEnv *env,
    jobject receiver,
    jlong handle,
    jint index
) {
    (void) receiver;
    ErmaoMobiWarningInfo info = {.struct_size = sizeof(info)};
    const ErmaoMobiStatus status = ermao_mobi_get_warning_info(
        book_from_handle(handle),
        (uint32_t) index,
        &info
    );
    if (status != ERMAO_MOBI_OK) {
        throw_status(env, status);
        return NULL;
    }
    const jlong values[] = {(jlong) info.code, (jlong) info.related_index};
    jlongArray array = (*env)->NewLongArray(env, 2);
    if (array != NULL) {
        (*env)->SetLongArrayRegion(env, array, 0, 2, values);
    }
    return array;
}
