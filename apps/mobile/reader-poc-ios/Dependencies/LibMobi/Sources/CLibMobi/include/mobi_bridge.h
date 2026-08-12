#ifndef shuku_mobi_bridge_h
#define shuku_mobi_bridge_h

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    SHUKU_MOBI_FORMAT_MOBI6 = 0,
    SHUKU_MOBI_FORMAT_KF8 = 1,
    SHUKU_MOBI_FORMAT_HYBRID = 2
} ShukuMobiFormat;

typedef enum {
    SHUKU_MOBI_PART_MARKUP = 0,
    SHUKU_MOBI_PART_FLOW = 1,
    SHUKU_MOBI_PART_RESOURCE = 2
} ShukuMobiPartCategory;

typedef struct {
    uint64_t uid;
    ShukuMobiPartCategory category;
    int32_t mobi_file_type;
    char * _Nullable name;
    char * _Nullable media_type;
    uint8_t * _Nullable bytes;
    size_t length;
} ShukuMobiPart;

typedef struct {
    ShukuMobiFormat format;
    char * _Nullable title;
    char * _Nullable author;
    char * _Nullable language;
    char * _Nullable description_text;
    ShukuMobiPart * _Nullable parts;
    size_t part_count;
    bool has_opf;
    bool has_ncx;
} ShukuMobiBook;

typedef enum {
    SHUKU_MOBI_BRIDGE_SUCCESS = 0,
    SHUKU_MOBI_BRIDGE_INVALID_ARGUMENT = 1,
    SHUKU_MOBI_BRIDGE_OUT_OF_MEMORY = 2,
    SHUKU_MOBI_BRIDGE_ENCRYPTED = 3,
    SHUKU_MOBI_BRIDGE_UNSUPPORTED = 4,
    SHUKU_MOBI_BRIDGE_CORRUPT = 5,
    SHUKU_MOBI_BRIDGE_NO_MARKUP = 6,
    SHUKU_MOBI_BRIDGE_LIBMOBI_ERROR = 7
} ShukuMobiBridgeResult;

ShukuMobiBridgeResult shuku_mobi_extract_path(
    const char * _Nonnull path,
    ShukuMobiBook * _Nullable * _Nonnull book,
    char * _Nullable * _Nonnull error_message
);

void shuku_mobi_free_book(ShukuMobiBook * _Nullable book);
void shuku_mobi_free_error(char * _Nullable error_message);
const char * _Nonnull shuku_mobi_version(void);

#ifdef __cplusplus
}
#endif

#endif
