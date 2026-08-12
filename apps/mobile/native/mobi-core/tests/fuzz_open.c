#include "ermao_mobi.h"

#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    if (data == NULL || size == 0u || size > 1024u * 1024u) {
        return 0;
    }
    char path[] = "/tmp/ermao-mobi-fuzz-XXXXXX";
    const int descriptor = mkstemp(path);
    if (descriptor < 0) {
        return 0;
    }
    size_t written = 0u;
    while (written < size) {
        const ssize_t result = write(descriptor, data + written, size - written);
        if (result <= 0) {
            close(descriptor);
            unlink(path);
            return 0;
        }
        written += (size_t) result;
    }
    close(descriptor);

    ErmaoMobiOpenOptions options;
    ermao_mobi_default_options(&options);
    options.max_file_bytes = 1024u * 1024u;
    ErmaoMobiBook *book = NULL;
    if (ermao_mobi_open(path, &options, &book) == ERMAO_MOBI_OK) {
        ErmaoMobiBookInfo info = {.struct_size = sizeof(info)};
        if (ermao_mobi_get_book_info(book, &info) == ERMAO_MOBI_OK) {
            const uint32_t count = info.resource_count < 8u ? info.resource_count : 8u;
            for (uint32_t index = 0u; index < count; index++) {
                uint8_t buffer[256];
                uint32_t bytes_read = 0u;
                (void) ermao_mobi_read_resource(
                    book,
                    index,
                    0u,
                    buffer,
                    (uint32_t) sizeof(buffer),
                    &bytes_read
                );
            }
        }
        ermao_mobi_close(&book);
    }
    unlink(path);
    return 0;
}
