#include "archive_core.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int supported_image(const unsigned char *bytes, size_t count) {
    static const unsigned char png[] = {0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a};
    return (count >= 3 && bytes[0] == 0xff && bytes[1] == 0xd8 && bytes[2] == 0xff) ||
        (count >= sizeof(png) && memcmp(bytes, png, sizeof(png)) == 0) ||
        (count >= 6 && (memcmp(bytes, "GIF87a", 6) == 0 || memcmp(bytes, "GIF89a", 6) == 0)) ||
        (count >= 12 && memcmp(bytes, "RIFF", 4) == 0 && memcmp(bytes + 8, "WEBP", 4) == 0);
}

static int verify_archive(const char *path) {
    ermao_archive_limits limits = {10000U, 256LL * 1024LL * 1024LL, 4LL * 1024LL * 1024LL * 1024LL};
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
            ) || written != (size_t)size_bytes || !supported_image(bytes, written)) {
            fprintf(stderr, "%s[%zu]: %s: %s\n", path, index, error.code, error.message);
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

int main(int argc, char **argv) {
    int index;
    if (argc < 2) {
        fprintf(stderr, "Expected at least one ZIP/RAR archive path\n");
        return 2;
    }
    printf("%s\n", ermao_archive_version());
    for (index = 1; index < argc; index++) {
        if (!verify_archive(argv[index])) return 1;
    }
    return 0;
}
