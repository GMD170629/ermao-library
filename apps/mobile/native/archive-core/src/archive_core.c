#include "archive_core.h"
#include "reader_safety_policy.generated.h"

#include <archive.h>
#include <archive_entry.h>
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    char *path;
    char *canonical_path;
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
        contains_case_insensitive(message, "encrypt") ? "ARCHIVE_ENCRYPTED" :
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

/*
 * Keep the archive spelling for the libarchive lookup, while normalizing a
 * second identity for ordering and collision detection.  Backslashes are
 * ordinary archive separators and dot segments are harmless when they stay
 * inside the archive root.  Only an absolute path, a drive-qualified path,
 * or a parent segment that escapes the root makes the resource unusable.
 *
 * Return 1 for a usable path, 0 for an isolated path, and -1 for allocation
 * failure.  The caller deliberately treats an unusable path as a resource
 * fact rather than a publication-fatal archive error.
 */
static int canonicalize_path(const char *path, char **canonical_out) {
    size_t length;
    size_t index = 0;
    size_t canonical_length = 0;
    char *canonical;

    if (canonical_out != NULL) *canonical_out = NULL;
    if (path == NULL || path[0] == '\0' || path[0] == '/' || path[0] == '\\') return 0;
    if (isalpha((unsigned char)path[0]) && path[1] == ':') return 0;
    length = strlen(path);
    canonical = malloc(length + 1U);
    if (canonical == NULL) return -1;

    while (index < length) {
        size_t component_start;
        size_t component_length;

        while (index < length && (path[index] == '/' || path[index] == '\\')) index++;
        if (index == length) break;
        component_start = index;
        while (index < length && path[index] != '/' && path[index] != '\\') index++;
        component_length = index - component_start;
        if (component_length == 1 && path[component_start] == '.') continue;
        if (component_length == 2 && path[component_start] == '.' && path[component_start + 1U] == '.') {
            size_t component_end;
            if (canonical_length == 0) {
                free(canonical);
                return 0;
            }
            component_end = canonical_length;
            while (component_end > 0 && canonical[component_end - 1U] != '/') component_end--;
            canonical_length = component_end == 0 ? 0 : component_end - 1U;
            continue;
        }
        if (canonical_length != 0) canonical[canonical_length++] = '/';
        memcpy(canonical + canonical_length, path + component_start, component_length);
        canonical_length += component_length;
    }
    if (canonical_length == 0) {
        free(canonical);
        return 0;
    }
    canonical[canonical_length] = '\0';
    *canonical_out = canonical;
    return 1;
}

static int compression_ratio_exceeded(int64_t expanded_bytes, int64_t compressed_bytes) {
    const int64_t maximum_ratio = ERMAO_READER_SAFETY_COMIC_COMPRESSION_RATIO_MAX;
    int64_t quotient;
    if (expanded_bytes <= 0) return 0;
    if (compressed_bytes <= 0 || maximum_ratio <= 0) return 1;
    quotient = expanded_bytes / compressed_bytes;
    return quotient > maximum_ratio ||
        (quotient == maximum_ratio && expanded_bytes % compressed_bytes != 0);
}

static int natural_compare(const void *left_value, const void *right_value) {
    const char *left_identity = ((const ermao_archive_page *)left_value)->canonical_path;
    const char *right_identity = ((const ermao_archive_page *)right_value)->canonical_path;
    const unsigned char *left = (const unsigned char *)left_identity;
    const unsigned char *right = (const unsigned char *)right_identity;
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
    if (*left != *right) return *left == '\0' ? -1 : 1;
    /* Case-distinct archive identities are different resources. */
    return strcmp(left_identity, right_identity);
}

static void free_pages(ermao_archive *value) {
    size_t index;
    if (value == NULL) return;
    for (index = 0; index < value->page_count; index++) {
        free(value->pages[index].path);
        free(value->pages[index].canonical_path);
    }
    free(value->pages);
}

static int append_page(
    ermao_archive *value,
    const char *path,
    char *canonical_path,
    int64_t size,
    ermao_archive_error *error
) {
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
    value->pages[value->page_count].canonical_path = canonical_path;
    value->pages[value->page_count].size_bytes = size;
    value->page_count++;
    return 1;
}

static int set_zip_crc_mode(struct archive *reader, int ignore, ermao_archive_error *error) {
    /* libarchive requires options before the stream is opened.  A non-empty
     * value enables ZIP CRC suppression for the indexing pass; normal page
     * readers leave the default strict mode in place. */
    const char *option = ignore ? "zip:ignorecrc32=1" : "zip:ignorecrc32";
    int status = archive_read_set_options(reader, option);
    if (status == ARCHIVE_FATAL) {
        set_reader_error(error, "ARCHIVE_FORMAT_SETUP_FAILED", archive_error_string(reader));
        return 0;
    }
    return 1;
}

static void discard_canonical_conflicts(ermao_archive *value) {
    size_t read_index = 0;
    size_t write_index = 0;
    while (read_index < value->page_count) {
        size_t end_index = read_index + 1U;
        while (end_index < value->page_count &&
               strcmp(value->pages[read_index].canonical_path,
                      value->pages[end_index].canonical_path) == 0) {
            end_index++;
        }
        if (end_index - read_index == 1U) {
            if (write_index != read_index) value->pages[write_index] = value->pages[read_index];
            write_index++;
        } else {
            size_t index;
            for (index = read_index; index < end_index; index++) {
                free(value->pages[index].path);
                free(value->pages[index].canonical_path);
            }
        }
        read_index = end_index;
    }
    value->page_count = write_index;
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
    size_t oversize_resources = 0;
    int64_t expanded_bytes = 0;
    int64_t compressed_bytes;
    int status;
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
    if (!set_zip_crc_mode(reader, 1, error)) goto failure;
    if (archive_read_open_filename(reader, path, 64 * 1024) != ARCHIVE_OK) {
        set_reader_error(error, "ARCHIVE_OPEN_FAILED", archive_error_string(reader));
        goto failure;
    }
    while ((status = archive_read_next_header(reader, &entry)) == ARCHIVE_OK) {
        const char *entry_path = archive_entry_pathname_utf8(entry);
        char *canonical_path = NULL;
        int path_status;
        int64_t size;
        if (entry_path == NULL) entry_path = archive_entry_pathname(entry);
        entries_seen++;
        if (entries_seen > limits.maximum_entries) {
            set_error(error, "ARCHIVE_PAGE_COUNT_EXCEEDED", "Archive contains too many archive entries");
            goto failure;
        }
        if (archive_entry_size_is_set(entry) && (size = archive_entry_size(entry)) >= 0) {
            if (expanded_bytes > limits.maximum_expanded_bytes - size) {
                set_error(error, "ARCHIVE_EXPANDED_LIMIT_EXCEEDED", "Archive expanded size is too large");
                goto failure;
            }
            expanded_bytes += size;
        }
        if (archive_entry_filetype(entry) == AE_IFDIR) {
            if (archive_read_data_skip(reader) == ARCHIVE_FATAL) {
                set_reader_error(error, "ARCHIVE_DATA_INVALID", archive_error_string(reader));
                goto failure;
            }
            continue;
        }
        if (archive_entry_filetype(entry) != AE_IFREG || archive_entry_symlink(entry) != NULL ||
            archive_entry_hardlink(entry) != NULL) {
            /* Links and other entry kinds are isolated resources. */
            if (archive_read_data_skip(reader) == ARCHIVE_FATAL) {
                set_reader_error(error, "ARCHIVE_DATA_INVALID", archive_error_string(reader));
                goto failure;
            }
            continue;
        }
        if (!archive_entry_size_is_set(entry) || (size = archive_entry_size(entry)) < 0) {
            /* An unreadable optional entry does not poison other pages. */
            if (archive_read_data_skip(reader) == ARCHIVE_FATAL) {
                set_reader_error(error, "ARCHIVE_DATA_INVALID", archive_error_string(reader));
                goto failure;
            }
            continue;
        }
        if (size > limits.maximum_page_bytes) oversize_resources++;
        path_status = canonicalize_path(entry_path, &canonical_path);
        if (path_status < 0) {
            set_error(error, "ARCHIVE_OUT_OF_MEMORY", "Unable to normalize archive resource path");
            goto failure;
        }
        if (path_status == 1 && size > 0 && size <= limits.maximum_page_bytes &&
            !append_page(value, entry_path, canonical_path, size, error)) {
            free(canonical_path);
            goto failure;
        }
        if (path_status == 1 && (size <= 0 || size > limits.maximum_page_bytes)) free(canonical_path);
        /* Unknown extensions remain candidates for the real decoder. */
        status = archive_read_data_skip(reader);
        if (status == ARCHIVE_FATAL) {
            set_reader_error(error, "ARCHIVE_DATA_INVALID", archive_error_string(reader));
            goto failure;
        }
    }
    if (status != ARCHIVE_EOF) {
        set_reader_error(error, "ARCHIVE_HEADER_INVALID", archive_error_string(reader));
        goto failure;
    }
    compressed_bytes = archive_filter_bytes(reader, -1);
    if (compression_ratio_exceeded(expanded_bytes, compressed_bytes)) {
        set_error(error, "ARCHIVE_COMPRESSION_RATIO_EXCEEDED", "Archive compression ratio is too large");
        goto failure;
    }
    archive_read_free(reader);
    reader = NULL;
    if (value->page_count == 0) {
        if (oversize_resources > 0) {
            set_error(error, "ARCHIVE_PAGE_LIMIT_EXCEEDED", "Archive resource exceeds its page byte limit");
            goto failure;
        }
        set_error(error, "ARCHIVE_NO_IMAGES", "Archive contains no readable archive resources");
        goto failure;
    }
    qsort(value->pages, value->page_count, sizeof(*value->pages), natural_compare);
    discard_canonical_conflicts(value);
    if (value->page_count == 0) {
        set_error(error, "ARCHIVE_NO_IMAGES", "Archive contains no readable archive resources");
        goto failure;
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
        if (entry_path == NULL || strcmp(entry_path, archive->pages[index].path) != 0) {
            /* A failed optional entry is isolated by libarchive and leaves
             * the stream ready for the next header; only FATAL ends lookup. */
            if (archive_read_data_skip(reader) == ARCHIVE_FATAL) break;
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
        {
            unsigned char trailing_byte;
            la_ssize_t trailing = archive_read_data(reader, &trailing_byte, 1);
            if (trailing < 0) {
                set_reader_error(error, "ARCHIVE_DATA_INVALID", archive_error_string(reader));
                archive_read_free(reader);
                return 0;
            }
            if (trailing > 0) {
                set_error(error, "ARCHIVE_DATA_INVALID", "Archive page exceeds its declared size");
                archive_read_free(reader);
                return 0;
            }
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
