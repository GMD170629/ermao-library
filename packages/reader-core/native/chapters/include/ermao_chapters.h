#ifndef ERMAO_CHAPTERS_H
#define ERMAO_CHAPTERS_H

#include <stddef.h>
#include <stdint.h>

#ifdef _WIN32
#define ERMAO_CHAPTER_API __declspec(dllexport)
#else
#define ERMAO_CHAPTER_API __attribute__((visibility("default")))
#endif
#ifdef __cplusplus
extern "C" {
#endif

/* No filesystem, XML codec, renderer, policy or Locator ownership crosses this ABI.
 * Text is UTF-8. All input pointers are borrowed for the duration of the call.
 * XML adapters emit the entire parsed document in source order, without applying
 * chapter filtering. target_href annotates existing, resolved publication targets
 * (anchors/NCX content/FB2 sections); NULL means no readable target. */
typedef enum {
    ERMAO_CHAPTER_OK = 0,
    ERMAO_CHAPTER_INVALID_INPUT = 1,
    ERMAO_CHAPTER_OUT_OF_MEMORY = 2
} ErmaoChapterStatus;
typedef enum {
    ERMAO_CHAPTER_EPUB_NAV = 1,
    ERMAO_CHAPTER_EPUB_NCX = 2,
    ERMAO_CHAPTER_FB2 = 3
} ErmaoChapterXmlFormat;
typedef enum {
    ERMAO_CHAPTER_XML_START = 1,
    ERMAO_CHAPTER_XML_TEXT = 2,
    ERMAO_CHAPTER_XML_END = 3
} ErmaoChapterXmlEventKind;
typedef struct {
    const char *name;
    const char *value;
} ErmaoChapterAttribute;
typedef struct {
    uint32_t kind;
    const char *name;
    const char *text;
    const ErmaoChapterAttribute *attributes;
    uint32_t attribute_count;
    const char *target_href;
} ErmaoChapterXmlEvent;
typedef struct {
    int32_t parent_index; /* -1 for a root */
    const char *title;
    const char *target_href;
} ErmaoChapterMobiNode;
typedef struct {
    uint32_t index; /* zero-based pre-order, never reading-order index */
    int32_t parent_index;
    uint32_t navigable;
    const char *key; /* deterministic within the publication, independent of title */
    const char *title;
    const char *href; /* NULL for a non-clickable group */
    uint64_t source_start; /* TXT normalized UTF-8 byte range; XML start-element ordinal */
    uint64_t source_end; /* TXT exclusive byte offset */
    uint64_t content_start; /* TXT first body byte, after the full heading */
} ErmaoChapterEntry;
typedef struct ErmaoChapterResult ErmaoChapterResult;

ERMAO_CHAPTER_API uint32_t ermao_chapters_abi_version(void);
ERMAO_CHAPTER_API ErmaoChapterStatus ermao_chapters_parse_txt(
    const uint8_t *utf8, uint64_t length, ErmaoChapterResult **result);
ERMAO_CHAPTER_API ErmaoChapterStatus ermao_chapters_parse_xml(
    uint32_t format, const ErmaoChapterXmlEvent *events, uint32_t count,
    ErmaoChapterResult **result);
ERMAO_CHAPTER_API ErmaoChapterStatus ermao_chapters_from_mobi(
    const ErmaoChapterMobiNode *nodes, uint32_t count, ErmaoChapterResult **result);
ERMAO_CHAPTER_API uint32_t ermao_chapters_count(const ErmaoChapterResult *result);
ERMAO_CHAPTER_API uint32_t ermao_chapters_navigable_count(const ErmaoChapterResult *result);
ERMAO_CHAPTER_API const ErmaoChapterEntry *ermao_chapters_entry(
    const ErmaoChapterResult *result, uint32_t index);
ERMAO_CHAPTER_API const uint8_t *ermao_chapters_text(const ErmaoChapterResult *result);
ERMAO_CHAPTER_API uint64_t ermao_chapters_text_length(const ErmaoChapterResult *result);
ERMAO_CHAPTER_API void ermao_chapters_free(ErmaoChapterResult *result);

#ifdef __cplusplus
}
#endif
#endif
