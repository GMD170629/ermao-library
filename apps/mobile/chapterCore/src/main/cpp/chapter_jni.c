#include <jni.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "ermao_chapters.h"

static ErmaoChapterResult *result_from_handle(jlong handle) {
    return (ErmaoChapterResult *)(uintptr_t)handle;
}

static jstring utf8_string(JNIEnv *env, const char *value) {
    jclass string_class = NULL;
    jmethodID constructor;
    jbyteArray bytes = NULL;
    jstring charset = NULL;
    jstring output = NULL;
    size_t length;
    if (value == NULL) return NULL;
    length = strlen(value);
    if (length > INT32_MAX) goto cleanup;
    bytes = (*env)->NewByteArray(env, (jsize)length);
    if (bytes == NULL) goto cleanup;
    (*env)->SetByteArrayRegion(env, bytes, 0, (jsize)length, (const jbyte *)value);
    if ((*env)->ExceptionCheck(env)) goto cleanup;
    string_class = (*env)->FindClass(env, "java/lang/String");
    if (string_class == NULL) goto cleanup;
    constructor = (*env)->GetMethodID(env, string_class, "<init>", "([BLjava/lang/String;)V");
    if (constructor == NULL) goto cleanup;
    charset = (*env)->NewStringUTF(env, "UTF-8");
    if (charset == NULL) goto cleanup;
    output = (jstring)(*env)->NewObject(env, string_class, constructor, bytes, charset);

cleanup:
    if (charset != NULL) (*env)->DeleteLocalRef(env, charset);
    if (bytes != NULL) (*env)->DeleteLocalRef(env, bytes);
    if (string_class != NULL) (*env)->DeleteLocalRef(env, string_class);
    return output;
}

/* GetStringUTFChars exposes JNI's modified UTF-8, while the chapter ABI
 * requires ordinary UTF-8. Let the Java runtime perform the UTF-16 -> UTF-8
 * conversion so supplementary characters and embedded NULs are handled by
 * the platform contract rather than by a second native encoder. */
static char *copy_java_utf8(JNIEnv *env, jstring value) {
    jclass string_class = NULL;
    jclass standard_charsets = NULL;
    jobject charset = NULL;
    jbyteArray bytes = NULL;
    jfieldID utf8_field;
    jmethodID get_bytes;
    jsize length;
    char *output = NULL;

    if (value == NULL) return NULL;
    string_class = (*env)->FindClass(env, "java/lang/String");
    standard_charsets = (*env)->FindClass(env, "java/nio/charset/StandardCharsets");
    if (string_class == NULL || standard_charsets == NULL) goto cleanup;
    utf8_field = (*env)->GetStaticFieldID(
        env, standard_charsets, "UTF_8", "Ljava/nio/charset/Charset;");
    get_bytes = (*env)->GetMethodID(
        env, string_class, "getBytes", "(Ljava/nio/charset/Charset;)[B");
    if (utf8_field == NULL || get_bytes == NULL) goto cleanup;
    charset = (*env)->GetStaticObjectField(env, standard_charsets, utf8_field);
    if (charset == NULL) goto cleanup;
    bytes = (jbyteArray)(*env)->CallObjectMethod(env, value, get_bytes, charset);
    if (bytes == NULL || (*env)->ExceptionCheck(env)) goto cleanup;
    length = (*env)->GetArrayLength(env, bytes);
    if (length < 0 || (size_t)length > SIZE_MAX - 1U) goto cleanup;
    output = (char *)malloc((size_t)length + 1U);
    if (output == NULL) goto cleanup;
    if (length != 0) {
        (*env)->GetByteArrayRegion(env, bytes, 0, length, (jbyte *)output);
        if ((*env)->ExceptionCheck(env)) {
            free(output);
            output = NULL;
            goto cleanup;
        }
    }
    output[length] = '\0';

cleanup:
    if (bytes != NULL) (*env)->DeleteLocalRef(env, bytes);
    if (charset != NULL) (*env)->DeleteLocalRef(env, charset);
    if (standard_charsets != NULL) (*env)->DeleteLocalRef(env, standard_charsets);
    if (string_class != NULL) (*env)->DeleteLocalRef(env, string_class);
    return output;
}

static jlong parse_status(JNIEnv *env, ErmaoChapterStatus status, ErmaoChapterResult *result) {
    if (status == ERMAO_CHAPTER_OK) return (jlong)(uintptr_t)result;
    if (status == ERMAO_CHAPTER_OUT_OF_MEMORY) {
        jclass error = (*env)->FindClass(env, "java/lang/OutOfMemoryError");
        if (error != NULL) (*env)->ThrowNew(env, error, "Chapter core allocation failed");
    } else {
        jclass error = (*env)->FindClass(env, "java/lang/IllegalArgumentException");
        if (error != NULL) (*env)->ThrowNew(env, error, "Chapter core input is invalid");
    }
    return 0;
}

typedef struct {
    char *name_utf8;
    char *text_utf8;
    char *href_utf8;
    char **attribute_names;
    char **attribute_values;
    ErmaoChapterAttribute *attributes;
    jsize attribute_count;
} XmlEventStorage;

static void release_xml_storage(JNIEnv *env, XmlEventStorage *storage, jsize count) {
    jsize i;
    jsize attribute;
    (void)env;
    if (storage == NULL) return;
    for (i = 0; i < count; ++i) {
        XmlEventStorage *item = &storage[i];
        free(item->name_utf8);
        free(item->text_utf8);
        free(item->href_utf8);
        for (attribute = 0; attribute < item->attribute_count; ++attribute) {
            if (item->attribute_names != NULL) free(item->attribute_names[attribute]);
            if (item->attribute_values != NULL) free(item->attribute_values[attribute]);
        }
        free(item->attribute_names);
        free(item->attribute_values);
        free(item->attributes);
    }
}

static void throw_chapter_error(JNIEnv *env, const char *message, bool out_of_memory) {
    jclass error = (*env)->FindClass(env, out_of_memory ?
        "java/lang/OutOfMemoryError" : "java/lang/IllegalArgumentException");
    if (error != NULL) (*env)->ThrowNew(env, error, message);
}

JNIEXPORT jint JNICALL
Java_com_ermao_library_chapter_infrastructure_ChapterCoreNative_abiVersion(
    JNIEnv *env, jobject receiver
) {
    (void)env;
    (void)receiver;
    return (jint)ermao_chapters_abi_version();
}

JNIEXPORT jlong JNICALL
Java_com_ermao_library_chapter_infrastructure_ChapterCoreNative_parseTxt(
    JNIEnv *env, jobject receiver, jbyteArray input
) {
    jsize length;
    jbyte *bytes;
    ErmaoChapterResult *result = NULL;
    ErmaoChapterStatus status = ERMAO_CHAPTER_INVALID_INPUT;
    (void)receiver;
    if (input == NULL) {
        jclass error = (*env)->FindClass(env, "java/lang/IllegalArgumentException");
        if (error != NULL) (*env)->ThrowNew(env, error, "TXT input is null");
        return 0;
    }
    length = (*env)->GetArrayLength(env, input);
    bytes = (*env)->GetByteArrayElements(env, input, NULL);
    if (bytes == NULL) return 0;
    status = ermao_chapters_parse_txt((const uint8_t *)bytes, (uint64_t)length, &result);
    (*env)->ReleaseByteArrayElements(env, input, bytes, JNI_ABORT);
    return parse_status(env, status, result);
}

JNIEXPORT jlong JNICALL
Java_com_ermao_library_chapter_infrastructure_ChapterCoreNative_parseMobi(
    JNIEnv *env, jobject receiver, jintArray parents, jobjectArray titles, jobjectArray hrefs
) {
    jsize count;
    jint *parent_values = NULL;
    ErmaoChapterMobiNode *nodes = NULL;
    char **title_utf8 = NULL;
    char **href_utf8 = NULL;
    ErmaoChapterResult *result = NULL;
    ErmaoChapterStatus status = ERMAO_CHAPTER_INVALID_INPUT;
    jsize i;
    (void)receiver;
    if (parents == NULL || titles == NULL || hrefs == NULL ||
        (count = (*env)->GetArrayLength(env, parents)) < 0 ||
        (*env)->GetArrayLength(env, titles) != count || (*env)->GetArrayLength(env, hrefs) != count) {
        jclass error = (*env)->FindClass(env, "java/lang/IllegalArgumentException");
        if (error != NULL) (*env)->ThrowNew(env, error, "MOBI chapter arrays have different lengths");
        return 0;
    }
    if (count == 0) {
        status = ermao_chapters_from_mobi(NULL, 0, &result);
        return parse_status(env, status, result);
    }
    parent_values = (*env)->GetIntArrayElements(env, parents, NULL);
    nodes = (ErmaoChapterMobiNode *)calloc((size_t)count, sizeof(*nodes));
    title_utf8 = (char **)calloc((size_t)count, sizeof(*title_utf8));
    href_utf8 = (char **)calloc((size_t)count, sizeof(*href_utf8));
    if (parent_values == NULL || nodes == NULL ||
        title_utf8 == NULL || href_utf8 == NULL) {
        jclass error = (*env)->FindClass(env, "java/lang/OutOfMemoryError");
        if (error != NULL) (*env)->ThrowNew(env, error, "Chapter core allocation failed");
        goto cleanup;
    }
    for (i = 0; i < count; ++i) {
        jstring title = (jstring)(*env)->GetObjectArrayElement(env, titles, i);
        jstring href = (jstring)(*env)->GetObjectArrayElement(env, hrefs, i);
        if (title != NULL) title_utf8[i] = copy_java_utf8(env, title);
        if (href != NULL) href_utf8[i] = copy_java_utf8(env, href);
        if ((title != NULL && title_utf8[i] == NULL) ||
            (href != NULL && href_utf8[i] == NULL) || (*env)->ExceptionCheck(env)) {
            if (title != NULL) (*env)->DeleteLocalRef(env, title);
            if (href != NULL) (*env)->DeleteLocalRef(env, href);
            throw_chapter_error(env, "Chapter core string conversion failed", true);
            goto cleanup;
        }
        if (title != NULL) (*env)->DeleteLocalRef(env, title);
        if (href != NULL) (*env)->DeleteLocalRef(env, href);
        nodes[i].parent_index = parent_values[i];
        nodes[i].title = title_utf8[i];
        nodes[i].target_href = href_utf8[i];
    }
    status = ermao_chapters_from_mobi(nodes, (uint32_t)count, &result);
    if (status != ERMAO_CHAPTER_OK) parse_status(env, status, result);

cleanup:
    for (i = 0; i < count; ++i) {
        if (title_utf8 != NULL) free(title_utf8[i]);
        if (href_utf8 != NULL) free(href_utf8[i]);
    }
    if (parent_values != NULL) (*env)->ReleaseIntArrayElements(env, parents, parent_values, JNI_ABORT);
    free(nodes);
    free(title_utf8);
    free(href_utf8);
    return status == ERMAO_CHAPTER_OK ? (jlong)(uintptr_t)result : 0;
}

JNIEXPORT jlong JNICALL
Java_com_ermao_library_chapter_infrastructure_ChapterCoreNative_parseXml(
    JNIEnv *env, jobject receiver, jint format, jobjectArray events
) {
    jsize count;
    jsize i;
    jsize attribute;
    jclass event_class = NULL;
    jclass attribute_class = NULL;
    jmethodID event_kind;
    jmethodID event_name;
    jmethodID event_text;
    jmethodID event_attributes;
    jmethodID event_href;
    jmethodID attribute_name;
    jmethodID attribute_value;
    ErmaoChapterXmlEvent *native_events = NULL;
    XmlEventStorage *storage = NULL;
    ErmaoChapterResult *result = NULL;
    ErmaoChapterStatus status = ERMAO_CHAPTER_INVALID_INPUT;
    bool failed = false;
    (void)receiver;
    if (events == NULL || format < ERMAO_CHAPTER_EPUB_NAV ||
        format > ERMAO_CHAPTER_FB2) {
        throw_chapter_error(env, "Chapter XML input is invalid", false);
        return 0;
    }
    count = (*env)->GetArrayLength(env, events);
    if (count < 0) return 0;
    native_events = (ErmaoChapterXmlEvent *)calloc((size_t)(count == 0 ? 1 : count), sizeof(*native_events));
    storage = (XmlEventStorage *)calloc((size_t)(count == 0 ? 1 : count), sizeof(*storage));
    if (native_events == NULL || storage == NULL) {
        throw_chapter_error(env, "Chapter core allocation failed", true);
        failed = true;
        goto cleanup;
    }
    event_class = (*env)->FindClass(env, "com/ermao/library/chapter/infrastructure/ChapterCoreXmlEvent");
    attribute_class = (*env)->FindClass(env, "com/ermao/library/chapter/infrastructure/ChapterCoreXmlAttribute");
    if (event_class == NULL || attribute_class == NULL) {
        failed = true;
        goto cleanup;
    }
    event_kind = (*env)->GetMethodID(env, event_class, "getKind", "()I");
    event_name = (*env)->GetMethodID(env, event_class, "getName", "()Ljava/lang/String;");
    event_text = (*env)->GetMethodID(env, event_class, "getText", "()Ljava/lang/String;");
    event_attributes = (*env)->GetMethodID(env, event_class, "getAttributes", "()[Lcom/ermao/library/chapter/infrastructure/ChapterCoreXmlAttribute;");
    event_href = (*env)->GetMethodID(env, event_class, "getHref", "()Ljava/lang/String;");
    attribute_name = (*env)->GetMethodID(env, attribute_class, "getName", "()Ljava/lang/String;");
    attribute_value = (*env)->GetMethodID(env, attribute_class, "getValue", "()Ljava/lang/String;");
    if (event_kind == NULL || event_name == NULL || event_text == NULL ||
        event_attributes == NULL || event_href == NULL || attribute_name == NULL ||
        attribute_value == NULL) {
        failed = true;
        goto cleanup;
    }
    for (i = 0; i < count; ++i) {
        jobject event = (*env)->GetObjectArrayElement(env, events, i);
        jobjectArray attributes;
        if (event == NULL) {
            throw_chapter_error(env, "Chapter XML event is null", false);
            failed = true;
            goto cleanup;
        }
        native_events[i].kind = (uint32_t)(*env)->CallIntMethod(env, event, event_kind);
        jstring name_object = (jstring)(*env)->CallObjectMethod(env, event, event_name);
        jstring text_object = (jstring)(*env)->CallObjectMethod(env, event, event_text);
        jstring href_object = (jstring)(*env)->CallObjectMethod(env, event, event_href);
        attributes = (jobjectArray)(*env)->CallObjectMethod(env, event, event_attributes);
        (*env)->DeleteLocalRef(env, event);
        if ((*env)->ExceptionCheck(env) || attributes == NULL) {
            if (name_object != NULL) (*env)->DeleteLocalRef(env, name_object);
            if (text_object != NULL) (*env)->DeleteLocalRef(env, text_object);
            if (href_object != NULL) (*env)->DeleteLocalRef(env, href_object);
            failed = true;
            goto cleanup;
        }
        storage[i].attribute_count = (*env)->GetArrayLength(env, attributes);
        if (storage[i].attribute_count > 0) {
            size_t n = (size_t)storage[i].attribute_count;
            storage[i].attribute_names = (char **)calloc(n, sizeof(char *));
            storage[i].attribute_values = (char **)calloc(n, sizeof(char *));
            storage[i].attributes = (ErmaoChapterAttribute *)calloc(n, sizeof(ErmaoChapterAttribute));
            if (storage[i].attribute_names == NULL || storage[i].attribute_values == NULL ||
                storage[i].attributes == NULL) {
                throw_chapter_error(env, "Chapter core allocation failed", true);
                if (name_object != NULL) (*env)->DeleteLocalRef(env, name_object);
                if (text_object != NULL) (*env)->DeleteLocalRef(env, text_object);
                if (href_object != NULL) (*env)->DeleteLocalRef(env, href_object);
                (*env)->DeleteLocalRef(env, attributes);
                failed = true;
                goto cleanup;
            }
        }
        if (name_object != NULL) storage[i].name_utf8 = copy_java_utf8(env, name_object);
        if (text_object != NULL) storage[i].text_utf8 = copy_java_utf8(env, text_object);
        if (href_object != NULL) storage[i].href_utf8 = copy_java_utf8(env, href_object);
        if ((name_object != NULL && storage[i].name_utf8 == NULL) ||
            (text_object != NULL && storage[i].text_utf8 == NULL) ||
            (href_object != NULL && storage[i].href_utf8 == NULL) ||
            (*env)->ExceptionCheck(env)) {
            if (name_object != NULL) (*env)->DeleteLocalRef(env, name_object);
            if (text_object != NULL) (*env)->DeleteLocalRef(env, text_object);
            if (href_object != NULL) (*env)->DeleteLocalRef(env, href_object);
            (*env)->DeleteLocalRef(env, attributes);
            throw_chapter_error(env, "Chapter core string conversion failed", true);
            failed = true;
            goto cleanup;
        }
        if (name_object != NULL) (*env)->DeleteLocalRef(env, name_object);
        if (text_object != NULL) (*env)->DeleteLocalRef(env, text_object);
        if (href_object != NULL) (*env)->DeleteLocalRef(env, href_object);
        native_events[i].name = storage[i].name_utf8;
        native_events[i].text = storage[i].text_utf8;
        native_events[i].target_href = storage[i].href_utf8;
        native_events[i].attributes = storage[i].attributes;
        native_events[i].attribute_count = (uint32_t)storage[i].attribute_count;
        for (attribute = 0; attribute < storage[i].attribute_count; ++attribute) {
            jobject item = (*env)->GetObjectArrayElement(env, attributes, attribute);
            if (item == NULL) {
                throw_chapter_error(env, "Chapter XML attribute is null", false);
                (*env)->DeleteLocalRef(env, attributes);
                failed = true;
                goto cleanup;
            }
            jstring attribute_name_object =
                (jstring)(*env)->CallObjectMethod(env, item, attribute_name);
            jstring attribute_value_object =
                (jstring)(*env)->CallObjectMethod(env, item, attribute_value);
            (*env)->DeleteLocalRef(env, item);
            if ((*env)->ExceptionCheck(env) ||
                attribute_name_object == NULL || attribute_value_object == NULL) {
                if (attribute_name_object != NULL) (*env)->DeleteLocalRef(env, attribute_name_object);
                if (attribute_value_object != NULL) (*env)->DeleteLocalRef(env, attribute_value_object);
                throw_chapter_error(env, "Chapter XML attribute is invalid", false);
                (*env)->DeleteLocalRef(env, attributes);
                failed = true;
                goto cleanup;
            }
            storage[i].attribute_names[attribute] = copy_java_utf8(env, attribute_name_object);
            storage[i].attribute_values[attribute] = copy_java_utf8(env, attribute_value_object);
            (*env)->DeleteLocalRef(env, attribute_name_object);
            (*env)->DeleteLocalRef(env, attribute_value_object);
            if (storage[i].attribute_names[attribute] == NULL ||
                storage[i].attribute_values[attribute] == NULL ||
                (*env)->ExceptionCheck(env)) {
                throw_chapter_error(env, "Chapter core string conversion failed", true);
                (*env)->DeleteLocalRef(env, attributes);
                failed = true;
                goto cleanup;
            }
            storage[i].attributes[attribute].name = storage[i].attribute_names[attribute];
            storage[i].attributes[attribute].value = storage[i].attribute_values[attribute];
        }
        (*env)->DeleteLocalRef(env, attributes);
    }
    if (count > UINT32_MAX) {
        throw_chapter_error(env, "Chapter XML input is too large", false);
        failed = true;
        goto cleanup;
    }
    status = ermao_chapters_parse_xml((uint32_t)format, native_events, (uint32_t)count, &result);
    if (status != ERMAO_CHAPTER_OK) {
        parse_status(env, status, result);
        failed = true;
        goto cleanup;
    }

cleanup:
    release_xml_storage(env, storage, count);
    if (event_class != NULL) (*env)->DeleteLocalRef(env, event_class);
    if (attribute_class != NULL) (*env)->DeleteLocalRef(env, attribute_class);
    free(native_events);
    free(storage);
    if (failed) return 0;
    return (jlong)(uintptr_t)result;
}

JNIEXPORT void JNICALL
Java_com_ermao_library_chapter_infrastructure_ChapterCoreNative_freeResult(
    JNIEnv *env, jobject receiver, jlong handle
) {
    (void)env;
    (void)receiver;
    if (handle != 0) ermao_chapters_free(result_from_handle(handle));
}

JNIEXPORT jint JNICALL
Java_com_ermao_library_chapter_infrastructure_ChapterCoreNative_count(
    JNIEnv *env, jobject receiver, jlong handle
) {
    (void)env;
    (void)receiver;
    return (jint)ermao_chapters_count(result_from_handle(handle));
}

JNIEXPORT jbyteArray JNICALL
Java_com_ermao_library_chapter_infrastructure_ChapterCoreNative_text(
    JNIEnv *env, jobject receiver, jlong handle
) {
    const uint8_t *value = ermao_chapters_text(result_from_handle(handle));
    uint64_t length = ermao_chapters_text_length(result_from_handle(handle));
    jbyteArray output;
    (void)receiver;
    if (length > INT32_MAX) return NULL;
    output = (*env)->NewByteArray(env, (jsize)length);
    if (output != NULL && length != 0) (*env)->SetByteArrayRegion(env, output, 0, (jsize)length, (const jbyte *)value);
    return output;
}

JNIEXPORT jlongArray JNICALL
Java_com_ermao_library_chapter_infrastructure_ChapterCoreNative_entryValues(
    JNIEnv *env, jobject receiver, jlong handle, jint index
) {
    const ErmaoChapterEntry *entry;
    jlong values[7];
    jlongArray output;
    (void)receiver;
    if (index < 0 || (uint32_t)index >= ermao_chapters_count(result_from_handle(handle))) return NULL;
    entry = ermao_chapters_entry(result_from_handle(handle), (uint32_t)index);
    if (entry == NULL) return NULL;
    values[0] = (jlong)entry->index;
    values[1] = (jlong)entry->parent_index;
    values[2] = (jlong)entry->navigable;
    values[3] = (jlong)entry->source_start;
    values[4] = (jlong)entry->source_end;
    values[5] = (jlong)entry->content_start;
    values[6] = (jlong)(uintptr_t)entry;
    output = (*env)->NewLongArray(env, 6);
    if (output != NULL) (*env)->SetLongArrayRegion(env, output, 0, 6, values);
    return output;
}

JNIEXPORT jobjectArray JNICALL
Java_com_ermao_library_chapter_infrastructure_ChapterCoreNative_entryStrings(
    JNIEnv *env, jobject receiver, jlong handle, jint index
) {
    const ErmaoChapterEntry *entry;
    jclass string_class;
    jobjectArray output;
    (void)receiver;
    if (index < 0 || (uint32_t)index >= ermao_chapters_count(result_from_handle(handle))) return NULL;
    entry = ermao_chapters_entry(result_from_handle(handle), (uint32_t)index);
    if (entry == NULL) return NULL;
    string_class = (*env)->FindClass(env, "java/lang/String");
    if (string_class == NULL) return NULL;
    output = (*env)->NewObjectArray(env, 3, string_class, NULL);
    if (output == NULL) return NULL;
    (*env)->SetObjectArrayElement(env, output, 0, utf8_string(env, entry->key));
    (*env)->SetObjectArrayElement(env, output, 1, utf8_string(env, entry->title));
    if (entry->href != NULL) (*env)->SetObjectArrayElement(env, output, 2, utf8_string(env, entry->href));
    return output;
}
