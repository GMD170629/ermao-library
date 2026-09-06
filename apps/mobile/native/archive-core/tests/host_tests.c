#if !defined(_WIN32)
#define _POSIX_C_SOURCE 200809L
#endif

#include "archive_core.h"
#include "reader_safety_policy.generated.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if defined(_WIN32)
#include <windows.h>
#else
#include <unistd.h>
#endif

typedef struct {
    const char *name;
    const unsigned char *bytes;
    size_t size;
    int symlink;
} test_zip_entry;

typedef struct {
    unsigned char *bytes;
    size_t length;
    size_t capacity;
} test_zip_buffer;

static int append_bytes(test_zip_buffer *buffer, const void *source, size_t length) {
    unsigned char *resized;
    size_t required;
    if (length > SIZE_MAX - buffer->length) return 0;
    required = buffer->length + length;
    if (required > buffer->capacity) {
        size_t capacity = buffer->capacity == 0 ? 256U : buffer->capacity;
        while (capacity < required) {
            if (capacity > SIZE_MAX / 2U) {
                capacity = required;
                break;
            }
            capacity *= 2U;
        }
        resized = realloc(buffer->bytes, capacity);
        if (resized == NULL) return 0;
        buffer->bytes = resized;
        buffer->capacity = capacity;
    }
    memcpy(buffer->bytes + buffer->length, source, length);
    buffer->length += length;
    return 1;
}

static int append_u16(test_zip_buffer *buffer, uint16_t value) {
    unsigned char encoded[2] = {
        (unsigned char)(value & 0xffU),
        (unsigned char)((value >> 8U) & 0xffU)
    };
    return append_bytes(buffer, encoded, sizeof(encoded));
}

static int append_u32(test_zip_buffer *buffer, uint32_t value) {
    unsigned char encoded[4] = {
        (unsigned char)(value & 0xffU),
        (unsigned char)((value >> 8U) & 0xffU),
        (unsigned char)((value >> 16U) & 0xffU),
        (unsigned char)((value >> 24U) & 0xffU)
    };
    return append_bytes(buffer, encoded, sizeof(encoded));
}

static uint32_t crc32_bytes(const unsigned char *bytes, size_t length) {
    uint32_t crc = 0xffffffffU;
    size_t index;
    for (index = 0; index < length; index++) {
        unsigned int bit;
        crc ^= bytes[index];
        for (bit = 0; bit < 8U; bit++) {
            crc = (crc >> 1U) ^ (0xedb88320U & (uint32_t)-(int)(crc & 1U));
        }
    }
    return ~crc;
}

static int write_test_zip(
    const char *path,
    const test_zip_entry *entries,
    size_t entry_count,
    size_t corrupt_index
) {
    test_zip_buffer buffer = {0};
    size_t *local_offsets = NULL;
    size_t *data_offsets = NULL;
    uint32_t *crcs = NULL;
    size_t central_offset;
    size_t index;
    FILE *file;
    int ok = 0;

    local_offsets = calloc(entry_count, sizeof(*local_offsets));
    data_offsets = calloc(entry_count, sizeof(*data_offsets));
    crcs = calloc(entry_count, sizeof(*crcs));
    if (local_offsets == NULL || data_offsets == NULL || crcs == NULL) goto cleanup;
    for (index = 0; index < entry_count; index++) {
        size_t name_length = strlen(entries[index].name);
        if (name_length > UINT16_MAX || entries[index].size > UINT32_MAX) goto cleanup;
        local_offsets[index] = buffer.length;
        crcs[index] = crc32_bytes(entries[index].bytes, entries[index].size);
        if (!append_u32(&buffer, 0x04034b50U) ||
            !append_u16(&buffer, 20U) ||
            !append_u16(&buffer, 0U) ||
            !append_u16(&buffer, 0U) ||
            !append_u16(&buffer, 0U) ||
            !append_u16(&buffer, 0U) ||
            !append_u32(&buffer, crcs[index]) ||
            !append_u32(&buffer, (uint32_t)entries[index].size) ||
            !append_u32(&buffer, (uint32_t)entries[index].size) ||
            !append_u16(&buffer, (uint16_t)name_length) ||
            !append_u16(&buffer, 0U) ||
            !append_bytes(&buffer, entries[index].name, name_length)) goto cleanup;
        data_offsets[index] = buffer.length;
        if (!append_bytes(&buffer, entries[index].bytes, entries[index].size)) goto cleanup;
    }
    central_offset = buffer.length;
    for (index = 0; index < entry_count; index++) {
        size_t name_length = strlen(entries[index].name);
        uint32_t external_attributes = entries[index].symlink
            ? ((uint32_t)(0120000U | 0777U) << 16U)
            : ((uint32_t)(0100644U) << 16U);
        if (!append_u32(&buffer, 0x02014b50U) ||
            !append_u16(&buffer, 0x0314U) ||
            !append_u16(&buffer, 20U) ||
            !append_u16(&buffer, 0U) ||
            !append_u16(&buffer, 0U) ||
            !append_u16(&buffer, 0U) ||
            !append_u16(&buffer, 0U) ||
            !append_u32(&buffer, crcs[index]) ||
            !append_u32(&buffer, (uint32_t)entries[index].size) ||
            !append_u32(&buffer, (uint32_t)entries[index].size) ||
            !append_u16(&buffer, (uint16_t)name_length) ||
            !append_u16(&buffer, 0U) ||
            !append_u16(&buffer, 0U) ||
            !append_u16(&buffer, 0U) ||
            !append_u16(&buffer, 0U) ||
            !append_u32(&buffer, external_attributes) ||
            !append_u32(&buffer, (uint32_t)local_offsets[index]) ||
            !append_bytes(&buffer, entries[index].name, name_length)) goto cleanup;
    }
    if (buffer.length < central_offset || buffer.length - central_offset > UINT32_MAX ||
        central_offset > UINT32_MAX || entry_count > UINT16_MAX) goto cleanup;
    if (!append_u32(&buffer, 0x06054b50U) ||
        !append_u16(&buffer, 0U) ||
        !append_u16(&buffer, 0U) ||
        !append_u16(&buffer, (uint16_t)entry_count) ||
        !append_u16(&buffer, (uint16_t)entry_count) ||
        !append_u32(&buffer, (uint32_t)(buffer.length - central_offset)) ||
        !append_u32(&buffer, (uint32_t)central_offset) ||
        !append_u16(&buffer, 0U)) goto cleanup;
    if (corrupt_index < entry_count && entries[corrupt_index].size > 0) {
        buffer.bytes[data_offsets[corrupt_index]] ^= 0xffU;
    }
    file = fopen(path, "wb");
    if (file == NULL) goto cleanup;
    {
        size_t written = fwrite(buffer.bytes, 1, buffer.length, file);
        int close_status = fclose(file);
        ok = written == buffer.length && close_status == 0;
    }

cleanup:
    free(local_offsets);
    free(data_offsets);
    free(crcs);
    free(buffer.bytes);
    return ok;
}

static int make_temporary_path(char *path, size_t capacity) {
#if defined(_WIN32)
    return tmpnam_s(path, capacity) == 0;
#else
    char template_path[] = "ermao-archive-core-XXXXXX";
    int descriptor = mkstemp(template_path);
    if (descriptor < 0) return 0;
    close(descriptor);
    remove(template_path);
    if (strlen(template_path) + 1U > capacity) return 0;
    memcpy(path, template_path, strlen(template_path) + 1U);
    return 1;
#endif
}

static int verify_archive(const char *path) {
    ermao_archive_limits limits = {
        (size_t)ERMAO_READER_SAFETY_COMIC_PAGE_MAX_COUNT,
        ERMAO_READER_SAFETY_COMIC_PAGE_MAX_BYTES,
        ERMAO_READER_SAFETY_COMIC_EXPANDED_MAX_BYTES
    };
    ermao_archive_error error = {{0}, {0}};
    ermao_archive *archive = NULL;
    size_t page_count;
    size_t index;
    if (!ermao_archive_open(path, limits, &archive, &error)) {
        fprintf(stderr, "%s: %s: %s\n", path, error.code, error.message);
        return 0;
    }
    page_count = ermao_archive_page_count(archive);
    for (index = 0; index < page_count; index++) {
        const char *entry_path = NULL;
        int64_t size_bytes = 0;
        unsigned char *bytes;
        size_t written = 0;
        if (!ermao_archive_page_info(archive, index, &entry_path, &size_bytes, &error) ||
            entry_path == NULL || size_bytes <= 0) {
            fprintf(stderr, "%s[%zu]: invalid page info\n", path, index);
            ermao_archive_close(archive);
            return 0;
        }
        bytes = malloc((size_t)size_bytes);
        if (bytes == NULL || !ermao_archive_read_page(
                archive, index, bytes, (size_t)size_bytes, &written, &error
            ) || written != (size_t)size_bytes) {
            fprintf(stderr, "%s[%zu] (%s): %s: %s\n", path, index, entry_path, error.code, error.message);
            free(bytes);
            ermao_archive_close(archive);
            return 0;
        }
        free(bytes);
    }
    printf("%s: %zu pages\n", path, page_count);
    ermao_archive_close(archive);
    return 1;
}

static int verify_symlink_isolated(const char *path) {
    ermao_archive_limits limits = {
        (size_t)ERMAO_READER_SAFETY_COMIC_PAGE_MAX_COUNT,
        ERMAO_READER_SAFETY_COMIC_PAGE_MAX_BYTES,
        ERMAO_READER_SAFETY_COMIC_EXPANDED_MAX_BYTES
    };
    ermao_archive_error error = {{0}, {0}};
    ermao_archive *archive = NULL;
    const char *entry_path = NULL;
    int64_t size_bytes = 0;
    int ok = 0;
    if (!ermao_archive_open(path, limits, &archive, &error)) goto cleanup;
    if (ermao_archive_page_count(archive) != 1U ||
        !ermao_archive_page_info(archive, 0, &entry_path, &size_bytes, &error) ||
        entry_path == NULL || strcmp(entry_path, "good.weird") != 0 || size_bytes <= 0) goto cleanup;
    ok = 1;
cleanup:
    if (archive != NULL) ermao_archive_close(archive);
    if (!ok) fprintf(stderr, "%s: symlink isolation failed: %s: %s\n", path, error.code, error.message);
    return ok;
}

static int verify_resource_isolation(void) {
    static const unsigned char page[] = "page";
    static const unsigned char second[] = "second";
    static const unsigned char normal[] = "normal";
    static const unsigned char case_lower[] = "lower";
    static const unsigned char case_upper[] = "upper";
    static const unsigned char collision[] = "collision";
    static const unsigned char unsafe[] = "unsafe";
    static const unsigned char corrupt[] = "corrupt";
    const test_zip_entry entries[] = {
        {"good/corrupt.unknown", corrupt, sizeof(corrupt) - 1U, 0},
        {"good/./page.weird", page, sizeof(page) - 1U, 0},
        {"good\\second.bin", second, sizeof(second) - 1U, 0},
        {"good/case.bin", case_lower, sizeof(case_lower) - 1U, 0},
        {"GOOD/case.bin", case_upper, sizeof(case_upper) - 1U, 0},
        {"good/../normal.dat", normal, sizeof(normal) - 1U, 0},
        {"good/./collision.dat", collision, sizeof(collision) - 1U, 0},
        {"good/collision.dat", collision, sizeof(collision) - 1U, 0},
        {"../ignored.dat", unsafe, sizeof(unsafe) - 1U, 0}
    };
    ermao_archive_limits limits = {
        (size_t)ERMAO_READER_SAFETY_COMIC_PAGE_MAX_COUNT,
        ERMAO_READER_SAFETY_COMIC_PAGE_MAX_BYTES,
        ERMAO_READER_SAFETY_COMIC_EXPANDED_MAX_BYTES
    };
    ermao_archive_error error = {{0}, {0}};
    ermao_archive *archive = NULL;
    char temporary_path[512] = {0};
    size_t page_count;
    size_t index;
    int found_corrupt = 0;
    int found_good_after_corrupt = 0;
    int ok = 0;

    if (!make_temporary_path(temporary_path, sizeof(temporary_path))) {
        fprintf(stderr, "resource isolation temp path failed\n");
        goto cleanup;
    }
    if (!write_test_zip(
            temporary_path,
            entries,
            sizeof(entries) / sizeof(entries[0]),
            sizeof(entries) / sizeof(entries[0])
        )) {
        fprintf(stderr, "resource isolation fixture write failed: %s\n", temporary_path);
        goto cleanup;
    }
    /* Corrupt only the first entry's data, leaving its CRC fields intact. */
    {
        FILE *file = fopen(temporary_path, "r+b");
        unsigned char byte;
        long offset = 30L + (long)strlen(entries[0].name);
        if (file == NULL || fseek(file, offset, SEEK_SET) != 0 ||
            fread(&byte, 1, 1, file) != 1 || fseek(file, offset, SEEK_SET) != 0) {
            if (file != NULL) fclose(file);
            goto cleanup;
        }
        byte ^= 0xffU;
        {
            size_t written = fwrite(&byte, 1, 1, file);
            int close_status = fclose(file);
            if (written != 1 || close_status != 0) goto cleanup;
        }
    }
    if (!ermao_archive_open(temporary_path, limits, &archive, &error)) {
        fprintf(stderr, "resource isolation open: %s: %s\n", error.code, error.message);
        goto cleanup;
    }
    page_count = ermao_archive_page_count(archive);
    if (page_count != 6U) {
        goto cleanup;
    }
    for (index = 0; index < page_count; index++) {
        const char *entry_path = NULL;
        int64_t size_bytes = 0;
        unsigned char *bytes;
        size_t written = 0;
        if (!ermao_archive_page_info(archive, index, &entry_path, &size_bytes, &error) ||
            entry_path == NULL || size_bytes <= 0) goto cleanup;
        if (strstr(entry_path, "corrupt") != NULL) {
            found_corrupt = 1;
            bytes = malloc((size_t)size_bytes);
            if (bytes == NULL || ermao_archive_read_page(
                    archive, index, bytes, (size_t)size_bytes, &written, &error
                ) || strcmp(error.code, "ARCHIVE_DATA_INVALID") != 0) {
                free(bytes);
                goto cleanup;
            }
            free(bytes);
        } else {
            bytes = malloc((size_t)size_bytes);
            if (bytes == NULL || !ermao_archive_read_page(
                    archive, index, bytes, (size_t)size_bytes, &written, &error
                ) || written != (size_t)size_bytes) {
                free(bytes);
                goto cleanup;
            }
            if (found_corrupt) found_good_after_corrupt = 1;
            free(bytes);
        }
    }
    if (!found_corrupt || !found_good_after_corrupt) goto cleanup;
    ermao_archive_close(archive);
    archive = NULL;
    {
        ermao_archive_limits small_limits = limits;
        small_limits.maximum_page_bytes = 3;
        if (ermao_archive_open(temporary_path, small_limits, &archive, &error) ||
            strcmp(error.code, "ARCHIVE_PAGE_LIMIT_EXCEEDED") != 0) {
            if (archive != NULL) {
                ermao_archive_close(archive);
                archive = NULL;
            }
            goto cleanup;
        }
    }
    ok = 1;

cleanup:
    if (archive != NULL) ermao_archive_close(archive);
    if (temporary_path[0] != '\0') remove(temporary_path);
    if (!ok) fprintf(stderr, "resource isolation test failed: %s: %s\n", error.code, error.message);
    return ok;
}

int main(int argc, char **argv) {
    int index;
    if (!verify_resource_isolation()) return 1;
    if (argc < 2) {
        fprintf(stderr, "Expected at least one ZIP/RAR archive path\n");
        return 2;
    }
    printf("%s\n", ermao_archive_version());
    for (index = 1; index < argc; index++) {
        if (strstr(argv[index], "good-plus-symlink.zip") != NULL &&
            !verify_symlink_isolated(argv[index])) return 1;
        if (!verify_archive(argv[index])) return 1;
    }
    return 0;
}
