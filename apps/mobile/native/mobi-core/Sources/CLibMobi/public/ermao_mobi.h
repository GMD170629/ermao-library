#ifndef ERMAO_MOBI_H
#define ERMAO_MOBI_H

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#define ERMAO_MOBI_EXPORT __declspec(dllexport)
#else
#define ERMAO_MOBI_EXPORT __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define ERMAO_MOBI_ABI_VERSION 1u
#define ERMAO_MOBI_MAX_FILE_BYTES (UINT64_C(512) * UINT64_C(1024) * UINT64_C(1024))
#define ERMAO_MOBI_MAX_READ_BYTES (UINT32_C(256) * UINT32_C(1024))
#define ERMAO_MOBI_INDEX_NONE UINT32_MAX

typedef struct ErmaoMobiBook ErmaoMobiBook;

typedef enum ErmaoMobiStatus {
    ERMAO_MOBI_OK = 0,
    ERMAO_MOBI_INVALID_ARGUMENT = 1,
    ERMAO_MOBI_FILE_NOT_FOUND = 2,
    ERMAO_MOBI_IO_ERROR = 3,
    ERMAO_MOBI_UNSUPPORTED = 4,
    ERMAO_MOBI_DRM_PROTECTED = 5,
    ERMAO_MOBI_CORRUPT = 6,
    ERMAO_MOBI_PARSE_FAILED = 7,
    ERMAO_MOBI_NO_CONTENT = 8,
    ERMAO_MOBI_LIMIT_EXCEEDED = 9,
    ERMAO_MOBI_OUT_OF_MEMORY = 10,
    ERMAO_MOBI_NOT_FOUND = 11,
    ERMAO_MOBI_OUT_OF_RANGE = 12,
    ERMAO_MOBI_BUFFER_TOO_SMALL = 13,
    ERMAO_MOBI_INTERNAL = 14
} ErmaoMobiStatus;

typedef enum ErmaoMobiFormat {
    ERMAO_MOBI_FORMAT_MOBI6 = 1,
    ERMAO_MOBI_FORMAT_KF8 = 2,
    ERMAO_MOBI_FORMAT_HYBRID_KF8 = 3,
    ERMAO_MOBI_FORMAT_HYBRID_MOBI6_FALLBACK = 4
} ErmaoMobiFormat;

typedef enum ErmaoMobiReadingDirection {
    ERMAO_MOBI_DIRECTION_UNKNOWN = 0,
    ERMAO_MOBI_DIRECTION_LTR = 1,
    ERMAO_MOBI_DIRECTION_RTL = 2
} ErmaoMobiReadingDirection;

typedef enum ErmaoMobiMetadataField {
    ERMAO_MOBI_METADATA_TITLE = 1,
    ERMAO_MOBI_METADATA_AUTHOR = 2,
    ERMAO_MOBI_METADATA_PUBLISHER = 3,
    ERMAO_MOBI_METADATA_LANGUAGE = 4,
    ERMAO_MOBI_METADATA_ASIN = 5,
    ERMAO_MOBI_METADATA_ISBN = 6,
    ERMAO_MOBI_METADATA_DESCRIPTION = 7
} ErmaoMobiMetadataField;

typedef enum ErmaoMobiResourceCategory {
    ERMAO_MOBI_RESOURCE_MARKUP = 1,
    ERMAO_MOBI_RESOURCE_FLOW = 2,
    ERMAO_MOBI_RESOURCE_ASSET = 3
} ErmaoMobiResourceCategory;

typedef enum ErmaoMobiWarningCode {
    ERMAO_MOBI_WARNING_HYBRID_MOBI6_FALLBACK = 1,
    ERMAO_MOBI_WARNING_MISSING_TOC = 2,
    ERMAO_MOBI_WARNING_UNRESOLVED_TOC_TARGET = 3
} ErmaoMobiWarningCode;

typedef struct ErmaoMobiOpenOptions {
    uint32_t struct_size;
    uint32_t max_read_bytes;
    uint64_t max_file_bytes;
} ErmaoMobiOpenOptions;

typedef struct ErmaoMobiBookInfo {
    uint32_t struct_size;
    uint32_t format;
    uint32_t reading_direction;
    uint32_t resource_count;
    uint32_t reading_order_count;
    uint32_t toc_count;
    uint32_t warning_count;
    uint32_t cover_resource_index;
} ErmaoMobiBookInfo;

typedef struct ErmaoMobiResourceInfo {
    uint32_t struct_size;
    uint32_t category;
    uint64_t source_uid;
    uint64_t decoded_length;
} ErmaoMobiResourceInfo;

typedef struct ErmaoMobiTocInfo {
    uint32_t struct_size;
    uint32_t parent_index;
    uint32_t target_resource_index;
} ErmaoMobiTocInfo;

typedef struct ErmaoMobiWarningInfo {
    uint32_t struct_size;
    uint32_t code;
    uint32_t related_index;
} ErmaoMobiWarningInfo;

ERMAO_MOBI_EXPORT uint32_t ermao_mobi_abi_version(void);
ERMAO_MOBI_EXPORT const char *ermao_mobi_parser_identifier(void);
ERMAO_MOBI_EXPORT const char *ermao_mobi_normalization_identifier(void);
ERMAO_MOBI_EXPORT const char *ermao_mobi_status_name(ErmaoMobiStatus status);

ERMAO_MOBI_EXPORT void ermao_mobi_default_options(ErmaoMobiOpenOptions *options);
ERMAO_MOBI_EXPORT ErmaoMobiStatus ermao_mobi_open(
    const char *path,
    const ErmaoMobiOpenOptions *options,
    ErmaoMobiBook **out_book
);
ERMAO_MOBI_EXPORT void ermao_mobi_close(ErmaoMobiBook **book);

ERMAO_MOBI_EXPORT ErmaoMobiStatus ermao_mobi_get_book_info(
    const ErmaoMobiBook *book,
    ErmaoMobiBookInfo *out_info
);
ERMAO_MOBI_EXPORT ErmaoMobiStatus ermao_mobi_copy_metadata(
    const ErmaoMobiBook *book,
    ErmaoMobiMetadataField field,
    char *buffer,
    uint32_t capacity,
    uint32_t *out_required
);

ERMAO_MOBI_EXPORT ErmaoMobiStatus ermao_mobi_resource_count(
    const ErmaoMobiBook *book,
    uint32_t *out_count
);
ERMAO_MOBI_EXPORT ErmaoMobiStatus ermao_mobi_get_resource_info(
    const ErmaoMobiBook *book,
    uint32_t resource_index,
    ErmaoMobiResourceInfo *out_info
);
ERMAO_MOBI_EXPORT ErmaoMobiStatus ermao_mobi_copy_resource_source_name(
    const ErmaoMobiBook *book,
    uint32_t resource_index,
    char *buffer,
    uint32_t capacity,
    uint32_t *out_required
);
ERMAO_MOBI_EXPORT ErmaoMobiStatus ermao_mobi_copy_resource_media_type(
    const ErmaoMobiBook *book,
    uint32_t resource_index,
    char *buffer,
    uint32_t capacity,
    uint32_t *out_required
);
ERMAO_MOBI_EXPORT ErmaoMobiStatus ermao_mobi_read_resource(
    const ErmaoMobiBook *book,
    uint32_t resource_index,
    uint64_t offset,
    uint8_t *buffer,
    uint32_t capacity,
    uint32_t *out_read
);

ERMAO_MOBI_EXPORT ErmaoMobiStatus ermao_mobi_reading_order_count(
    const ErmaoMobiBook *book,
    uint32_t *out_count
);
ERMAO_MOBI_EXPORT ErmaoMobiStatus ermao_mobi_reading_order_resource_index(
    const ErmaoMobiBook *book,
    uint32_t position,
    uint32_t *out_resource_index
);

ERMAO_MOBI_EXPORT ErmaoMobiStatus ermao_mobi_toc_count(
    const ErmaoMobiBook *book,
    uint32_t *out_count
);
ERMAO_MOBI_EXPORT ErmaoMobiStatus ermao_mobi_get_toc_info(
    const ErmaoMobiBook *book,
    uint32_t toc_index,
    ErmaoMobiTocInfo *out_info
);
ERMAO_MOBI_EXPORT ErmaoMobiStatus ermao_mobi_copy_toc_title(
    const ErmaoMobiBook *book,
    uint32_t toc_index,
    char *buffer,
    uint32_t capacity,
    uint32_t *out_required
);
ERMAO_MOBI_EXPORT ErmaoMobiStatus ermao_mobi_copy_toc_fragment(
    const ErmaoMobiBook *book,
    uint32_t toc_index,
    char *buffer,
    uint32_t capacity,
    uint32_t *out_required
);

ERMAO_MOBI_EXPORT ErmaoMobiStatus ermao_mobi_warning_count(
    const ErmaoMobiBook *book,
    uint32_t *out_count
);
ERMAO_MOBI_EXPORT ErmaoMobiStatus ermao_mobi_get_warning_info(
    const ErmaoMobiBook *book,
    uint32_t warning_index,
    ErmaoMobiWarningInfo *out_info
);

#ifdef __cplusplus
}
#endif

#endif
