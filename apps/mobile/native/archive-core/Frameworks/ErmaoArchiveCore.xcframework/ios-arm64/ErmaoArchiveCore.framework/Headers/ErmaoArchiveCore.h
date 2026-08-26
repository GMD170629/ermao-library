#ifndef ERMAO_ARCHIVE_CORE_H
#define ERMAO_ARCHIVE_CORE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ermao_archive ermao_archive;

typedef struct {
    size_t maximum_entries;
    int64_t maximum_page_bytes;
    int64_t maximum_expanded_bytes;
} ermao_archive_limits;

typedef struct {
    char code[64];
    char message[256];
} ermao_archive_error;

int ermao_archive_open(
    const char *path,
    ermao_archive_limits limits,
    ermao_archive **result,
    ermao_archive_error *error
);

size_t ermao_archive_page_count(const ermao_archive *archive);

int ermao_archive_page_info(
    const ermao_archive *archive,
    size_t index,
    const char **path,
    int64_t *size_bytes,
    ermao_archive_error *error
);

int ermao_archive_read_page(
    const ermao_archive *archive,
    size_t index,
    unsigned char *output,
    size_t capacity,
    size_t *written,
    ermao_archive_error *error
);

void ermao_archive_close(ermao_archive *archive);

const char *ermao_archive_version(void);

#ifdef __cplusplus
}
#endif

#endif
