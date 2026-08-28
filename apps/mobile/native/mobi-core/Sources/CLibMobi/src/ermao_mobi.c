#include "ermao_mobi.h"

#include "mobi.h"
#include "util.h"

#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

typedef struct ErmaoMobiResource {
    const MOBIPart *part;
    uint32_t category;
    char *source_name;
    char *media_type;
} ErmaoMobiResource;

typedef struct ErmaoMobiTocEntry {
    uint32_t parent_index;
    uint32_t target_resource_index;
    char *title;
    char *fragment;
} ErmaoMobiTocEntry;

struct ErmaoMobiBook {
    MOBIData *mobi;
    MOBIRawml *rawml;
    uint32_t format;
    uint32_t reading_direction;
    uint32_t max_read_bytes;
    uint32_t cover_resource_index;
    char *metadata[7];
    ErmaoMobiResource *resources;
    uint32_t resource_count;
    uint32_t *reading_order;
    uint32_t reading_order_count;
    ErmaoMobiTocEntry *toc;
    uint32_t toc_count;
    ErmaoMobiWarningInfo *warnings;
    uint32_t warning_count;
};

static char *ermao_copy_string(const char *value) {
    if (value == NULL) {
        return NULL;
    }
    const size_t length = strlen(value);
    char *copy = malloc(length + 1u);
    if (copy != NULL) {
        memcpy(copy, value, length + 1u);
    }
    return copy;
}

static ErmaoMobiStatus ermao_status_from_libmobi(MOBI_RET result, bool parsing) {
    switch (result) {
        case MOBI_SUCCESS:
            return ERMAO_MOBI_OK;
        case MOBI_PARAM_ERR:
            return ERMAO_MOBI_INVALID_ARGUMENT;
        case MOBI_FILE_NOT_FOUND:
            return ERMAO_MOBI_FILE_NOT_FOUND;
        case MOBI_FILE_ENCRYPTED:
        case MOBI_DRM_PIDINV:
        case MOBI_DRM_KEYNOTFOUND:
        case MOBI_DRM_UNSUPPORTED:
        case MOBI_DRM_EXPIRED:
        case MOBI_DRM_RANDOM_ERR:
            return ERMAO_MOBI_DRM_PROTECTED;
        case MOBI_FILE_UNSUPPORTED:
            return ERMAO_MOBI_UNSUPPORTED;
        case MOBI_DATA_CORRUPT:
        case MOBI_BUFFER_END:
            return ERMAO_MOBI_CORRUPT;
        case MOBI_MALLOC_FAILED:
        case MOBI_INIT_FAILED:
            return ERMAO_MOBI_OUT_OF_MEMORY;
        case MOBI_WRITE_FAILED:
            return ERMAO_MOBI_IO_ERROR;
        case MOBI_XML_ERR:
        case MOBI_ERROR:
        default:
            return parsing ? ERMAO_MOBI_PARSE_FAILED : ERMAO_MOBI_INTERNAL;
    }
}

static bool ermao_header_is_encrypted(const MOBIData *mobi) {
    return mobi != NULL && mobi->rh != NULL
        && (mobi->rh->encryption_type == MOBI_ENCRYPTION_V1
            || mobi->rh->encryption_type == MOBI_ENCRYPTION_V2);
}

static ErmaoMobiStatus ermao_copy_out(
    const char *value,
    char *buffer,
    uint32_t capacity,
    uint32_t *out_required
) {
    if (out_required == NULL) {
        return ERMAO_MOBI_INVALID_ARGUMENT;
    }
    *out_required = 0u;
    if (value == NULL || value[0] == '\0') {
        return ERMAO_MOBI_NOT_FOUND;
    }
    const size_t required = strlen(value) + 1u;
    if (required > UINT32_MAX) {
        return ERMAO_MOBI_LIMIT_EXCEEDED;
    }
    *out_required = (uint32_t) required;
    if (buffer == NULL || capacity < required) {
        return ERMAO_MOBI_BUFFER_TOO_SMALL;
    }
    memcpy(buffer, value, required);
    return ERMAO_MOBI_OK;
}

static bool ermao_bytes_contain(
    const unsigned char *bytes,
    size_t length,
    const char *needle
) {
    if (bytes == NULL || needle == NULL) {
        return false;
    }
    const size_t needle_length = strlen(needle);
    if (needle_length == 0u || needle_length > length) {
        return false;
    }
    for (size_t index = 0u; index <= length - needle_length; index++) {
        if (memcmp(bytes + index, needle, needle_length) == 0) {
            return true;
        }
    }
    return false;
}

static uint32_t ermao_part_count(const MOBIRawml *rawml) {
    size_t count = 0u;
    for (const MOBIPart *part = rawml->markup; part != NULL; part = part->next) {
        count++;
    }
    const MOBIPart *flow = rawml->flow;
    if (flow != NULL) {
        flow = flow->next;
    }
    for (const MOBIPart *part = flow; part != NULL; part = part->next) {
        count++;
    }
    for (const MOBIPart *part = rawml->resources; part != NULL; part = part->next) {
        if (part->size > 0u) {
            count++;
        }
    }
    return count <= UINT32_MAX ? (uint32_t) count : UINT32_MAX;
}

static char *ermao_source_name(const MOBIPart *part, uint32_t category) {
    const MOBIFileMeta metadata = mobi_get_filemeta_by_type(part->type);
    const char *prefix = category == ERMAO_MOBI_RESOURCE_MARKUP
        ? "part"
        : (category == ERMAO_MOBI_RESOURCE_FLOW ? "flow" : "resource");
    char name[80];
    const int written = snprintf(
        name,
        sizeof(name),
        "%s%05zu.%s",
        prefix,
        part->uid,
        metadata.extension[0] == '\0' ? "bin" : metadata.extension
    );
    if (written <= 0 || (size_t) written >= sizeof(name)) {
        return NULL;
    }
    return ermao_copy_string(name);
}

static bool ermao_add_resource(
    ErmaoMobiBook *book,
    uint32_t index,
    const MOBIPart *part,
    uint32_t category
) {
    const MOBIFileMeta metadata = mobi_get_filemeta_by_type(part->type);
    book->resources[index].part = part;
    book->resources[index].category = category;
    book->resources[index].source_name = ermao_source_name(part, category);
    book->resources[index].media_type = ermao_copy_string(
        metadata.mime_type[0] == '\0' ? "application/octet-stream" : metadata.mime_type
    );
    return book->resources[index].source_name != NULL
        && book->resources[index].media_type != NULL;
}

static ErmaoMobiStatus ermao_build_resources(ErmaoMobiBook *book) {
    const uint32_t count = ermao_part_count(book->rawml);
    if (count == UINT32_MAX) {
        return ERMAO_MOBI_LIMIT_EXCEEDED;
    }
    if (count == 0u || book->rawml->markup == NULL) {
        return ERMAO_MOBI_NO_CONTENT;
    }
    book->resources = calloc(count, sizeof(*book->resources));
    if (book->resources == NULL) {
        return ERMAO_MOBI_OUT_OF_MEMORY;
    }
    book->resource_count = count;

    uint32_t index = 0u;
    for (const MOBIPart *part = book->rawml->markup; part != NULL; part = part->next) {
        if (!ermao_add_resource(book, index++, part, ERMAO_MOBI_RESOURCE_MARKUP)) {
            return ERMAO_MOBI_OUT_OF_MEMORY;
        }
    }
    const MOBIPart *flow = book->rawml->flow;
    if (flow != NULL) {
        flow = flow->next;
    }
    for (const MOBIPart *part = flow; part != NULL; part = part->next) {
        if (!ermao_add_resource(book, index++, part, ERMAO_MOBI_RESOURCE_FLOW)) {
            return ERMAO_MOBI_OUT_OF_MEMORY;
        }
    }
    for (const MOBIPart *part = book->rawml->resources; part != NULL; part = part->next) {
        if (part->size > 0u
            && !ermao_add_resource(book, index++, part, ERMAO_MOBI_RESOURCE_ASSET)) {
            return ERMAO_MOBI_OUT_OF_MEMORY;
        }
    }

    book->reading_order_count = 0u;
    for (index = 0u; index < count; index++) {
        if (book->resources[index].category == ERMAO_MOBI_RESOURCE_MARKUP) {
            book->reading_order_count++;
        }
    }
    if (book->reading_order_count == 0u) {
        return ERMAO_MOBI_NO_CONTENT;
    }
    book->reading_order = calloc(book->reading_order_count, sizeof(*book->reading_order));
    if (book->reading_order == NULL) {
        return ERMAO_MOBI_OUT_OF_MEMORY;
    }
    uint32_t reading_position = 0u;
    for (index = 0u; index < count; index++) {
        if (book->resources[index].category == ERMAO_MOBI_RESOURCE_MARKUP) {
            book->reading_order[reading_position++] = index;
        }
    }
    return ERMAO_MOBI_OK;
}

static ErmaoMobiStatus ermao_add_warning(
    ErmaoMobiBook *book,
    uint32_t code,
    uint32_t related_index
) {
    if (book->warning_count == UINT32_MAX) {
        return ERMAO_MOBI_LIMIT_EXCEEDED;
    }
    ErmaoMobiWarningInfo *warnings = realloc(
        book->warnings,
        ((size_t) book->warning_count + 1u) * sizeof(*warnings)
    );
    if (warnings == NULL) {
        return ERMAO_MOBI_OUT_OF_MEMORY;
    }
    book->warnings = warnings;
    ErmaoMobiWarningInfo *warning = &book->warnings[book->warning_count++];
    warning->struct_size = (uint32_t) sizeof(*warning);
    warning->code = code;
    warning->related_index = related_index;
    return ERMAO_MOBI_OK;
}

static uint32_t ermao_find_resource(const ErmaoMobiBook *book, const char *source_name) {
    if (source_name == NULL) {
        return ERMAO_MOBI_INDEX_NONE;
    }
    while (source_name[0] == '.' && source_name[1] == '/') {
        source_name += 2;
    }
    const char *slash = strrchr(source_name, '/');
    if (slash != NULL) {
        source_name = slash + 1;
    }
    for (uint32_t index = 0u; index < book->resource_count; index++) {
        if (strcmp(book->resources[index].source_name, source_name) == 0) {
            return index;
        }
    }
    return ERMAO_MOBI_INDEX_NONE;
}

static char *ermao_xml_decode(const unsigned char *bytes, size_t length) {
    char *result = malloc(length + 1u);
    if (result == NULL) {
        return NULL;
    }
    size_t input = 0u;
    size_t output = 0u;
    while (input < length) {
        if (bytes[input] == '&') {
            const struct {
                const char *entity;
                char replacement;
            } entities[] = {
                {"&amp;", '&'}, {"&lt;", '<'}, {"&gt;", '>'},
                {"&quot;", '"'}, {"&apos;", '\''},
            };
            bool matched = false;
            for (size_t index = 0u; index < sizeof(entities) / sizeof(entities[0]); index++) {
                const size_t entity_length = strlen(entities[index].entity);
                if (input + entity_length <= length
                    && memcmp(bytes + input, entities[index].entity, entity_length) == 0) {
                    result[output++] = entities[index].replacement;
                    input += entity_length;
                    matched = true;
                    break;
                }
            }
            if (matched) {
                continue;
            }
        }
        result[output++] = (char) bytes[input++];
    }
    result[output] = '\0';
    return result;
}

static bool ermao_xml_tag_name(
    const unsigned char *start,
    const unsigned char *end,
    const char *name,
    bool *closing
) {
    const unsigned char *cursor = start + 1;
    while (cursor < end && (*cursor == ' ' || *cursor == '\t' || *cursor == '\r' || *cursor == '\n')) {
        cursor++;
    }
    *closing = cursor < end && *cursor == '/';
    if (*closing) {
        cursor++;
    }
    const unsigned char *name_start = cursor;
    while (cursor < end && *cursor != ' ' && *cursor != '\t' && *cursor != '\r'
           && *cursor != '\n' && *cursor != '>' && *cursor != '/') {
        cursor++;
    }
    const unsigned char *local = name_start;
    for (const unsigned char *scan = name_start; scan < cursor; scan++) {
        if (*scan == ':') {
            local = scan + 1;
        }
    }
    const size_t actual_length = (size_t) (cursor - local);
    return actual_length == strlen(name) && memcmp(local, name, actual_length) == 0;
}

static const unsigned char *ermao_xml_tag_end(
    const unsigned char *start,
    const unsigned char *end
) {
    unsigned char quote = 0u;
    for (const unsigned char *cursor = start; cursor < end; cursor++) {
        if (quote == 0u && (*cursor == '\'' || *cursor == '"')) {
            quote = *cursor;
        } else if (quote != 0u && *cursor == quote) {
            quote = 0u;
        } else if (quote == 0u && *cursor == '>') {
            return cursor;
        }
    }
    return NULL;
}

static char *ermao_xml_attribute(
    const unsigned char *tag_start,
    const unsigned char *tag_end,
    const char *attribute
) {
    const size_t attribute_length = strlen(attribute);
    const unsigned char *cursor = tag_start + 1;
    while (cursor + attribute_length < tag_end) {
        if (memcmp(cursor, attribute, attribute_length) == 0) {
            const unsigned char *equals = cursor + attribute_length;
            while (equals < tag_end && (*equals == ' ' || *equals == '\t')) {
                equals++;
            }
            if (equals >= tag_end || *equals != '=') {
                cursor++;
                continue;
            }
            equals++;
            while (equals < tag_end && (*equals == ' ' || *equals == '\t')) {
                equals++;
            }
            if (equals >= tag_end || (*equals != '\'' && *equals != '"')) {
                cursor++;
                continue;
            }
            const unsigned char quote = *equals++;
            const unsigned char *value_start = equals;
            while (equals < tag_end && *equals != quote) {
                equals++;
            }
            if (equals < tag_end) {
                return ermao_xml_decode(value_start, (size_t) (equals - value_start));
            }
        }
        cursor++;
    }
    return NULL;
}

static ErmaoMobiStatus ermao_append_toc(
    ErmaoMobiBook *book,
    uint32_t parent_index,
    uint32_t *out_index
) {
    if (book->toc_count == UINT32_MAX) {
        return ERMAO_MOBI_LIMIT_EXCEEDED;
    }
    ErmaoMobiTocEntry *toc = realloc(
        book->toc,
        ((size_t) book->toc_count + 1u) * sizeof(*toc)
    );
    if (toc == NULL) {
        return ERMAO_MOBI_OUT_OF_MEMORY;
    }
    book->toc = toc;
    const uint32_t index = book->toc_count++;
    memset(&book->toc[index], 0, sizeof(book->toc[index]));
    book->toc[index].parent_index = parent_index;
    book->toc[index].target_resource_index = ERMAO_MOBI_INDEX_NONE;
    *out_index = index;
    return ERMAO_MOBI_OK;
}

static ErmaoMobiStatus ermao_parse_ncx(ErmaoMobiBook *book, const MOBIPart *ncx) {
    const unsigned char *cursor = ncx->data;
    const unsigned char *end = ncx->data + ncx->size;
    uint32_t *stack = NULL;
    size_t depth = 0u;
    ErmaoMobiStatus status = ERMAO_MOBI_OK;

    while (cursor < end) {
        while (cursor < end && *cursor != '<') {
            cursor++;
        }
        if (cursor >= end) {
            break;
        }
        const unsigned char *tag_end = ermao_xml_tag_end(cursor, end);
        if (tag_end == NULL) {
            status = ERMAO_MOBI_CORRUPT;
            break;
        }
        bool closing = false;
        if (ermao_xml_tag_name(cursor, tag_end, "navPoint", &closing)) {
            if (closing) {
                if (depth > 0u) {
                    depth--;
                }
            } else {
                const uint32_t parent = depth == 0u ? ERMAO_MOBI_INDEX_NONE : stack[depth - 1u];
                uint32_t toc_index = ERMAO_MOBI_INDEX_NONE;
                status = ermao_append_toc(book, parent, &toc_index);
                if (status != ERMAO_MOBI_OK) {
                    break;
                }
                uint32_t *new_stack = realloc(stack, (depth + 1u) * sizeof(*new_stack));
                if (new_stack == NULL) {
                    status = ERMAO_MOBI_OUT_OF_MEMORY;
                    break;
                }
                stack = new_stack;
                stack[depth++] = toc_index;
            }
        } else if (depth > 0u && ermao_xml_tag_name(cursor, tag_end, "text", &closing) && !closing) {
            const unsigned char *text_start = tag_end + 1;
            const unsigned char *text_end = text_start;
            while (text_end < end && *text_end != '<') {
                text_end++;
            }
            char *title = ermao_xml_decode(text_start, (size_t) (text_end - text_start));
            if (title == NULL) {
                status = ERMAO_MOBI_OUT_OF_MEMORY;
                break;
            }
            const uint32_t toc_index = stack[depth - 1u];
            free(book->toc[toc_index].title);
            book->toc[toc_index].title = title;
        } else if (depth > 0u && ermao_xml_tag_name(cursor, tag_end, "content", &closing) && !closing) {
            char *source = ermao_xml_attribute(cursor, tag_end, "src");
            if (source != NULL) {
                char *fragment = strchr(source, '#');
                if (fragment != NULL) {
                    *fragment++ = '\0';
                }
                const uint32_t toc_index = stack[depth - 1u];
                book->toc[toc_index].target_resource_index = ermao_find_resource(book, source);
                if (fragment != NULL && fragment[0] != '\0') {
                    book->toc[toc_index].fragment = ermao_copy_string(fragment);
                    if (book->toc[toc_index].fragment == NULL) {
                        free(source);
                        status = ERMAO_MOBI_OUT_OF_MEMORY;
                        break;
                    }
                }
                free(source);
            }
        }
        cursor = tag_end + 1;
    }
    free(stack);
    return status;
}

static ErmaoMobiStatus ermao_build_toc(ErmaoMobiBook *book) {
    const MOBIPart *ncx = NULL;
    for (const MOBIPart *part = book->rawml->resources; part != NULL; part = part->next) {
        if (part->type == T_NCX) {
            ncx = part;
            break;
        }
    }
    if (ncx == NULL || ncx->size == 0u) {
        return ermao_add_warning(book, ERMAO_MOBI_WARNING_MISSING_TOC, ERMAO_MOBI_INDEX_NONE);
    }
    ErmaoMobiStatus status = ermao_parse_ncx(book, ncx);
    if (status != ERMAO_MOBI_OK) {
        return status;
    }
    if (book->toc_count == 0u) {
        return ermao_add_warning(book, ERMAO_MOBI_WARNING_MISSING_TOC, ERMAO_MOBI_INDEX_NONE);
    }
    for (uint32_t index = 0u; index < book->toc_count; index++) {
        if (book->toc[index].target_resource_index == ERMAO_MOBI_INDEX_NONE) {
            status = ermao_add_warning(book, ERMAO_MOBI_WARNING_UNRESOLVED_TOC_TARGET, index);
            if (status != ERMAO_MOBI_OK) {
                return status;
            }
        }
    }
    return ERMAO_MOBI_OK;
}

static uint32_t ermao_reading_direction(const ErmaoMobiBook *book) {
    for (uint32_t index = 0u; index < book->resource_count; index++) {
        const MOBIPart *part = book->resources[index].part;
        if (part->type == T_OPF
            && (ermao_bytes_contain(part->data, part->size, "page-progression-direction=\"rtl\"")
                || ermao_bytes_contain(part->data, part->size, "page-progression-direction='rtl'"))) {
            return ERMAO_MOBI_DIRECTION_RTL;
        }
        if ((part->type == T_CSS || part->type == T_HTML)
            && (ermao_bytes_contain(part->data, part->size, "vertical-rl")
                || ermao_bytes_contain(part->data, part->size, "direction:rtl")
                || ermao_bytes_contain(part->data, part->size, "direction: rtl"))) {
            return ERMAO_MOBI_DIRECTION_RTL;
        }
    }
    return ERMAO_MOBI_DIRECTION_LTR;
}

static void ermao_find_cover(ErmaoMobiBook *book) {
    book->cover_resource_index = ERMAO_MOBI_INDEX_NONE;
    MOBIExthHeader *cover = mobi_get_exthrecord_by_tag(book->mobi, EXTH_COVEROFFSET);
    if (cover == NULL || cover->data == NULL) {
        return;
    }
    const uint32_t cover_uid = mobi_decode_exthvalue(cover->data, cover->size);
    for (uint32_t index = 0u; index < book->resource_count; index++) {
        if (book->resources[index].category == ERMAO_MOBI_RESOURCE_ASSET
            && book->resources[index].part->uid == cover_uid) {
            book->cover_resource_index = index;
            return;
        }
    }
}

static void ermao_free_book(ErmaoMobiBook *book) {
    if (book == NULL) {
        return;
    }
    for (size_t index = 0u; index < sizeof(book->metadata) / sizeof(book->metadata[0]); index++) {
        free(book->metadata[index]);
    }
    for (uint32_t index = 0u; index < book->resource_count; index++) {
        free(book->resources[index].source_name);
        free(book->resources[index].media_type);
    }
    for (uint32_t index = 0u; index < book->toc_count; index++) {
        free(book->toc[index].title);
        free(book->toc[index].fragment);
    }
    free(book->warnings);
    free(book->toc);
    free(book->reading_order);
    free(book->resources);
    if (book->rawml != NULL) {
        mobi_free_rawml(book->rawml);
    }
    if (book->mobi != NULL) {
        mobi_free(book->mobi);
    }
    free(book);
}

uint32_t ermao_mobi_abi_version(void) {
    return ERMAO_MOBI_ABI_VERSION;
}

const char *ermao_mobi_parser_identifier(void) {
    return "libmobi:0.12@85dcfe803fc2a21020ddcf15c3eb66b93d388add";
}

const char *ermao_mobi_normalization_identifier(void) {
    return "ermao-mobi-core-v1";
}

const char *ermao_mobi_status_name(ErmaoMobiStatus status) {
    static const char *names[] = {
        "ok", "invalid_argument", "file_not_found", "io", "unsupported",
        "drm_protected", "corrupt", "parse_failed", "no_content",
        "limit_exceeded", "out_of_memory", "not_found", "out_of_range",
        "buffer_too_small", "internal",
    };
    return status >= ERMAO_MOBI_OK && status <= ERMAO_MOBI_INTERNAL
        ? names[(uint32_t) status]
        : "internal";
}

void ermao_mobi_default_options(ErmaoMobiOpenOptions *options) {
    if (options == NULL) {
        return;
    }
    options->struct_size = (uint32_t) sizeof(*options);
    options->max_read_bytes = ERMAO_MOBI_MAX_READ_BYTES;
    options->max_file_bytes = ERMAO_MOBI_MAX_FILE_BYTES;
}

ErmaoMobiStatus ermao_mobi_open(
    const char *path,
    const ErmaoMobiOpenOptions *options,
    ErmaoMobiBook **out_book
) {
    if (path == NULL || path[0] == '\0' || out_book == NULL) {
        return ERMAO_MOBI_INVALID_ARGUMENT;
    }
    *out_book = NULL;
    ErmaoMobiOpenOptions effective;
    ermao_mobi_default_options(&effective);
    if (options != NULL) {
        if (options->struct_size < sizeof(*options)
            || options->max_file_bytes == 0u
            || options->max_read_bytes == 0u
            || options->max_read_bytes > ERMAO_MOBI_MAX_READ_BYTES) {
            return ERMAO_MOBI_INVALID_ARGUMENT;
        }
        effective = *options;
    }

    struct stat file_stat;
    errno = 0;
    if (stat(path, &file_stat) != 0) {
        return errno == ENOENT ? ERMAO_MOBI_FILE_NOT_FOUND : ERMAO_MOBI_IO_ERROR;
    }
    if (!S_ISREG(file_stat.st_mode)) {
        return ERMAO_MOBI_UNSUPPORTED;
    }
    if (file_stat.st_size < 0 || (uint64_t) file_stat.st_size > effective.max_file_bytes) {
        return ERMAO_MOBI_LIMIT_EXCEEDED;
    }

    ErmaoMobiBook *book = calloc(1u, sizeof(*book));
    if (book == NULL) {
        return ERMAO_MOBI_OUT_OF_MEMORY;
    }
    book->max_read_bytes = effective.max_read_bytes;
    book->cover_resource_index = ERMAO_MOBI_INDEX_NONE;
    book->mobi = mobi_init();
    if (book->mobi == NULL) {
        ermao_free_book(book);
        return ERMAO_MOBI_OUT_OF_MEMORY;
    }
    MOBI_RET result = mobi_load_filename(book->mobi, path);
    if (result != MOBI_SUCCESS) {
        const ErmaoMobiStatus status = ermao_status_from_libmobi(result, false);
        ermao_free_book(book);
        return status;
    }
    if (mobi_is_encrypted(book->mobi) || ermao_header_is_encrypted(book->mobi)) {
        ermao_free_book(book);
        return ERMAO_MOBI_DRM_PROTECTED;
    }
    const bool hybrid = mobi_is_hybrid(book->mobi);
    book->rawml = mobi_init_rawml(book->mobi);
    if (book->rawml == NULL) {
        ermao_free_book(book);
        return ERMAO_MOBI_OUT_OF_MEMORY;
    }
    result = mobi_parse_rawml(book->rawml, book->mobi);
    bool used_fallback = false;
    if (result != MOBI_SUCCESS && hybrid && book->mobi->use_kf8) {
        mobi_free_rawml(book->rawml);
        book->rawml = NULL;
        if (mobi_swap_mobidata(book->mobi) == MOBI_SUCCESS
            && mobi_parse_kf7(book->mobi) == MOBI_SUCCESS) {
            book->rawml = mobi_init_rawml(book->mobi);
            if (book->rawml != NULL) {
                result = mobi_parse_rawml(book->rawml, book->mobi);
                used_fallback = result == MOBI_SUCCESS;
            } else {
                result = MOBI_MALLOC_FAILED;
            }
        }
    }
    if (result != MOBI_SUCCESS) {
        const ErmaoMobiStatus status = ermao_status_from_libmobi(result, true);
        ermao_free_book(book);
        return status;
    }

    if (hybrid) {
        book->format = used_fallback || !mobi_is_rawml_kf8(book->rawml)
            ? ERMAO_MOBI_FORMAT_HYBRID_MOBI6_FALLBACK
            : ERMAO_MOBI_FORMAT_HYBRID_KF8;
    } else {
        book->format = mobi_is_rawml_kf8(book->rawml)
            ? ERMAO_MOBI_FORMAT_KF8
            : ERMAO_MOBI_FORMAT_MOBI6;
    }

    book->metadata[ERMAO_MOBI_METADATA_TITLE - 1u] = mobi_meta_get_title(book->mobi);
    book->metadata[ERMAO_MOBI_METADATA_AUTHOR - 1u] = mobi_meta_get_author(book->mobi);
    book->metadata[ERMAO_MOBI_METADATA_PUBLISHER - 1u] = mobi_meta_get_publisher(book->mobi);
    book->metadata[ERMAO_MOBI_METADATA_LANGUAGE - 1u] = mobi_meta_get_language(book->mobi);
    book->metadata[ERMAO_MOBI_METADATA_ASIN - 1u] = mobi_meta_get_asin(book->mobi);
    book->metadata[ERMAO_MOBI_METADATA_ISBN - 1u] = mobi_meta_get_isbn(book->mobi);
    book->metadata[ERMAO_MOBI_METADATA_DESCRIPTION - 1u] = mobi_meta_get_description(book->mobi);

    ErmaoMobiStatus status = ermao_build_resources(book);
    if (status == ERMAO_MOBI_OK && book->format == ERMAO_MOBI_FORMAT_HYBRID_MOBI6_FALLBACK) {
        status = ermao_add_warning(
            book,
            ERMAO_MOBI_WARNING_HYBRID_MOBI6_FALLBACK,
            ERMAO_MOBI_INDEX_NONE
        );
    }
    if (status == ERMAO_MOBI_OK) {
        status = ermao_build_toc(book);
    }
    if (status != ERMAO_MOBI_OK) {
        ermao_free_book(book);
        return status;
    }
    book->reading_direction = ermao_reading_direction(book);
    ermao_find_cover(book);
    *out_book = book;
    return ERMAO_MOBI_OK;
}

void ermao_mobi_close(ErmaoMobiBook **book) {
    if (book == NULL || *book == NULL) {
        return;
    }
    ermao_free_book(*book);
    *book = NULL;
}

ErmaoMobiStatus ermao_mobi_get_book_info(
    const ErmaoMobiBook *book,
    ErmaoMobiBookInfo *out_info
) {
    if (book == NULL || out_info == NULL || out_info->struct_size < sizeof(*out_info)) {
        return ERMAO_MOBI_INVALID_ARGUMENT;
    }
    out_info->format = book->format;
    out_info->reading_direction = book->reading_direction;
    out_info->resource_count = book->resource_count;
    out_info->reading_order_count = book->reading_order_count;
    out_info->toc_count = book->toc_count;
    out_info->warning_count = book->warning_count;
    out_info->cover_resource_index = book->cover_resource_index;
    return ERMAO_MOBI_OK;
}

ErmaoMobiStatus ermao_mobi_copy_metadata(
    const ErmaoMobiBook *book,
    ErmaoMobiMetadataField field,
    char *buffer,
    uint32_t capacity,
    uint32_t *out_required
) {
    if (book == NULL || field < ERMAO_MOBI_METADATA_TITLE
        || field > ERMAO_MOBI_METADATA_DESCRIPTION) {
        return ERMAO_MOBI_INVALID_ARGUMENT;
    }
    return ermao_copy_out(book->metadata[(uint32_t) field - 1u], buffer, capacity, out_required);
}

ErmaoMobiStatus ermao_mobi_resource_count(const ErmaoMobiBook *book, uint32_t *out_count) {
    if (book == NULL || out_count == NULL) {
        return ERMAO_MOBI_INVALID_ARGUMENT;
    }
    *out_count = book->resource_count;
    return ERMAO_MOBI_OK;
}

ErmaoMobiStatus ermao_mobi_get_resource_info(
    const ErmaoMobiBook *book,
    uint32_t resource_index,
    ErmaoMobiResourceInfo *out_info
) {
    if (book == NULL || out_info == NULL || out_info->struct_size < sizeof(*out_info)) {
        return ERMAO_MOBI_INVALID_ARGUMENT;
    }
    if (resource_index >= book->resource_count) {
        return ERMAO_MOBI_OUT_OF_RANGE;
    }
    const ErmaoMobiResource *resource = &book->resources[resource_index];
    out_info->category = resource->category;
    out_info->source_uid = (uint64_t) resource->part->uid;
    out_info->decoded_length = (uint64_t) resource->part->size;
    return ERMAO_MOBI_OK;
}

ErmaoMobiStatus ermao_mobi_copy_resource_source_name(
    const ErmaoMobiBook *book,
    uint32_t resource_index,
    char *buffer,
    uint32_t capacity,
    uint32_t *out_required
) {
    if (book == NULL) {
        return ERMAO_MOBI_INVALID_ARGUMENT;
    }
    if (resource_index >= book->resource_count) {
        return ERMAO_MOBI_OUT_OF_RANGE;
    }
    return ermao_copy_out(book->resources[resource_index].source_name, buffer, capacity, out_required);
}

ErmaoMobiStatus ermao_mobi_copy_resource_media_type(
    const ErmaoMobiBook *book,
    uint32_t resource_index,
    char *buffer,
    uint32_t capacity,
    uint32_t *out_required
) {
    if (book == NULL) {
        return ERMAO_MOBI_INVALID_ARGUMENT;
    }
    if (resource_index >= book->resource_count) {
        return ERMAO_MOBI_OUT_OF_RANGE;
    }
    return ermao_copy_out(book->resources[resource_index].media_type, buffer, capacity, out_required);
}

ErmaoMobiStatus ermao_mobi_read_resource(
    const ErmaoMobiBook *book,
    uint32_t resource_index,
    uint64_t offset,
    uint8_t *buffer,
    uint32_t capacity,
    uint32_t *out_read
) {
    if (book == NULL || out_read == NULL) {
        return ERMAO_MOBI_INVALID_ARGUMENT;
    }
    *out_read = 0u;
    if (resource_index >= book->resource_count) {
        return ERMAO_MOBI_OUT_OF_RANGE;
    }
    if (capacity > book->max_read_bytes || capacity > ERMAO_MOBI_MAX_READ_BYTES) {
        return ERMAO_MOBI_LIMIT_EXCEEDED;
    }
    const MOBIPart *part = book->resources[resource_index].part;
    if (offset > part->size) {
        return ERMAO_MOBI_OUT_OF_RANGE;
    }
    if (offset == part->size || capacity == 0u) {
        return ERMAO_MOBI_OK;
    }
    if (buffer == NULL) {
        return ERMAO_MOBI_INVALID_ARGUMENT;
    }
    const uint64_t remaining = (uint64_t) part->size - offset;
    const uint32_t read_size = remaining < capacity ? (uint32_t) remaining : capacity;
    memcpy(buffer, part->data + (size_t) offset, read_size);
    *out_read = read_size;
    return ERMAO_MOBI_OK;
}

ErmaoMobiStatus ermao_mobi_reading_order_count(const ErmaoMobiBook *book, uint32_t *out_count) {
    if (book == NULL || out_count == NULL) {
        return ERMAO_MOBI_INVALID_ARGUMENT;
    }
    *out_count = book->reading_order_count;
    return ERMAO_MOBI_OK;
}

ErmaoMobiStatus ermao_mobi_reading_order_resource_index(
    const ErmaoMobiBook *book,
    uint32_t position,
    uint32_t *out_resource_index
) {
    if (book == NULL || out_resource_index == NULL) {
        return ERMAO_MOBI_INVALID_ARGUMENT;
    }
    if (position >= book->reading_order_count) {
        return ERMAO_MOBI_OUT_OF_RANGE;
    }
    *out_resource_index = book->reading_order[position];
    return ERMAO_MOBI_OK;
}

ErmaoMobiStatus ermao_mobi_toc_count(const ErmaoMobiBook *book, uint32_t *out_count) {
    if (book == NULL || out_count == NULL) {
        return ERMAO_MOBI_INVALID_ARGUMENT;
    }
    *out_count = book->toc_count;
    return ERMAO_MOBI_OK;
}

ErmaoMobiStatus ermao_mobi_get_toc_info(
    const ErmaoMobiBook *book,
    uint32_t toc_index,
    ErmaoMobiTocInfo *out_info
) {
    if (book == NULL || out_info == NULL || out_info->struct_size < sizeof(*out_info)) {
        return ERMAO_MOBI_INVALID_ARGUMENT;
    }
    if (toc_index >= book->toc_count) {
        return ERMAO_MOBI_OUT_OF_RANGE;
    }
    out_info->parent_index = book->toc[toc_index].parent_index;
    out_info->target_resource_index = book->toc[toc_index].target_resource_index;
    return ERMAO_MOBI_OK;
}

ErmaoMobiStatus ermao_mobi_copy_toc_title(
    const ErmaoMobiBook *book,
    uint32_t toc_index,
    char *buffer,
    uint32_t capacity,
    uint32_t *out_required
) {
    if (book == NULL) {
        return ERMAO_MOBI_INVALID_ARGUMENT;
    }
    if (toc_index >= book->toc_count) {
        return ERMAO_MOBI_OUT_OF_RANGE;
    }
    return ermao_copy_out(book->toc[toc_index].title, buffer, capacity, out_required);
}

ErmaoMobiStatus ermao_mobi_copy_toc_fragment(
    const ErmaoMobiBook *book,
    uint32_t toc_index,
    char *buffer,
    uint32_t capacity,
    uint32_t *out_required
) {
    if (book == NULL) {
        return ERMAO_MOBI_INVALID_ARGUMENT;
    }
    if (toc_index >= book->toc_count) {
        return ERMAO_MOBI_OUT_OF_RANGE;
    }
    return ermao_copy_out(book->toc[toc_index].fragment, buffer, capacity, out_required);
}

ErmaoMobiStatus ermao_mobi_warning_count(const ErmaoMobiBook *book, uint32_t *out_count) {
    if (book == NULL || out_count == NULL) {
        return ERMAO_MOBI_INVALID_ARGUMENT;
    }
    *out_count = book->warning_count;
    return ERMAO_MOBI_OK;
}

ErmaoMobiStatus ermao_mobi_get_warning_info(
    const ErmaoMobiBook *book,
    uint32_t warning_index,
    ErmaoMobiWarningInfo *out_info
) {
    if (book == NULL || out_info == NULL || out_info->struct_size < sizeof(*out_info)) {
        return ERMAO_MOBI_INVALID_ARGUMENT;
    }
    if (warning_index >= book->warning_count) {
        return ERMAO_MOBI_OUT_OF_RANGE;
    }
    out_info->code = book->warnings[warning_index].code;
    out_info->related_index = book->warnings[warning_index].related_index;
    return ERMAO_MOBI_OK;
}
