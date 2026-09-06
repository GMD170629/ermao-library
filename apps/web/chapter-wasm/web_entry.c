#include "ermao_chapters.h"

#include <stdint.h>

/* Keep the independently built chapter ABI reachable from the Emscripten archive. */
ERMAO_CHAPTER_API uint32_t ermao_chapters_web_abi_anchor(void) {
    return ermao_chapters_abi_version();
}

/*
 * C struct padding is compiler-specific. The Web ABI copies the public result
 * into twelve uint32 values so JavaScript only consumes an explicit wasm32
 * representation: index, parent, navigable, three pointers, and three uint64
 * values represented as low/high pairs.
 */
ERMAO_CHAPTER_API ErmaoChapterStatus ermao_chapters_web_copy_entry(
    const ErmaoChapterResult *result,
    uint32_t index,
    uint32_t *out
) {
    if (result == NULL || out == NULL) return ERMAO_CHAPTER_INVALID_INPUT;
    const ErmaoChapterEntry *entry = ermao_chapters_entry(result, index);
    if (entry == NULL) return ERMAO_CHAPTER_INVALID_INPUT;
    out[0] = entry->index;
    out[1] = (uint32_t) entry->parent_index;
    out[2] = entry->navigable;
    out[3] = (uint32_t) (uintptr_t) entry->key;
    out[4] = (uint32_t) (uintptr_t) entry->title;
    out[5] = (uint32_t) (uintptr_t) entry->href;
    out[6] = (uint32_t) entry->source_start;
    out[7] = (uint32_t) (entry->source_start >> 32u);
    out[8] = (uint32_t) entry->source_end;
    out[9] = (uint32_t) (entry->source_end >> 32u);
    out[10] = (uint32_t) entry->content_start;
    out[11] = (uint32_t) (entry->content_start >> 32u);
    return ERMAO_CHAPTER_OK;
}

ERMAO_CHAPTER_API ErmaoChapterStatus ermao_chapters_web_copy_text_length(
    const ErmaoChapterResult *result,
    uint32_t *out
) {
    if (result == NULL || out == NULL) return ERMAO_CHAPTER_INVALID_INPUT;
    const uint64_t length = ermao_chapters_text_length(result);
    out[0] = (uint32_t) length;
    out[1] = (uint32_t) (length >> 32u);
    return ERMAO_CHAPTER_OK;
}
