#include "mobi_bridge.h"

#include "mobi.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char *copy_string(const char *value) {
    if (value == NULL) {
        return NULL;
    }
    const size_t length = strlen(value);
    char *copy = malloc(length + 1);
    if (copy != NULL) {
        memcpy(copy, value, length + 1);
    }
    return copy;
}

static char *make_error(const char *message, MOBI_RET result) {
    char buffer[160];
    if (result == MOBI_SUCCESS) {
        snprintf(buffer, sizeof(buffer), "%s", message);
    } else {
        snprintf(buffer, sizeof(buffer), "%s (libmobi code %d)", message, (int) result);
    }
    return copy_string(buffer);
}

static size_t part_count(const MOBIRawml *rawml) {
    size_t count = 0;
    const MOBIPart *part = rawml->markup;
    while (part != NULL) {
        count++;
        part = part->next;
    }

    part = rawml->flow;
    if (part != NULL) {
        part = part->next; /* The first flow item is the unsplit raw HTML. */
    }
    while (part != NULL) {
        count++;
        part = part->next;
    }

    part = rawml->resources;
    while (part != NULL) {
        if (part->size > 0) {
            count++;
        }
        part = part->next;
    }
    return count;
}

static bool copy_part(
    ShukuMobiPart *target,
    const MOBIPart *source,
    ShukuMobiPartCategory category
) {
    const MOBIFileMeta metadata = mobi_get_filemeta_by_type(source->type);
    const char *prefix = category == SHUKU_MOBI_PART_MARKUP
        ? "part"
        : (category == SHUKU_MOBI_PART_FLOW ? "flow" : "resource");
    char name[64];
    const int written = snprintf(
        name,
        sizeof(name),
        "%s%05zu.%s",
        prefix,
        source->uid,
        metadata.extension
    );
    if (written <= 0 || (size_t) written >= sizeof(name)) {
        return false;
    }

    target->uid = source->uid;
    target->category = category;
    target->mobi_file_type = (int32_t) source->type;
    target->name = copy_string(name);
    target->media_type = copy_string(metadata.mime_type);
    target->bytes = malloc(source->size);
    target->length = source->size;
    if (target->name == NULL || target->media_type == NULL || target->bytes == NULL) {
        return false;
    }
    memcpy(target->bytes, source->data, source->size);
    return true;
}

static void free_part(ShukuMobiPart *part) {
    if (part == NULL) {
        return;
    }
    free(part->name);
    free(part->media_type);
    free(part->bytes);
}

void shuku_mobi_free_book(ShukuMobiBook *book) {
    if (book == NULL) {
        return;
    }
    free(book->title);
    free(book->author);
    free(book->language);
    free(book->description_text);
    if (book->parts != NULL) {
        for (size_t index = 0; index < book->part_count; index++) {
            free_part(&book->parts[index]);
        }
    }
    free(book->parts);
    free(book);
}

void shuku_mobi_free_error(char *error_message) {
    free(error_message);
}

const char *shuku_mobi_version(void) {
    return mobi_version();
}

static ShukuMobiBridgeResult bridge_result_for(MOBI_RET result) {
    switch (result) {
        case MOBI_FILE_ENCRYPTED:
        case MOBI_DRM_UNSUPPORTED:
            return SHUKU_MOBI_BRIDGE_ENCRYPTED;
        case MOBI_FILE_UNSUPPORTED:
            return SHUKU_MOBI_BRIDGE_UNSUPPORTED;
        case MOBI_DATA_CORRUPT:
        case MOBI_BUFFER_END:
            return SHUKU_MOBI_BRIDGE_CORRUPT;
        case MOBI_MALLOC_FAILED:
            return SHUKU_MOBI_BRIDGE_OUT_OF_MEMORY;
        default:
            return SHUKU_MOBI_BRIDGE_LIBMOBI_ERROR;
    }
}

ShukuMobiBridgeResult shuku_mobi_extract_path(
    const char *path,
    ShukuMobiBook **book,
    char **error_message
) {
    if (path == NULL || book == NULL || error_message == NULL) {
        return SHUKU_MOBI_BRIDGE_INVALID_ARGUMENT;
    }
    *book = NULL;
    *error_message = NULL;

    MOBIData *mobi = mobi_init();
    if (mobi == NULL) {
        *error_message = make_error("Unable to initialize libmobi", MOBI_INIT_FAILED);
        return SHUKU_MOBI_BRIDGE_OUT_OF_MEMORY;
    }

    MOBI_RET result = mobi_load_filename(mobi, path);
    if (result != MOBI_SUCCESS) {
        *error_message = make_error("Unable to load MOBI container", result);
        mobi_free(mobi);
        return bridge_result_for(result);
    }
    if (!mobi_is_mobipocket(mobi) || mobi_is_replica(mobi)) {
        *error_message = make_error("The file is not a supported MOBI6/KF8 publication", MOBI_FILE_UNSUPPORTED);
        mobi_free(mobi);
        return SHUKU_MOBI_BRIDGE_UNSUPPORTED;
    }
    if (mobi_is_encrypted(mobi)) {
        *error_message = make_error("DRM-protected MOBI/AZW content is not supported", MOBI_FILE_ENCRYPTED);
        mobi_free(mobi);
        return SHUKU_MOBI_BRIDGE_ENCRYPTED;
    }

    MOBIRawml *rawml = mobi_init_rawml(mobi);
    if (rawml == NULL) {
        *error_message = make_error("Unable to initialize RAWML extraction", MOBI_INIT_FAILED);
        mobi_free(mobi);
        return SHUKU_MOBI_BRIDGE_OUT_OF_MEMORY;
    }

    /* mobi_parse_rawml reconstructs links and invokes mobi_decode_font_resource
       for every FONT resource before returning the resource list. */
    result = mobi_parse_rawml(rawml, mobi);
    if (result != MOBI_SUCCESS) {
        *error_message = make_error("Unable to reconstruct MOBI resources", result);
        mobi_free_rawml(rawml);
        mobi_free(mobi);
        return bridge_result_for(result);
    }
    if (rawml->markup == NULL) {
        *error_message = make_error("MOBI publication has no reconstructed markup", MOBI_SUCCESS);
        mobi_free_rawml(rawml);
        mobi_free(mobi);
        return SHUKU_MOBI_BRIDGE_NO_MARKUP;
    }

    ShukuMobiBook *output = calloc(1, sizeof(ShukuMobiBook));
    if (output == NULL) {
        *error_message = make_error("Unable to allocate extraction result", MOBI_MALLOC_FAILED);
        mobi_free_rawml(rawml);
        mobi_free(mobi);
        return SHUKU_MOBI_BRIDGE_OUT_OF_MEMORY;
    }

    output->format = mobi_is_hybrid(mobi)
        ? SHUKU_MOBI_FORMAT_HYBRID
        : (mobi_is_rawml_kf8(rawml) ? SHUKU_MOBI_FORMAT_KF8 : SHUKU_MOBI_FORMAT_MOBI6);
    output->title = mobi_meta_get_title(mobi);
    output->author = mobi_meta_get_author(mobi);
    output->language = mobi_meta_get_language(mobi);
    output->description_text = mobi_meta_get_description(mobi);
    output->part_count = part_count(rawml);
    output->parts = calloc(output->part_count, sizeof(ShukuMobiPart));
    if (output->parts == NULL) {
        *error_message = make_error("Unable to allocate extracted resources", MOBI_MALLOC_FAILED);
        shuku_mobi_free_book(output);
        mobi_free_rawml(rawml);
        mobi_free(mobi);
        return SHUKU_MOBI_BRIDGE_OUT_OF_MEMORY;
    }

    size_t index = 0;
    const MOBIPart *part = rawml->markup;
    while (part != NULL) {
        if (!copy_part(&output->parts[index++], part, SHUKU_MOBI_PART_MARKUP)) {
            goto allocation_failure;
        }
        part = part->next;
    }

    part = rawml->flow;
    if (part != NULL) {
        part = part->next;
    }
    while (part != NULL) {
        if (!copy_part(&output->parts[index++], part, SHUKU_MOBI_PART_FLOW)) {
            goto allocation_failure;
        }
        part = part->next;
    }

    part = rawml->resources;
    while (part != NULL) {
        if (part->size > 0) {
            if (!copy_part(&output->parts[index++], part, SHUKU_MOBI_PART_RESOURCE)) {
                goto allocation_failure;
            }
            if (part->type == T_OPF) {
                output->has_opf = true;
            } else if (part->type == T_NCX) {
                output->has_ncx = true;
            }
        }
        part = part->next;
    }

    mobi_free_rawml(rawml);
    mobi_free(mobi);
    *book = output;
    return SHUKU_MOBI_BRIDGE_SUCCESS;

allocation_failure:
    *error_message = make_error("Unable to copy extracted resource", MOBI_MALLOC_FAILED);
    shuku_mobi_free_book(output);
    mobi_free_rawml(rawml);
    mobi_free(mobi);
    return SHUKU_MOBI_BRIDGE_OUT_OF_MEMORY;
}
