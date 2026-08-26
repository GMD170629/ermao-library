#include "archive_core.h"

#include <archive.h>
#include <archive_entry.h>
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

typedef struct {
    char *path;
    int64_t size_bytes;
} ermao_archive_page;

struct ermao_archive {
    char *path;
    ermao_archive_limits limits;
    ermao_archive_page *pages;
    size_t page_count;
};

static void set_error(ermao_archive_error *error, const char *code, const char *message) {
    if (error == NULL) return;
    snprintf(error->code, sizeof(error->code), "%s", code == NULL ? "ARCHIVE_ERROR" : code);
    snprintf(error->message, sizeof(error->message), "%s", message == NULL ? "Archive operation failed" : message);
}

static int contains_case_insensitive(const char *value, const char *needle) {
    size_t value_length;
    size_t needle_length;
    size_t start;
    size_t index;
    if (value == NULL || needle == NULL) return 0;
    value_length = strlen(value);
    needle_length = strlen(needle);
    if (needle_length == 0 || needle_length > value_length) return 0;
    for (start = 0; start + needle_length <= value_length; start++) {
        for (index = 0; index < needle_length; index++) {
            if (tolower((unsigned char)value[start + index]) !=
                tolower((unsigned char)needle[index])) break;
        }
        if (index == needle_length) return 1;
    }
    return 0;
}

static void set_reader_error(
    ermao_archive_error *error,
    const char *fallback_code,
    const char *message
) {
    set_error(
        error,
        contains_case_insensitive(message, "volume") ? "ARCHIVE_PART_MISSING" : fallback_code,
        message
    );
}

static char *copy_string(const char *value) {
    size_t length;
    char *copy;
    if (value == NULL) return NULL;
    length = strlen(value);
    copy = malloc(length + 1U);
    if (copy == NULL) return NULL;
    memcpy(copy, value, length + 1U);
    return copy;
}

static struct archive *new_reader(ermao_archive_error *error) {
    struct archive *reader = archive_read_new();
    if (reader == NULL) {
        set_error(error, "ARCHIVE_OUT_OF_MEMORY", "Unable to allocate archive reader");
        return NULL;
    }
    if (archive_read_support_filter_none(reader) != ARCHIVE_OK ||
        archive_read_support_format_zip(reader) != ARCHIVE_OK ||
        archive_read_support_format_rar(reader) != ARCHIVE_OK ||
        archive_read_support_format_rar5(reader) != ARCHIVE_OK) {
        set_error(error, "ARCHIVE_FORMAT_SETUP_FAILED", archive_error_string(reader));
        archive_read_free(reader);
        return NULL;
    }
    return reader;
}

static int safe_path(const char *path) {
    const char *component;
    const char *cursor;
    size_t length;
    if (path == NULL || path[0] == '\0' || path[0] == '/' || path[0] == '\\') return 0;
    if (isalpha((unsigned char)path[0]) && path[1] == ':') return 0;
    if (strchr(path, '\\') != NULL) return 0;
    component = path;
    cursor = path;
    for (;;) {
        if (*cursor == '/' || *cursor == '\0') {
            length = (size_t)(cursor - component);
            if (length == 0) {
                if (*cursor == '\0' && cursor > path && cursor[-1] == '/') break;
                return 0;
            }
            if ((length == 1 && component[0] == '.') ||
                (length == 2 && component[0] == '.' && component[1] == '.')) return 0;
            if (*cursor == '\0') break;
            component = cursor + 1;
        }
        cursor++;
    }
    return 1;
}

static int image_path(const char *path) {
    const char *extension = strrchr(path, '.');
    char lowered[8];
    size_t length;
    size_t index;
    if (extension == NULL) return 0;
    extension++;
    length = strlen(extension);
    if (length == 0 || length >= sizeof(lowered)) return 0;
    for (index = 0; index < length; index++) lowered[index] = (char)tolower((unsigned char)extension[index]);
    lowered[length] = '\0';
    return strcmp(lowered, "jpg") == 0 || strcmp(lowered, "jpeg") == 0 ||
        strcmp(lowered, "png") == 0 || strcmp(lowered, "gif") == 0 || strcmp(lowered, "webp") == 0;
}

static int natural_compare(const void *left_value, const void *right_value) {
    const unsigned char *left = (const unsigned char *)((const ermao_archive_page *)left_value)->path;
    const unsigned char *right = (const unsigned char *)((const ermao_archive_page *)right_value)->path;
    while (*left != '\0' && *right != '\0') {
        if (isdigit(*left) && isdigit(*right)) {
            const unsigned char *left_end = left;
            const unsigned char *right_end = right;
            while (*left_end == '0') left_end++;
            while (*right_end == '0') right_end++;
            const unsigned char *left_digits = left_end;
            const unsigned char *right_digits = right_end;
            while (isdigit(*left_end)) left_end++;
            while (isdigit(*right_end)) right_end++;
            size_t left_length = (size_t)(left_end - left_digits);
            size_t right_length = (size_t)(right_end - right_digits);
            if (left_length != right_length) return left_length < right_length ? -1 : 1;
            int digits = memcmp(left_digits, right_digits, left_length);
            if (digits != 0) return digits;
            left = left_end;
            right = right_end;
            continue;
        }
        int left_char = tolower(*left);
        int right_char = tolower(*right);
        if (left_char != right_char) return left_char < right_char ? -1 : 1;
        left++;
        right++;
    }
    return *left == *right ? 0 : (*left == '\0' ? -1 : 1);
}

static void free_pages(ermao_archive *value) {
    size_t index;
    if (value == NULL) return;
    for (index = 0; index < value->page_count; index++) free(value->pages[index].path);
    free(value->pages);
}

static int append_page(ermao_archive *value, const char *path, int64_t size, ermao_archive_error *error) {
    ermao_archive_page *pages = realloc(value->pages, (value->page_count + 1) * sizeof(*pages));
    if (pages == NULL) {
        set_error(error, "ARCHIVE_OUT_OF_MEMORY", "Unable to allocate archive page index");
        return 0;
    }
    value->pages = pages;
    value->pages[value->page_count].path = copy_string(path);
    if (value->pages[value->page_count].path == NULL) {
        set_error(error, "ARCHIVE_OUT_OF_MEMORY", "Unable to copy archive page path");
        return 0;
    }
    value->pages[value->page_count].size_bytes = size;
    value->page_count++;
    return 1;
}

int ermao_archive_open(
    const char *path,
    ermao_archive_limits limits,
    ermao_archive **result,
    ermao_archive_error *error
) {
    struct archive *reader = NULL;
    struct archive_entry *entry = NULL;
    ermao_archive *value = NULL;
    size_t entries_seen = 0;
    int64_t expanded_bytes = 0;
    int status;
    size_t index;
    if (result != NULL) *result = NULL;
    if (path == NULL || result == NULL || limits.maximum_entries == 0 ||
        limits.maximum_page_bytes <= 0 || limits.maximum_expanded_bytes <= 0) {
        set_error(error, "ARCHIVE_ARGUMENT_INVALID", "Archive arguments are invalid");
        return 0;
    }
    value = calloc(1, sizeof(*value));
    if (value == NULL || (value->path = copy_string(path)) == NULL) {
        free(value);
        set_error(error, "ARCHIVE_OUT_OF_MEMORY", "Unable to allocate archive state");
        return 0;
    }
    value->limits = limits;
    reader = new_reader(error);
    if (reader == NULL) goto failure;
    if (archive_read_open_filename(reader, path, 64 * 1024) != ARCHIVE_OK) {
        set_reader_error(error, "ARCHIVE_OPEN_FAILED", archive_error_string(reader));
        goto failure;
    }
    while ((status = archive_read_next_header(reader, &entry)) == ARCHIVE_OK) {
        const char *entry_path = archive_entry_pathname_utf8(entry);
        int64_t size;
        if (entry_path == NULL) entry_path = archive_entry_pathname(entry);
        if (!safe_path(entry_path)) {
            set_error(error, "ARCHIVE_PATH_INVALID", "Archive contains an unsafe path");
            goto failure;
        }
        if (archive_entry_filetype(entry) == AE_IFDIR) {
            archive_read_data_skip(reader);
            continue;
        }
        if (archive_entry_filetype(entry) != AE_IFREG || archive_entry_symlink(entry) != NULL ||
            archive_entry_hardlink(entry) != NULL) {
            set_error(error, "ARCHIVE_ENTRY_TYPE_INVALID", "Archive contains a non-regular entry");
            goto failure;
        }
        entries_seen++;
        if (entries_seen > limits.maximum_entries) {
            set_error(error, "ARCHIVE_ENTRY_LIMIT_EXCEEDED", "Archive contains too many entries");
            goto failure;
        }
        if (!archive_entry_size_is_set(entry) || (size = archive_entry_size(entry)) < 0 ||
            size > limits.maximum_page_bytes) {
            set_error(error, "ARCHIVE_PAGE_LIMIT_EXCEEDED", "Archive entry size is invalid");
            goto failure;
        }
        if (expanded_bytes > limits.maximum_expanded_bytes - size) {
            set_error(error, "ARCHIVE_EXPANDED_LIMIT_EXCEEDED", "Archive expanded size is too large");
            goto failure;
        }
        expanded_bytes += size;
        if (archive_entry_is_encrypted(entry) == 1) {
            set_error(error, "ARCHIVE_ENCRYPTED", "Archive contains encrypted entries");
            goto failure;
        }
        if (image_path(entry_path) && !append_page(value, entry_path, size, error)) goto failure;
        status = archive_read_data_skip(reader);
        if (status != ARCHIVE_OK && status != ARCHIVE_WARN) {
            set_reader_error(error, "ARCHIVE_DATA_INVALID", archive_error_string(reader));
            goto failure;
        }
    }
    if (status != ARCHIVE_EOF) {
        set_reader_error(error, "ARCHIVE_HEADER_INVALID", archive_error_string(reader));
        goto failure;
    }
    if (archive_read_has_encrypted_entries(reader) == 1) {
        set_error(error, "ARCHIVE_ENCRYPTED", "Archive contains encrypted entries");
        goto failure;
    }
    archive_read_free(reader);
    reader = NULL;
    if (value->page_count == 0) {
        set_error(error, "ARCHIVE_NO_IMAGES", "Archive contains no supported image pages");
        goto failure;
    }
    qsort(value->pages, value->page_count, sizeof(*value->pages), natural_compare);
    for (index = 1; index < value->page_count; index++) {
        if (strcasecmp(value->pages[index - 1].path, value->pages[index].path) == 0) {
            set_error(error, "ARCHIVE_PATH_DUPLICATE", "Archive contains duplicate page paths");
            goto failure;
        }
    }
    *result = value;
    return 1;

failure:
    if (reader != NULL) archive_read_free(reader);
    free_pages(value);
    if (value != NULL) free(value->path);
    free(value);
    return 0;
}

size_t ermao_archive_page_count(const ermao_archive *archive) {
    return archive == NULL ? 0 : archive->page_count;
}

int ermao_archive_page_info(
    const ermao_archive *archive,
    size_t index,
    const char **path,
    int64_t *size_bytes,
    ermao_archive_error *error
) {
    if (archive == NULL || path == NULL || size_bytes == NULL || index >= archive->page_count) {
        set_error(error, "ARCHIVE_PAGE_OUT_OF_RANGE", "Archive page index is invalid");
        return 0;
    }
    *path = archive->pages[index].path;
    *size_bytes = archive->pages[index].size_bytes;
    return 1;
}

int ermao_archive_read_page(
    const ermao_archive *archive,
    size_t index,
    unsigned char *output,
    size_t capacity,
    size_t *written,
    ermao_archive_error *error
) {
    struct archive *reader;
    struct archive_entry *entry = NULL;
    int status;
    size_t total = 0;
    if (written != NULL) *written = 0;
    if (archive == NULL || index >= archive->page_count || output == NULL || written == NULL ||
        capacity != (size_t)archive->pages[index].size_bytes) {
        set_error(error, "ARCHIVE_ARGUMENT_INVALID", "Archive page buffer is invalid");
        return 0;
    }
    reader = new_reader(error);
    if (reader == NULL) return 0;
    if (archive_read_open_filename(reader, archive->path, 64 * 1024) != ARCHIVE_OK) {
        set_reader_error(error, "ARCHIVE_OPEN_FAILED", archive_error_string(reader));
        archive_read_free(reader);
        return 0;
    }
    while ((status = archive_read_next_header(reader, &entry)) == ARCHIVE_OK) {
        const char *entry_path = archive_entry_pathname_utf8(entry);
        if (entry_path == NULL) entry_path = archive_entry_pathname(entry);
        if (strcmp(entry_path, archive->pages[index].path) != 0) {
            if (archive_read_data_skip(reader) < ARCHIVE_WARN) break;
            continue;
        }
        while (total < capacity) {
            la_ssize_t count = archive_read_data(reader, output + total, capacity - total);
            if (count < 0) {
                set_reader_error(error, "ARCHIVE_DATA_INVALID", archive_error_string(reader));
                archive_read_free(reader);
                return 0;
            }
            if (count == 0) break;
            total += (size_t)count;
        }
        if (total != capacity) {
            set_error(error, "ARCHIVE_DATA_TRUNCATED", "Archive page ended before its declared size");
            archive_read_free(reader);
            return 0;
        }
        *written = total;
        archive_read_free(reader);
        return 1;
    }
    if (status == ARCHIVE_EOF) {
        set_error(error, "ARCHIVE_PAGE_MISSING", "Archive page is missing");
    } else {
        set_reader_error(error, "ARCHIVE_PAGE_MISSING", archive_error_string(reader));
    }
    archive_read_free(reader);
    return 0;
}

void ermao_archive_close(ermao_archive *archive) {
    if (archive == NULL) return;
    free_pages(archive);
    free(archive->path);
    free(archive);
}

const char *ermao_archive_version(void) {
    return archive_version_string();
}
