#include "ermao_mobi.h"

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct Sha256 {
    uint32_t state[8];
    uint64_t bit_count;
    uint8_t block[64];
    size_t block_size;
} Sha256;

static uint32_t rotate_right(uint32_t value, uint32_t bits) {
    return (value >> bits) | (value << (32u - bits));
}

static void sha256_transform(Sha256 *hash, const uint8_t block[64]) {
    static const uint32_t constants[64] = {
        0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu,
        0x59f111f1u, 0x923f82a4u, 0xab1c5ed5u, 0xd807aa98u, 0x12835b01u,
        0x243185beu, 0x550c7dc3u, 0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u,
        0xc19bf174u, 0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu,
        0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau, 0x983e5152u,
        0xa831c66du, 0xb00327c8u, 0xbf597fc7u, 0xc6e00bf3u, 0xd5a79147u,
        0x06ca6351u, 0x14292967u, 0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu,
        0x53380d13u, 0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u,
        0xa2bfe8a1u, 0xa81a664bu, 0xc24b8b70u, 0xc76c51a3u, 0xd192e819u,
        0xd6990624u, 0xf40e3585u, 0x106aa070u, 0x19a4c116u, 0x1e376c08u,
        0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu,
        0x682e6ff3u, 0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u,
        0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u,
    };
    uint32_t words[64];
    for (uint32_t index = 0u; index < 16u; index++) {
        const uint32_t offset = index * 4u;
        words[index] = ((uint32_t) block[offset] << 24u)
            | ((uint32_t) block[offset + 1u] << 16u)
            | ((uint32_t) block[offset + 2u] << 8u)
            | block[offset + 3u];
    }
    for (uint32_t index = 16u; index < 64u; index++) {
        const uint32_t first = rotate_right(words[index - 15u], 7u)
            ^ rotate_right(words[index - 15u], 18u) ^ (words[index - 15u] >> 3u);
        const uint32_t second = rotate_right(words[index - 2u], 17u)
            ^ rotate_right(words[index - 2u], 19u) ^ (words[index - 2u] >> 10u);
        words[index] = words[index - 16u] + first + words[index - 7u] + second;
    }
    uint32_t a = hash->state[0];
    uint32_t b = hash->state[1];
    uint32_t c = hash->state[2];
    uint32_t d = hash->state[3];
    uint32_t e = hash->state[4];
    uint32_t f = hash->state[5];
    uint32_t g = hash->state[6];
    uint32_t h = hash->state[7];
    for (uint32_t index = 0u; index < 64u; index++) {
        const uint32_t sum_one = rotate_right(e, 6u) ^ rotate_right(e, 11u)
            ^ rotate_right(e, 25u);
        const uint32_t choose = (e & f) ^ ((~e) & g);
        const uint32_t temporary_one = h + sum_one + choose + constants[index] + words[index];
        const uint32_t sum_zero = rotate_right(a, 2u) ^ rotate_right(a, 13u)
            ^ rotate_right(a, 22u);
        const uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
        const uint32_t temporary_two = sum_zero + majority;
        h = g;
        g = f;
        f = e;
        e = d + temporary_one;
        d = c;
        c = b;
        b = a;
        a = temporary_one + temporary_two;
    }
    hash->state[0] += a;
    hash->state[1] += b;
    hash->state[2] += c;
    hash->state[3] += d;
    hash->state[4] += e;
    hash->state[5] += f;
    hash->state[6] += g;
    hash->state[7] += h;
}

static void sha256_initialize(Sha256 *hash) {
    static const uint32_t initial_state[8] = {
        0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
        0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u,
    };
    memcpy(hash->state, initial_state, sizeof(initial_state));
    hash->bit_count = 0u;
    hash->block_size = 0u;
}

static void sha256_update(Sha256 *hash, const uint8_t *bytes, size_t length) {
    hash->bit_count += (uint64_t) length * 8u;
    while (length > 0u) {
        const size_t available = sizeof(hash->block) - hash->block_size;
        const size_t copied = length < available ? length : available;
        memcpy(hash->block + hash->block_size, bytes, copied);
        hash->block_size += copied;
        bytes += copied;
        length -= copied;
        if (hash->block_size == sizeof(hash->block)) {
            sha256_transform(hash, hash->block);
            hash->block_size = 0u;
        }
    }
}

static void sha256_finish(Sha256 *hash, uint8_t digest[32]) {
    const uint64_t bit_count = hash->bit_count;
    const uint8_t marker = 0x80u;
    sha256_update(hash, &marker, 1u);
    const uint8_t zero = 0u;
    while (hash->block_size != 56u) {
        sha256_update(hash, &zero, 1u);
    }
    uint8_t length_bytes[8];
    for (uint32_t index = 0u; index < 8u; index++) {
        length_bytes[7u - index] = (uint8_t) (bit_count >> (index * 8u));
    }
    sha256_update(hash, length_bytes, sizeof(length_bytes));
    for (uint32_t index = 0u; index < 8u; index++) {
        digest[index * 4u] = (uint8_t) (hash->state[index] >> 24u);
        digest[index * 4u + 1u] = (uint8_t) (hash->state[index] >> 16u);
        digest[index * 4u + 2u] = (uint8_t) (hash->state[index] >> 8u);
        digest[index * 4u + 3u] = (uint8_t) hash->state[index];
    }
}

static void print_hex(const uint8_t *bytes, size_t length) {
    static const char digits[] = "0123456789abcdef";
    for (size_t index = 0u; index < length; index++) {
        putchar(digits[bytes[index] >> 4u]);
        putchar(digits[bytes[index] & 0x0fu]);
    }
}

static char *copy_indexed_string(
    ErmaoMobiStatus (*copy_function)(
        const ErmaoMobiBook *, uint32_t, char *, uint32_t, uint32_t *
    ),
    const ErmaoMobiBook *book,
    uint32_t index
) {
    uint32_t required = 0u;
    const ErmaoMobiStatus query = copy_function(book, index, NULL, 0u, &required);
    if (query == ERMAO_MOBI_NOT_FOUND) {
        return NULL;
    }
    if (query != ERMAO_MOBI_BUFFER_TOO_SMALL || required == 0u) {
        return NULL;
    }
    char *value = malloc(required);
    if (value == NULL || copy_function(book, index, value, required, &required) != ERMAO_MOBI_OK) {
        free(value);
        return NULL;
    }
    return value;
}

static char *copy_metadata_string(const ErmaoMobiBook *book, ErmaoMobiMetadataField field) {
    uint32_t required = 0u;
    const ErmaoMobiStatus query = ermao_mobi_copy_metadata(book, field, NULL, 0u, &required);
    if (query == ERMAO_MOBI_NOT_FOUND) {
        return NULL;
    }
    if (query != ERMAO_MOBI_BUFFER_TOO_SMALL || required == 0u) {
        return NULL;
    }
    char *value = malloc(required);
    if (value == NULL
        || ermao_mobi_copy_metadata(book, field, value, required, &required) != ERMAO_MOBI_OK) {
        free(value);
        return NULL;
    }
    return value;
}

static void print_nullable_hex(const char *value) {
    if (value == NULL) {
        putchar('-');
    } else {
        print_hex((const uint8_t *) value, strlen(value));
    }
}

static int snapshot(const ErmaoMobiBook *book) {
    ErmaoMobiBookInfo info = {.struct_size = sizeof(info)};
    if (ermao_mobi_get_book_info(book, &info) != ERMAO_MOBI_OK) {
        return 1;
    }
    puts("snapshot-version\t1");
    printf("abi\t%u\n", ermao_mobi_abi_version());
    printf("parser\t");
    print_nullable_hex(ermao_mobi_parser_identifier());
    printf("\nnormalization\t");
    print_nullable_hex(ermao_mobi_normalization_identifier());
    printf("\nbook\t%u\t%u\t%u\n", info.format, info.reading_direction, info.cover_resource_index);

    for (uint32_t field = ERMAO_MOBI_METADATA_TITLE;
         field <= ERMAO_MOBI_METADATA_DESCRIPTION;
         field++) {
        char *value = copy_metadata_string(book, (ErmaoMobiMetadataField) field);
        printf("metadata\t%u\t", field);
        print_nullable_hex(value);
        putchar('\n');
        free(value);
    }

    uint8_t buffer[8192];
    for (uint32_t index = 0u; index < info.resource_count; index++) {
        ErmaoMobiResourceInfo resource = {.struct_size = sizeof(resource)};
        if (ermao_mobi_get_resource_info(book, index, &resource) != ERMAO_MOBI_OK) {
            return 1;
        }
        Sha256 hash;
        sha256_initialize(&hash);
        uint64_t offset = 0u;
        while (offset < resource.decoded_length) {
            uint32_t read = 0u;
            if (ermao_mobi_read_resource(book, index, offset, buffer, sizeof(buffer), &read)
                    != ERMAO_MOBI_OK
                || read == 0u) {
                return 1;
            }
            sha256_update(&hash, buffer, read);
            offset += read;
        }
        uint8_t digest[32];
        sha256_finish(&hash, digest);
        char *name = copy_indexed_string(ermao_mobi_copy_resource_source_name, book, index);
        char *media_type = copy_indexed_string(ermao_mobi_copy_resource_media_type, book, index);
        printf(
            "resource\t%u\t%u\t%" PRIu64 "\t%" PRIu64 "\t",
            index,
            resource.category,
            resource.source_uid,
            resource.decoded_length
        );
        print_hex(digest, sizeof(digest));
        putchar('\t');
        print_nullable_hex(name);
        putchar('\t');
        print_nullable_hex(media_type);
        putchar('\n');
        free(name);
        free(media_type);
    }

    for (uint32_t position = 0u; position < info.reading_order_count; position++) {
        uint32_t resource_index = 0u;
        if (ermao_mobi_reading_order_resource_index(book, position, &resource_index)
            != ERMAO_MOBI_OK) {
            return 1;
        }
        printf("reading\t%u\t%u\n", position, resource_index);
    }
    for (uint32_t index = 0u; index < info.toc_count; index++) {
        ErmaoMobiTocInfo toc = {.struct_size = sizeof(toc)};
        if (ermao_mobi_get_toc_info(book, index, &toc) != ERMAO_MOBI_OK) {
            return 1;
        }
        char *title = copy_indexed_string(ermao_mobi_copy_toc_title, book, index);
        char *fragment = copy_indexed_string(ermao_mobi_copy_toc_fragment, book, index);
        printf("toc\t%u\t%u\t%u\t", index, toc.parent_index, toc.target_resource_index);
        print_nullable_hex(title);
        putchar('\t');
        print_nullable_hex(fragment);
        putchar('\n');
        free(title);
        free(fragment);
    }
    for (uint32_t index = 0u; index < info.warning_count; index++) {
        ErmaoMobiWarningInfo warning = {.struct_size = sizeof(warning)};
        if (ermao_mobi_get_warning_info(book, index, &warning) != ERMAO_MOBI_OK) {
            return 1;
        }
        printf("warning\t%u\t%u\t%u\n", index, warning.code, warning.related_index);
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s <publication>\n", argv[0]);
        return 2;
    }
    ErmaoMobiBook *book = NULL;
    const ErmaoMobiStatus status = ermao_mobi_open(argv[1], NULL, &book);
    if (status != ERMAO_MOBI_OK) {
        fprintf(stderr, "open failed: %s\n", ermao_mobi_status_name(status));
        return 1;
    }
    const int result = snapshot(book);
    ermao_mobi_close(&book);
    return result;
}
