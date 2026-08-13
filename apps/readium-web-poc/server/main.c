#include "ermao_mobi.h"

#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>

#define REQUEST_CAPACITY 8192u
#define PATH_CAPACITY 4096u
#define RESOURCE_PATH_CAPACITY 1024u
#define JSON_INITIAL_CAPACITY 4096u
#define POSITION_PAGE_LENGTH 1024u

typedef struct JsonBuffer {
    char *bytes;
    size_t length;
    size_t capacity;
} JsonBuffer;

typedef struct OpenPublication {
    ErmaoMobiBook *book;
    char id[RESOURCE_PATH_CAPACITY];
} OpenPublication;

static volatile sig_atomic_t keep_running = 1;
static const char *corpus_root = NULL;
static OpenPublication publication = {0};

static void handle_signal(int signal_number) {
    (void) signal_number;
    keep_running = 0;
}

static bool write_all(int descriptor, const void *bytes, size_t length) {
    const uint8_t *cursor = bytes;
    while (length > 0u) {
        const ssize_t written = send(descriptor, cursor, length, 0);
        if (written <= 0) {
            return false;
        }
        cursor += (size_t) written;
        length -= (size_t) written;
    }
    return true;
}

static bool json_reserve(JsonBuffer *buffer, size_t additional) {
    if (additional > SIZE_MAX - buffer->length - 1u) {
        return false;
    }
    const size_t required = buffer->length + additional + 1u;
    if (required <= buffer->capacity) {
        return true;
    }
    size_t capacity = buffer->capacity == 0u ? JSON_INITIAL_CAPACITY : buffer->capacity;
    while (capacity < required) {
        if (capacity > SIZE_MAX / 2u) {
            capacity = required;
            break;
        }
        capacity *= 2u;
    }
    char *resized = realloc(buffer->bytes, capacity);
    if (resized == NULL) {
        return false;
    }
    buffer->bytes = resized;
    buffer->capacity = capacity;
    return true;
}

static bool json_append_n(JsonBuffer *buffer, const char *value, size_t length) {
    if (!json_reserve(buffer, length)) {
        return false;
    }
    memcpy(buffer->bytes + buffer->length, value, length);
    buffer->length += length;
    buffer->bytes[buffer->length] = '\0';
    return true;
}

static bool json_append(JsonBuffer *buffer, const char *value) {
    return json_append_n(buffer, value, strlen(value));
}

static bool json_append_uint64(JsonBuffer *buffer, uint64_t value) {
    char number[32];
    const int length = snprintf(number, sizeof(number), "%llu", (unsigned long long) value);
    return length > 0 && json_append_n(buffer, number, (size_t) length);
}

static bool json_append_double(JsonBuffer *buffer, double value) {
    char number[48];
    const int length = snprintf(number, sizeof(number), "%.12g", value);
    return length > 0 && json_append_n(buffer, number, (size_t) length);
}

static bool json_append_string(JsonBuffer *buffer, const char *value) {
    if (!json_append(buffer, "\"")) {
        return false;
    }
    const unsigned char *cursor = (const unsigned char *) value;
    while (*cursor != 0u) {
        const unsigned char character = *cursor++;
        switch (character) {
        case '\"':
            if (!json_append(buffer, "\\\"")) return false;
            break;
        case '\\':
            if (!json_append(buffer, "\\\\")) return false;
            break;
        case '\b':
            if (!json_append(buffer, "\\b")) return false;
            break;
        case '\f':
            if (!json_append(buffer, "\\f")) return false;
            break;
        case '\n':
            if (!json_append(buffer, "\\n")) return false;
            break;
        case '\r':
            if (!json_append(buffer, "\\r")) return false;
            break;
        case '\t':
            if (!json_append(buffer, "\\t")) return false;
            break;
        default:
            if (character < 0x20u) {
                char escaped[7];
                const int length = snprintf(escaped, sizeof(escaped), "\\u%04x", character);
                if (length != 6 || !json_append_n(buffer, escaped, 6u)) return false;
            } else if (!json_append_n(buffer, (const char *) &character, 1u)) {
                return false;
            }
            break;
        }
    }
    return json_append(buffer, "\"");
}

static void json_free(JsonBuffer *buffer) {
    free(buffer->bytes);
    buffer->bytes = NULL;
    buffer->length = 0u;
    buffer->capacity = 0u;
}

static bool send_headers(
    int client,
    int status,
    const char *reason,
    const char *content_type,
    uint64_t content_length
) {
    char headers[1024];
    const int length = snprintf(
        headers,
        sizeof(headers),
        "HTTP/1.1 %d %s\r\n"
        "Content-Type: %s\r\n"
        "Content-Length: %llu\r\n"
        "Cache-Control: no-store\r\n"
        "X-Content-Type-Options: nosniff\r\n"
        "Connection: close\r\n\r\n",
        status,
        reason,
        content_type,
        (unsigned long long) content_length
    );
    return length > 0 && (size_t) length < sizeof(headers)
        && write_all(client, headers, (size_t) length);
}

static void send_json_error(int client, int status, const char *reason, const char *code, bool head_only) {
    JsonBuffer body = {0};
    if (!json_append(&body, "{\"error\":")
        || !json_append_string(&body, code)
        || !json_append(&body, "}")) {
        json_free(&body);
        return;
    }
    if (send_headers(client, status, reason, "application/json; charset=utf-8", body.length) && !head_only) {
        (void) write_all(client, body.bytes, body.length);
    }
    json_free(&body);
}

static bool has_publication_extension(const char *name) {
    const char *extension = strrchr(name, '.');
    if (extension == NULL || strncmp(name, "negative-", 9u) == 0) {
        return false;
    }
    return strcmp(extension, ".mobi") == 0
        || strcmp(extension, ".azw") == 0
        || strcmp(extension, ".azw3") == 0
        || strcmp(extension, ".prc") == 0;
}

static bool valid_publication_id(const char *id) {
    return id[0] != '\0'
        && strlen(id) < RESOURCE_PATH_CAPACITY
        && strstr(id, "..") == NULL
        && strchr(id, '/') == NULL
        && strchr(id, '\\') == NULL
        && has_publication_extension(id);
}

static int compare_names(const void *left, const void *right) {
    const char *const *left_name = left;
    const char *const *right_name = right;
    return strcmp(*left_name, *right_name);
}

static bool append_books(JsonBuffer *body) {
    DIR *directory = opendir(corpus_root);
    if (directory == NULL || !json_append(body, "{\"books\":[")) {
        if (directory != NULL) closedir(directory);
        return false;
    }
    char **names = NULL;
    size_t count = 0u;
    size_t capacity = 0u;
    struct dirent *entry;
    while ((entry = readdir(directory)) != NULL) {
        if (!has_publication_extension(entry->d_name)) continue;
        if (count == capacity) {
            const size_t next = capacity == 0u ? 16u : capacity * 2u;
            char **resized = realloc(names, next * sizeof(*names));
            if (resized == NULL) break;
            names = resized;
            capacity = next;
        }
        names[count] = strdup(entry->d_name);
        if (names[count] == NULL) break;
        count++;
    }
    closedir(directory);
    qsort(names, count, sizeof(*names), compare_names);
    bool ok = true;
    for (size_t index = 0u; index < count; index++) {
        if (index > 0u) ok = ok && json_append(body, ",");
        ok = ok && json_append(body, "{\"id\":")
            && json_append_string(body, names[index])
            && json_append(body, "}");
        free(names[index]);
    }
    free(names);
    return ok && json_append(body, "]}");
}

static ErmaoMobiStatus copy_core_string(
    ErmaoMobiStatus (*operation)(const ErmaoMobiBook *, uint32_t, char *, uint32_t, uint32_t *),
    const ErmaoMobiBook *book,
    uint32_t index,
    char **out_value
) {
    uint32_t required = 0u;
    ErmaoMobiStatus status = operation(book, index, NULL, 0u, &required);
    if (status == ERMAO_MOBI_NOT_FOUND) {
        *out_value = NULL;
        return ERMAO_MOBI_OK;
    }
    if (status != ERMAO_MOBI_BUFFER_TOO_SMALL || required == 0u) return status;
    char *value = malloc(required);
    if (value == NULL) return ERMAO_MOBI_OUT_OF_MEMORY;
    status = operation(book, index, value, required, &required);
    if (status != ERMAO_MOBI_OK) {
        free(value);
        return status;
    }
    *out_value = value;
    return ERMAO_MOBI_OK;
}

static ErmaoMobiStatus copy_resource_name(const ErmaoMobiBook *book, uint32_t index, char **value) {
    return copy_core_string(ermao_mobi_copy_resource_source_name, book, index, value);
}

static ErmaoMobiStatus copy_resource_type(const ErmaoMobiBook *book, uint32_t index, char **value) {
    return copy_core_string(ermao_mobi_copy_resource_media_type, book, index, value);
}

static ErmaoMobiStatus copy_toc_title(const ErmaoMobiBook *book, uint32_t index, char **value) {
    return copy_core_string(ermao_mobi_copy_toc_title, book, index, value);
}

static ErmaoMobiStatus copy_toc_fragment(const ErmaoMobiBook *book, uint32_t index, char **value) {
    return copy_core_string(ermao_mobi_copy_toc_fragment, book, index, value);
}

static ErmaoMobiStatus copy_metadata(ErmaoMobiMetadataField field, char **out_value) {
    uint32_t required = 0u;
    ErmaoMobiStatus status = ermao_mobi_copy_metadata(publication.book, field, NULL, 0u, &required);
    if (status == ERMAO_MOBI_NOT_FOUND) {
        *out_value = NULL;
        return ERMAO_MOBI_OK;
    }
    if (status != ERMAO_MOBI_BUFFER_TOO_SMALL || required == 0u) return status;
    char *value = malloc(required);
    if (value == NULL) return ERMAO_MOBI_OUT_OF_MEMORY;
    status = ermao_mobi_copy_metadata(publication.book, field, value, required, &required);
    if (status != ERMAO_MOBI_OK) {
        free(value);
        return status;
    }
    *out_value = value;
    return ERMAO_MOBI_OK;
}

static ErmaoMobiStatus ensure_publication(const char *id) {
    if (!valid_publication_id(id)) return ERMAO_MOBI_INVALID_ARGUMENT;
    if (publication.book != NULL && strcmp(publication.id, id) == 0) return ERMAO_MOBI_OK;
    ermao_mobi_close(&publication.book);
    publication.id[0] = '\0';
    char path[PATH_CAPACITY];
    const int path_length = snprintf(path, sizeof(path), "%s/%s", corpus_root, id);
    if (path_length <= 0 || (size_t) path_length >= sizeof(path)) return ERMAO_MOBI_INVALID_ARGUMENT;
    const ErmaoMobiStatus status = ermao_mobi_open(path, NULL, &publication.book);
    if (status != ERMAO_MOBI_OK) return status;
    (void) snprintf(publication.id, sizeof(publication.id), "%s", id);
    return ERMAO_MOBI_OK;
}

static bool copy_original_file_hash(char hash[65]) {
    char path[PATH_CAPACITY];
    const int path_length = snprintf(path, sizeof(path), "%s/SHA256SUMS", corpus_root);
    if (path_length <= 0 || (size_t) path_length >= sizeof(path)) return false;
    FILE *file = fopen(path, "r");
    if (file == NULL) return false;
    char line[PATH_CAPACITY];
    bool found = false;
    while (fgets(line, sizeof(line), file) != NULL) {
        char candidate_hash[65] = {0};
        char candidate_name[RESOURCE_PATH_CAPACITY] = {0};
        if (sscanf(line, "%64s %1023s", candidate_hash, candidate_name) == 2
            && strlen(candidate_hash) == 64u
            && strcmp(candidate_name, publication.id) == 0) {
            memcpy(hash, candidate_hash, 65u);
            found = true;
            break;
        }
    }
    fclose(file);
    return found;
}

static bool is_reading_order_resource(uint32_t resource_index, const ErmaoMobiBookInfo *info) {
    for (uint32_t position = 0u; position < info->reading_order_count; position++) {
        uint32_t candidate = 0u;
        if (ermao_mobi_reading_order_resource_index(publication.book, position, &candidate) == ERMAO_MOBI_OK
            && candidate == resource_index) {
            return true;
        }
    }
    return false;
}

static bool append_resource_link(JsonBuffer *body, uint32_t index, bool cover) {
    char *name = NULL;
    char *type = NULL;
    const bool loaded = copy_resource_name(publication.book, index, &name) == ERMAO_MOBI_OK
        && name != NULL
        && copy_resource_type(publication.book, index, &type) == ERMAO_MOBI_OK
        && type != NULL;
    bool ok = loaded && json_append(body, "{\"href\":\"")
        && json_append(body, name)
        && json_append(body, "\",\"type\":")
        && json_append_string(body, type);
    if (cover) ok = ok && json_append(body, ",\"rel\":[\"cover\"]");
    ok = ok && json_append(body, "}");
    free(name);
    free(type);
    return ok;
}

static bool append_toc_node(JsonBuffer *body, uint32_t index, uint32_t toc_count) {
    ErmaoMobiTocInfo info = {.struct_size = sizeof(info)};
    if (ermao_mobi_get_toc_info(publication.book, index, &info) != ERMAO_MOBI_OK
        || info.target_resource_index == ERMAO_MOBI_INDEX_NONE) {
        return false;
    }
    char *name = NULL;
    char *title = NULL;
    char *fragment = NULL;
    bool ok = copy_resource_name(publication.book, info.target_resource_index, &name) == ERMAO_MOBI_OK
        && name != NULL
        && copy_toc_title(publication.book, index, &title) == ERMAO_MOBI_OK
        && copy_toc_fragment(publication.book, index, &fragment) == ERMAO_MOBI_OK
        && json_append(body, "{\"href\":\"")
        && json_append(body, name);
    if (ok && fragment != NULL && fragment[0] != '\0') {
        ok = json_append(body, "#") && json_append(body, fragment);
    }
    ok = ok && json_append(body, "\"");
    if (ok && title != NULL && title[0] != '\0') {
        ok = json_append(body, ",\"title\":") && json_append_string(body, title);
    }
    bool has_child = false;
    for (uint32_t child = 0u; child < toc_count; child++) {
        ErmaoMobiTocInfo child_info = {.struct_size = sizeof(child_info)};
        if (ermao_mobi_get_toc_info(publication.book, child, &child_info) == ERMAO_MOBI_OK
            && child_info.parent_index == index
            && child_info.target_resource_index != ERMAO_MOBI_INDEX_NONE) {
            if (!has_child) ok = ok && json_append(body, ",\"children\":[");
            if (has_child) ok = ok && json_append(body, ",");
            ok = ok && append_toc_node(body, child, toc_count);
            has_child = true;
        }
    }
    if (has_child) ok = ok && json_append(body, "]");
    ok = ok && json_append(body, "}");
    free(name);
    free(title);
    free(fragment);
    return ok;
}

static bool append_manifest(JsonBuffer *body) {
    ErmaoMobiBookInfo info = {.struct_size = sizeof(info)};
    if (ermao_mobi_get_book_info(publication.book, &info) != ERMAO_MOBI_OK) return false;
    char *title = NULL;
    char *author = NULL;
    char *language = NULL;
    if (copy_metadata(ERMAO_MOBI_METADATA_TITLE, &title) != ERMAO_MOBI_OK
        || copy_metadata(ERMAO_MOBI_METADATA_AUTHOR, &author) != ERMAO_MOBI_OK
        || copy_metadata(ERMAO_MOBI_METADATA_LANGUAGE, &language) != ERMAO_MOBI_OK) {
        free(title); free(author); free(language);
        return false;
    }
    const char *effective_title = title != NULL && title[0] != '\0' ? title : publication.id;
    bool ok = json_append(body, "{\"@context\":\"https://readium.org/webpub-manifest/context.jsonld\",\"metadata\":{\"@type\":\"http://schema.org/Book\",\"identifier\":\"urn:shuku:mobi:")
        && json_append(body, publication.id)
        && json_append(body, "\",\"title\":")
        && json_append_string(body, effective_title)
        && json_append(body, ",\"conformsTo\":[\"https://readium.org/webpub-manifest/profiles/epub\"],\"layout\":\"reflowable\",\"readingProgression\":\"")
        && json_append(body, info.reading_direction == ERMAO_MOBI_DIRECTION_RTL ? "rtl" : "ltr")
        && json_append(body, "\"");
    if (author != NULL && author[0] != '\0') ok = ok && json_append(body, ",\"author\":") && json_append_string(body, author);
    if (language != NULL && language[0] != '\0') ok = ok && json_append(body, ",\"language\":") && json_append_string(body, language);
    ok = ok && json_append(body, "},\"links\":[{\"rel\":[\"self\"],\"href\":\"manifest.json\",\"type\":\"application/webpub+json\"},{\"rel\":[\"positions\"],\"href\":\"positions.json\",\"type\":\"application/vnd.readium.position-list+json\"}],\"readingOrder\":[");
    for (uint32_t position = 0u; ok && position < info.reading_order_count; position++) {
        uint32_t index = 0u;
        ok = ermao_mobi_reading_order_resource_index(publication.book, position, &index) == ERMAO_MOBI_OK;
        if (position > 0u) ok = ok && json_append(body, ",");
        ok = ok && append_resource_link(body, index, false);
    }
    ok = ok && json_append(body, "],\"resources\":[");
    bool first_resource = true;
    for (uint32_t index = 0u; ok && index < info.resource_count; index++) {
        if (is_reading_order_resource(index, &info)) continue;
        if (!first_resource) ok = ok && json_append(body, ",");
        ok = ok && append_resource_link(body, index, index == info.cover_resource_index);
        first_resource = false;
    }
    ok = ok && json_append(body, "],\"toc\":[");
    bool first_toc = true;
    for (uint32_t index = 0u; ok && index < info.toc_count; index++) {
        ErmaoMobiTocInfo toc_info = {.struct_size = sizeof(toc_info)};
        if (ermao_mobi_get_toc_info(publication.book, index, &toc_info) != ERMAO_MOBI_OK
            || toc_info.parent_index != ERMAO_MOBI_INDEX_NONE
            || toc_info.target_resource_index == ERMAO_MOBI_INDEX_NONE) continue;
        if (!first_toc) ok = ok && json_append(body, ",");
        ok = ok && append_toc_node(body, index, info.toc_count);
        first_toc = false;
    }
    char original_file_hash[65] = {0};
    const bool has_original_file_hash = copy_original_file_hash(original_file_hash);
    ok = ok && json_append(body, "],\"https://shuku.app/reader/runtime\":{");
    if (has_original_file_hash) {
        ok = ok && json_append(body, "\"originalFileHash\":")
            && json_append_string(body, original_file_hash)
            && json_append(body, ",");
    }
    ok = ok && json_append(body, "\"parser\":")
        && json_append_string(body, ermao_mobi_parser_identifier())
        && json_append(body, ",\"normalization\":")
        && json_append_string(body, ermao_mobi_normalization_identifier())
        && json_append(body, ",\"positionPageLength\":1024}}");
    free(title); free(author); free(language);
    return ok;
}

static bool append_positions(JsonBuffer *body) {
    ErmaoMobiBookInfo info = {.struct_size = sizeof(info)};
    if (ermao_mobi_get_book_info(publication.book, &info) != ERMAO_MOBI_OK) return false;
    uint64_t total = 0u;
    for (uint32_t order = 0u; order < info.reading_order_count; order++) {
        uint32_t index = 0u;
        ErmaoMobiResourceInfo resource = {.struct_size = sizeof(resource)};
        if (ermao_mobi_reading_order_resource_index(publication.book, order, &index) != ERMAO_MOBI_OK
            || ermao_mobi_get_resource_info(publication.book, index, &resource) != ERMAO_MOBI_OK) return false;
        total += resource.decoded_length == 0u ? 1u : (resource.decoded_length + POSITION_PAGE_LENGTH - 1u) / POSITION_PAGE_LENGTH;
    }
    bool ok = json_append(body, "{\"total\":") && json_append_uint64(body, total) && json_append(body, ",\"positions\":[");
    uint64_t current_position = 1u;
    bool first = true;
    for (uint32_t order = 0u; ok && order < info.reading_order_count; order++) {
        uint32_t index = 0u;
        ErmaoMobiResourceInfo resource = {.struct_size = sizeof(resource)};
        char *name = NULL;
        char *type = NULL;
        ok = ermao_mobi_reading_order_resource_index(publication.book, order, &index) == ERMAO_MOBI_OK
            && ermao_mobi_get_resource_info(publication.book, index, &resource) == ERMAO_MOBI_OK
            && copy_resource_name(publication.book, index, &name) == ERMAO_MOBI_OK && name != NULL
            && copy_resource_type(publication.book, index, &type) == ERMAO_MOBI_OK && type != NULL;
        const uint64_t count = resource.decoded_length == 0u ? 1u : (resource.decoded_length + POSITION_PAGE_LENGTH - 1u) / POSITION_PAGE_LENGTH;
        for (uint64_t local = 0u; ok && local < count; local++, current_position++) {
            if (!first) ok = ok && json_append(body, ",");
            const double progression = resource.decoded_length == 0u
                ? 0.0
                : (double) (local * POSITION_PAGE_LENGTH) / (double) resource.decoded_length;
            const double total_progression = total <= 1u ? 0.0 : (double) (current_position - 1u) / (double) (total - 1u);
            ok = ok && json_append(body, "{\"href\":\"")
                && json_append(body, name)
                && json_append(body, "\",\"type\":")
                && json_append_string(body, type)
                && json_append(body, ",\"locations\":{\"position\":")
                && json_append_uint64(body, current_position)
                && json_append(body, ",\"progression\":")
                && json_append_double(body, progression)
                && json_append(body, ",\"totalProgression\":")
                && json_append_double(body, total_progression)
                && json_append(body, "}}");
            first = false;
        }
        free(name); free(type);
    }
    return ok && json_append(body, "]}");
}

static bool url_decode(const char *encoded, char *decoded, size_t capacity) {
    size_t output = 0u;
    for (size_t input = 0u; encoded[input] != '\0'; input++) {
        if (output + 1u >= capacity) return false;
        if (encoded[input] == '%' && encoded[input + 1u] != '\0' && encoded[input + 2u] != '\0') {
            unsigned int byte = 0u;
            if (sscanf(encoded + input + 1u, "%2x", &byte) != 1) return false;
            decoded[output++] = (char) byte;
            input += 2u;
        } else {
            decoded[output++] = encoded[input] == '+' ? ' ' : encoded[input];
        }
    }
    decoded[output] = '\0';
    return true;
}

static bool split_publication_path(
    const char *path,
    char *id,
    size_t id_capacity,
    const char **remainder
) {
    const char prefix[] = "/publications/";
    if (strncmp(path, prefix, sizeof(prefix) - 1u) != 0) return false;
    const char *slash = strchr(path + sizeof(prefix) - 1u, '/');
    if (slash == NULL) return false;
    const size_t encoded_length = (size_t) (slash - (path + sizeof(prefix) - 1u));
    if (encoded_length == 0u || encoded_length >= RESOURCE_PATH_CAPACITY) return false;
    char encoded[RESOURCE_PATH_CAPACITY];
    memcpy(encoded, path + sizeof(prefix) - 1u, encoded_length);
    encoded[encoded_length] = '\0';
    if (!url_decode(encoded, id, id_capacity) || !valid_publication_id(id)) return false;
    *remainder = slash + 1u;
    return true;
}

static void serve_resource(int client, const char *encoded_path, bool head_only) {
    char resource_path[RESOURCE_PATH_CAPACITY];
    if (!url_decode(encoded_path, resource_path, sizeof(resource_path))
        || strstr(resource_path, "..") != NULL
        || resource_path[0] == '/') {
        send_json_error(client, 400, "Bad Request", "invalid_resource_path", head_only);
        return;
    }
    ErmaoMobiBookInfo info = {.struct_size = sizeof(info)};
    if (ermao_mobi_get_book_info(publication.book, &info) != ERMAO_MOBI_OK) {
        send_json_error(client, 500, "Internal Server Error", "book_info_failed", head_only);
        return;
    }
    for (uint32_t index = 0u; index < info.resource_count; index++) {
        char *name = NULL;
        if (copy_resource_name(publication.book, index, &name) != ERMAO_MOBI_OK || name == NULL) continue;
        const bool matches = strcmp(name, resource_path) == 0;
        free(name);
        if (!matches) continue;
        ErmaoMobiResourceInfo resource = {.struct_size = sizeof(resource)};
        char *type = NULL;
        if (ermao_mobi_get_resource_info(publication.book, index, &resource) != ERMAO_MOBI_OK
            || copy_resource_type(publication.book, index, &type) != ERMAO_MOBI_OK || type == NULL) {
            free(type);
            send_json_error(client, 500, "Internal Server Error", "resource_info_failed", head_only);
            return;
        }
        const bool headers_sent = send_headers(client, 200, "OK", type, resource.decoded_length);
        free(type);
        if (!headers_sent || head_only) return;
        uint8_t buffer[ERMAO_MOBI_MAX_READ_BYTES];
        uint64_t offset = 0u;
        while (offset < resource.decoded_length) {
            const uint64_t remaining = resource.decoded_length - offset;
            const uint32_t requested = remaining < sizeof(buffer) ? (uint32_t) remaining : (uint32_t) sizeof(buffer);
            uint32_t bytes_read = 0u;
            if (ermao_mobi_read_resource(publication.book, index, offset, buffer, requested, &bytes_read) != ERMAO_MOBI_OK
                || bytes_read == 0u || !write_all(client, buffer, bytes_read)) return;
            offset += bytes_read;
        }
        return;
    }
    send_json_error(client, 404, "Not Found", "resource_not_found", head_only);
}

static void serve_json(int client, JsonBuffer *body, const char *content_type, bool head_only) {
    if (send_headers(client, 200, "OK", content_type, body->length) && !head_only) {
        (void) write_all(client, body->bytes, body->length);
    }
}

static void handle_request(int client) {
    char request[REQUEST_CAPACITY];
    const ssize_t received = recv(client, request, sizeof(request) - 1u, 0);
    if (received <= 0) return;
    request[received] = '\0';
    char method[8];
    char path[PATH_CAPACITY];
    if (sscanf(request, "%7s %4095s", method, path) != 2) {
        send_json_error(client, 400, "Bad Request", "invalid_request", false);
        return;
    }
    fprintf(stdout, "request method=%s path=%s\n", method, path);
    fflush(stdout);
    const bool head_only = strcmp(method, "HEAD") == 0;
    if (!head_only && strcmp(method, "GET") != 0) {
        send_json_error(client, 405, "Method Not Allowed", "method_not_allowed", false);
        return;
    }
    char *query = strchr(path, '?');
    if (query != NULL) *query = '\0';
    if (strcmp(path, "/health") == 0) {
        JsonBuffer body = {0};
        (void) json_append(&body, "{\"status\":\"ok\",\"abiVersion\":");
        (void) json_append_uint64(&body, ermao_mobi_abi_version());
        (void) json_append(&body, "}");
        serve_json(client, &body, "application/json; charset=utf-8", head_only);
        json_free(&body);
        return;
    }
    if (strcmp(path, "/books") == 0) {
        JsonBuffer body = {0};
        if (!append_books(&body)) send_json_error(client, 500, "Internal Server Error", "catalog_failed", head_only);
        else serve_json(client, &body, "application/json; charset=utf-8", head_only);
        json_free(&body);
        return;
    }
    char id[RESOURCE_PATH_CAPACITY];
    const char *remainder = NULL;
    if (!split_publication_path(path, id, sizeof(id), &remainder)) {
        send_json_error(client, 404, "Not Found", "route_not_found", head_only);
        return;
    }
    const ErmaoMobiStatus open_status = ensure_publication(id);
    if (open_status != ERMAO_MOBI_OK) {
        send_json_error(client, 422, "Unprocessable Content", ermao_mobi_status_name(open_status), head_only);
        return;
    }
    if (strcmp(remainder, "manifest.json") == 0) {
        JsonBuffer body = {0};
        if (!append_manifest(&body)) send_json_error(client, 500, "Internal Server Error", "manifest_failed", head_only);
        else serve_json(client, &body, "application/webpub+json; charset=utf-8", head_only);
        json_free(&body);
    } else if (strcmp(remainder, "positions.json") == 0) {
        JsonBuffer body = {0};
        if (!append_positions(&body)) send_json_error(client, 500, "Internal Server Error", "positions_failed", head_only);
        else serve_json(client, &body, "application/vnd.readium.position-list+json; charset=utf-8", head_only);
        json_free(&body);
    } else {
        serve_resource(client, remainder, head_only);
    }
}

int main(int argc, char **argv) {
    if (argc < 2 || argc > 3) {
        fprintf(stderr, "usage: %s CORPUS_ROOT [PORT]\n", argv[0]);
        return EXIT_FAILURE;
    }
    corpus_root = argv[1];
    const long requested_port = argc == 3 ? strtol(argv[2], NULL, 10) : 8787L;
    if (requested_port <= 0L || requested_port > 65535L) {
        fprintf(stderr, "invalid port\n");
        return EXIT_FAILURE;
    }
    signal(SIGINT, handle_signal);
    signal(SIGTERM, handle_signal);
    signal(SIGPIPE, SIG_IGN);
    const int server = socket(AF_INET, SOCK_STREAM, 0);
    if (server < 0) {
        perror("socket");
        return EXIT_FAILURE;
    }
    int reuse = 1;
    (void) setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
    const struct sockaddr_in address = {
        .sin_family = AF_INET,
        .sin_port = htons((uint16_t) requested_port),
        .sin_addr = {.s_addr = htonl(INADDR_LOOPBACK)},
    };
    if (bind(server, (const struct sockaddr *) &address, sizeof(address)) != 0 || listen(server, 16) != 0) {
        perror("bind/listen");
        close(server);
        return EXIT_FAILURE;
    }
    fprintf(stdout, "Readium Web POC publication server listening on http://127.0.0.1:%ld\n", requested_port);
    fflush(stdout);
    while (keep_running) {
        const int client = accept(server, NULL, NULL);
        if (client < 0) {
            if (errno == EINTR) continue;
            perror("accept");
            break;
        }
        handle_request(client);
        close(client);
    }
    ermao_mobi_close(&publication.book);
    close(server);
    return EXIT_SUCCESS;
}
