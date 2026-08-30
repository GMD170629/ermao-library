#include "ermao_mobi.h"

#include <assert.h>
#include <dirent.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static bool has_publication_extension(const char *name) {
    const char *dot = strrchr(name, '.');
    return dot != NULL
        && (strcmp(dot, ".mobi") == 0 || strcmp(dot, ".azw") == 0
            || strcmp(dot, ".azw3") == 0 || strcmp(dot, ".prc") == 0);
}

static void make_path(char *path, size_t capacity, const char *directory, const char *name) {
    const int written = snprintf(path, capacity, "%s/%s", directory, name);
    assert(written > 0 && (size_t) written < capacity);
}

static ErmaoMobiOpenOptions test_open_options(void) {
    ErmaoMobiOpenOptions options;
    ermao_mobi_default_options(&options);
    options.max_file_bytes = UINT64_MAX;
    return options;
}

static void expect_open_status(
    const char *directory,
    const char *name,
    ErmaoMobiStatus expected
) {
    char path[4096];
    make_path(path, sizeof(path), directory, name);
    ErmaoMobiBook *book = NULL;
    const ErmaoMobiOpenOptions options = test_open_options();
    const ErmaoMobiStatus actual = ermao_mobi_open(path, &options, &book);
    if (actual != expected) fprintf(stderr, "%s: expected %s, actual %s\n", name,
        ermao_mobi_status_name(expected), ermao_mobi_status_name(actual));
    assert(actual == expected);
    assert(book == NULL);
}

static char *copy_string(
    ErmaoMobiStatus (*copy_fn)(const ErmaoMobiBook *, uint32_t, char *, uint32_t, uint32_t *),
    const ErmaoMobiBook *book,
    uint32_t index
) {
    uint32_t required = 0u;
    assert(copy_fn(book, index, NULL, 0u, &required) == ERMAO_MOBI_BUFFER_TOO_SMALL);
    assert(required > 1u);
    char *value = malloc(required);
    assert(value != NULL);
    assert(copy_fn(book, index, value, required, &required) == ERMAO_MOBI_OK);
    return value;
}

static void exercise_book(const char *path) {
    ErmaoMobiBook *book = NULL;
    const ErmaoMobiOpenOptions options = test_open_options();
    assert(ermao_mobi_open(path, &options, &book) == ERMAO_MOBI_OK);
    assert(book != NULL);

    ErmaoMobiBookInfo book_info = {.struct_size = sizeof(book_info)};
    assert(ermao_mobi_get_book_info(book, &book_info) == ERMAO_MOBI_OK);
    assert(book_info.resource_count > 0u);
    assert(book_info.reading_order_count > 0u);

    uint32_t resource_count = 0u;
    assert(ermao_mobi_resource_count(book, &resource_count) == ERMAO_MOBI_OK);
    assert(resource_count == book_info.resource_count);

    for (uint32_t index = 0u; index < resource_count; index++) {
        ErmaoMobiResourceInfo info = {.struct_size = sizeof(info)};
        assert(ermao_mobi_get_resource_info(book, index, &info) == ERMAO_MOBI_OK);
        char *name = copy_string(ermao_mobi_copy_resource_source_name, book, index);
        char *media_type = copy_string(ermao_mobi_copy_resource_media_type, book, index);
        assert(name[0] != '\0');
        assert(media_type[0] != '\0');
        free(name);
        free(media_type);

        uint8_t buffer[257];
        uint32_t bytes_read = 99u;
        assert(ermao_mobi_read_resource(book, index, 0u, buffer, 0u, &bytes_read) == ERMAO_MOBI_OK);
        assert(bytes_read == 0u);
        assert(ermao_mobi_read_resource(book, index, 0u, buffer, sizeof(buffer), &bytes_read) == ERMAO_MOBI_OK);
        assert(bytes_read <= sizeof(buffer));
        assert(ermao_mobi_read_resource(book, index, info.decoded_length, NULL, 0u, &bytes_read) == ERMAO_MOBI_OK);
        assert(bytes_read == 0u);
        assert(ermao_mobi_read_resource(book, index, info.decoded_length + 1u, buffer, 1u, &bytes_read) == ERMAO_MOBI_OUT_OF_RANGE);
    }

    uint32_t reading_count = 0u;
    assert(ermao_mobi_reading_order_count(book, &reading_count) == ERMAO_MOBI_OK);
    for (uint32_t position = 0u; position < reading_count; position++) {
        uint32_t resource_index = ERMAO_MOBI_INDEX_NONE;
        assert(ermao_mobi_reading_order_resource_index(book, position, &resource_index) == ERMAO_MOBI_OK);
        assert(resource_index < resource_count);
    }

    uint32_t toc_count = 0u;
    assert(ermao_mobi_toc_count(book, &toc_count) == ERMAO_MOBI_OK);
    for (uint32_t index = 0u; index < toc_count; index++) {
        ErmaoMobiTocInfo info = {.struct_size = sizeof(info)};
        assert(ermao_mobi_get_toc_info(book, index, &info) == ERMAO_MOBI_OK);
        assert(info.parent_index == ERMAO_MOBI_INDEX_NONE || info.parent_index < index);
        assert(info.target_resource_index == ERMAO_MOBI_INDEX_NONE
               || info.target_resource_index < resource_count);
    }

    ermao_mobi_close(&book);
    assert(book == NULL);
    ermao_mobi_close(&book);
}

static void exercise_abi_edges(const char *directory) {
    char path[4096];
    make_path(path, sizeof(path), directory, "01-basic-mobi6.mobi");

    ErmaoMobiBook *book = NULL;
    assert(ermao_mobi_open(path, NULL, NULL) == ERMAO_MOBI_INVALID_ARGUMENT);
    ErmaoMobiOpenOptions options;
    ermao_mobi_default_options(&options);
    options.struct_size = 0u;
    assert(ermao_mobi_open(path, &options, &book) == ERMAO_MOBI_INVALID_ARGUMENT);
    ermao_mobi_default_options(&options);
    options.max_file_bytes = 1u;
    assert(ermao_mobi_open(path, &options, &book) == ERMAO_MOBI_LIMIT_EXCEEDED);
    ermao_mobi_default_options(&options);
    options.max_file_bytes = UINT64_MAX;
    options.max_read_bytes = 1u;
    assert(ermao_mobi_open(path, &options, &book) == ERMAO_MOBI_OK);

    ErmaoMobiBookInfo invalid_info = {.struct_size = 0u};
    assert(ermao_mobi_get_book_info(book, &invalid_info) == ERMAO_MOBI_INVALID_ARGUMENT);
    uint32_t required = 0u;
    char small_buffer[1];
    assert(ermao_mobi_copy_metadata(
               book,
               ERMAO_MOBI_METADATA_TITLE,
               small_buffer,
               sizeof(small_buffer),
               &required
           ) == ERMAO_MOBI_BUFFER_TOO_SMALL);
    assert(required > sizeof(small_buffer));
    required = 99u;
    assert(ermao_mobi_copy_metadata(
               book,
               ERMAO_MOBI_METADATA_PUBLISHER,
               NULL,
               0u,
               &required
           ) == ERMAO_MOBI_NOT_FOUND);
    assert(required == 0u);
    uint32_t bytes_read = 99u;
    assert(ermao_mobi_read_resource(book, 0u, 0u, NULL, 2u, &bytes_read)
           == ERMAO_MOBI_LIMIT_EXCEEDED);
    assert(bytes_read == 0u);
    assert(ermao_mobi_resource_count(book, NULL) == ERMAO_MOBI_INVALID_ARGUMENT);
    assert(ermao_mobi_get_resource_info(book, UINT32_MAX, NULL) == ERMAO_MOBI_INVALID_ARGUMENT);
    assert(strcmp(ermao_mobi_status_name((ErmaoMobiStatus) 999), "internal") == 0);
    ermao_mobi_close(&book);

    options = test_open_options();
    assert(ermao_mobi_open(directory, &options, &book) == ERMAO_MOBI_UNSUPPORTED);
}

int main(int argc, char **argv) {
    assert(ermao_mobi_abi_version() == ERMAO_MOBI_ABI_VERSION);
    assert(strcmp(ermao_mobi_normalization_identifier(), "ermao-mobi-core-v1") == 0);
    assert(strstr(ermao_mobi_parser_identifier(), "85dcfe803fc2a210") != NULL);

    ErmaoMobiBook *book = NULL;
    const ErmaoMobiOpenOptions options = test_open_options();
    assert(ermao_mobi_open(NULL, NULL, &book) == ERMAO_MOBI_INVALID_ARGUMENT);
    assert(ermao_mobi_open("", NULL, &book) == ERMAO_MOBI_INVALID_ARGUMENT);
    assert(ermao_mobi_open("/definitely/missing/ermao.mobi", &options, &book) == ERMAO_MOBI_FILE_NOT_FOUND);

    if (argc != 2) {
        fprintf(stderr, "usage: %s <corpus-directory>\n", argv[0]);
        return 2;
    }
    DIR *directory = opendir(argv[1]);
    assert(directory != NULL);
    uint32_t publication_count = 0u;
    char first_fixture[4096] = {0};
    struct dirent *entry = NULL;
    while ((entry = readdir(directory)) != NULL) {
        if (!has_publication_extension(entry->d_name)
            || strncmp(entry->d_name, "negative-", strlen("negative-")) == 0) {
            continue;
        }
        char path[4096];
        make_path(path, sizeof(path), argv[1], entry->d_name);
        exercise_book(path);
        if (first_fixture[0] == '\0') {
            const size_t path_length = strlen(path);
            memcpy(first_fixture, path, path_length + 1u);
        }
        publication_count++;
    }
    closedir(directory);
    assert(publication_count >= 13u);
    exercise_abi_edges(argv[1]);

    expect_open_status(
        argv[1],
        "negative-synthetic-drm-header.mobi",
        ERMAO_MOBI_DRM_PROTECTED
    );
    expect_open_status(
        argv[1],
        "negative-upstream-drm-v1.mobi",
        ERMAO_MOBI_DRM_PROTECTED
    );
    expect_open_status(argv[1], "negative-no-content.mobi", ERMAO_MOBI_CORRUPT);
    expect_open_status(argv[1], "negative-truncated.mobi", ERMAO_MOBI_CORRUPT);
    expect_open_status(argv[1], "negative-corrupt-record-offset.mobi", ERMAO_MOBI_CORRUPT);
    expect_open_status(argv[1], "negative-pseudo.mobi", ERMAO_MOBI_CORRUPT);
    expect_open_status(argv[1], "negative-synthetic-kfx.kfx", ERMAO_MOBI_CORRUPT);
    expect_open_status(argv[1], "negative-synthetic-azw4.azw4", ERMAO_MOBI_CORRUPT);

    for (uint32_t iteration = 0u; iteration < 1000u; iteration++) {
        assert(ermao_mobi_open(first_fixture, &options, &book) == ERMAO_MOBI_OK);
        ermao_mobi_close(&book);
    }
    puts("ermao_mobi_host_tests: ok");
    return 0;
}
