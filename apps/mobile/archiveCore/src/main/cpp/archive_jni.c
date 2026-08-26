#include <jni.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "archive_core.h"

static ermao_archive *archive_from_handle(jlong handle) {
    return (ermao_archive *)(uintptr_t)handle;
}

static void throw_error(JNIEnv *env, const ermao_archive_error *error) {
    jclass exception_class = (*env)->FindClass(
        env, "com/ermao/library/archive/infrastructure/ArchiveCoreException"
    );
    jmethodID constructor;
    jstring code;
    jstring message;
    jobject exception;
    if (exception_class == NULL) return;
    constructor = (*env)->GetMethodID(
        env, exception_class, "<init>", "(Ljava/lang/String;Ljava/lang/String;)V"
    );
    if (constructor == NULL) return;
    code = (*env)->NewStringUTF(env, error->code[0] == '\0' ? "ARCHIVE_ERROR" : error->code);
    message = (*env)->NewStringUTF(env, error->message[0] == '\0' ? "Archive operation failed" : error->message);
    if (code == NULL || message == NULL) return;
    exception = (*env)->NewObject(env, exception_class, constructor, code, message);
    if (exception != NULL) (*env)->Throw(env, (jthrowable)exception);
}

static jstring utf8_string(JNIEnv *env, const char *value) {
    size_t length = strlen(value);
    jbyteArray bytes = (*env)->NewByteArray(env, (jsize)length);
    jclass string_class;
    jmethodID constructor;
    jstring charset;
    if (bytes == NULL) return NULL;
    (*env)->SetByteArrayRegion(env, bytes, 0, (jsize)length, (const jbyte *)value);
    string_class = (*env)->FindClass(env, "java/lang/String");
    if (string_class == NULL) return NULL;
    constructor = (*env)->GetMethodID(env, string_class, "<init>", "([BLjava/lang/String;)V");
    if (constructor == NULL) return NULL;
    charset = (*env)->NewStringUTF(env, "UTF-8");
    if (charset == NULL) return NULL;
    return (jstring)(*env)->NewObject(env, string_class, constructor, bytes, charset);
}

JNIEXPORT jstring JNICALL
Java_com_ermao_library_archive_infrastructure_ArchiveCoreNative_version(JNIEnv *env, jobject receiver) {
    (void)receiver;
    return utf8_string(env, ermao_archive_version());
}

JNIEXPORT jlong JNICALL
Java_com_ermao_library_archive_infrastructure_ArchiveCoreNative_open(
    JNIEnv *env, jobject receiver, jbyteArray path
) {
    ermao_archive_limits limits = {10000U, 64LL * 1024LL * 1024LL, 4LL * 1024LL * 1024LL * 1024LL};
    ermao_archive_error error = {{0}, {0}};
    ermao_archive *archive = NULL;
    jsize path_length;
    char *utf8_path;
    (void)receiver;
    if (path == NULL || (path_length = (*env)->GetArrayLength(env, path)) <= 0) {
        strcpy(error.code, "ARCHIVE_ARGUMENT_INVALID");
        strcpy(error.message, "Archive path is invalid");
        throw_error(env, &error);
        return 0;
    }
    utf8_path = malloc((size_t)path_length + 1U);
    if (utf8_path == NULL) {
        strcpy(error.code, "ARCHIVE_OUT_OF_MEMORY");
        strcpy(error.message, "Unable to allocate archive path");
        throw_error(env, &error);
        return 0;
    }
    (*env)->GetByteArrayRegion(env, path, 0, path_length, (jbyte *)utf8_path);
    utf8_path[path_length] = '\0';
    if (memchr(utf8_path, '\0', (size_t)path_length) != NULL ||
        !ermao_archive_open(utf8_path, limits, &archive, &error)) {
        free(utf8_path);
        if (error.code[0] == '\0') {
            strcpy(error.code, "ARCHIVE_ARGUMENT_INVALID");
            strcpy(error.message, "Archive path contains an embedded NUL");
        }
        throw_error(env, &error);
        return 0;
    }
    free(utf8_path);
    return (jlong)(uintptr_t)archive;
}

JNIEXPORT void JNICALL
Java_com_ermao_library_archive_infrastructure_ArchiveCoreNative_close(
    JNIEnv *env, jobject receiver, jlong handle
) {
    (void)env;
    (void)receiver;
    ermao_archive_close(archive_from_handle(handle));
}

JNIEXPORT jint JNICALL
Java_com_ermao_library_archive_infrastructure_ArchiveCoreNative_pageCount(
    JNIEnv *env, jobject receiver, jlong handle
) {
    (void)env;
    (void)receiver;
    return (jint)ermao_archive_page_count(archive_from_handle(handle));
}

JNIEXPORT jstring JNICALL
Java_com_ermao_library_archive_infrastructure_ArchiveCoreNative_pagePath(
    JNIEnv *env, jobject receiver, jlong handle, jint index
) {
    ermao_archive_error error = {{0}, {0}};
    const char *path = NULL;
    int64_t size = 0;
    (void)receiver;
    if (index < 0 || !ermao_archive_page_info(archive_from_handle(handle), (size_t)index, &path, &size, &error)) {
        throw_error(env, &error);
        return NULL;
    }
    return utf8_string(env, path);
}

JNIEXPORT jlong JNICALL
Java_com_ermao_library_archive_infrastructure_ArchiveCoreNative_pageSize(
    JNIEnv *env, jobject receiver, jlong handle, jint index
) {
    ermao_archive_error error = {{0}, {0}};
    const char *path = NULL;
    int64_t size = 0;
    (void)receiver;
    if (index < 0 || !ermao_archive_page_info(archive_from_handle(handle), (size_t)index, &path, &size, &error)) {
        throw_error(env, &error);
        return 0;
    }
    return (jlong)size;
}

JNIEXPORT jbyteArray JNICALL
Java_com_ermao_library_archive_infrastructure_ArchiveCoreNative_readPage(
    JNIEnv *env, jobject receiver, jlong handle, jint index
) {
    ermao_archive_error error = {{0}, {0}};
    const char *path = NULL;
    int64_t size = 0;
    unsigned char *buffer;
    size_t written = 0;
    jbyteArray result;
    (void)receiver;
    if (index < 0 || !ermao_archive_page_info(archive_from_handle(handle), (size_t)index, &path, &size, &error) ||
        size <= 0 || size > INT32_MAX) {
        if (error.code[0] == '\0') {
            strcpy(error.code, "ARCHIVE_PAGE_LIMIT_EXCEEDED");
            strcpy(error.message, "Archive page is too large");
        }
        throw_error(env, &error);
        return NULL;
    }
    buffer = malloc((size_t)size);
    if (buffer == NULL || !ermao_archive_read_page(
            archive_from_handle(handle), (size_t)index, buffer, (size_t)size, &written, &error
        )) {
        free(buffer);
        if (error.code[0] == '\0') {
            strcpy(error.code, "ARCHIVE_OUT_OF_MEMORY");
            strcpy(error.message, "Unable to allocate archive page");
        }
        throw_error(env, &error);
        return NULL;
    }
    result = (*env)->NewByteArray(env, (jsize)written);
    if (result != NULL) (*env)->SetByteArrayRegion(env, result, 0, (jsize)written, (const jbyte *)buffer);
    free(buffer);
    return result;
}
