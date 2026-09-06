#include "ermao_chapters.h"

#include <ctype.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ERMAO_ABI_VERSION 1U

typedef struct {
    ErmaoChapterEntry *items;
    uint32_t count;
    uint32_t capacity;
} EntryBuilder;

typedef struct OutNode OutNode;
struct OutNode {
    char *title;
    char *href;
    uint64_t source_start;
    OutNode **children;
    uint32_t child_count;
};

typedef struct {
    OutNode **items;
    uint32_t count;
    uint32_t capacity;
} NodeList;

typedef struct {
    uint32_t child_index;
    const char *text;
    bool is_child;
} XmlSegment;

typedef struct {
    const char *name;
    const ErmaoChapterAttribute *attributes;
    uint32_t attribute_count;
    const char *target_href;
    uint64_t source_start;
    int32_t parent;
    uint32_t *children;
    uint32_t child_count;
    uint32_t child_capacity;
    XmlSegment *segments;
    uint32_t segment_count;
    uint32_t segment_capacity;
} XmlNode;

typedef struct {
    XmlNode *items;
    uint32_t count;
    uint32_t capacity;
} XmlNodeArray;

typedef struct {
    size_t start;
    size_t end;
    size_t content_start;
    char *title;
} TxtHeading;

typedef struct {
    TxtHeading *items;
    uint32_t count;
    uint32_t capacity;
} TxtHeadingArray;

struct ErmaoChapterResult {
    ErmaoChapterEntry *entries;
    uint32_t count;
    uint32_t navigable_count;
    uint8_t *text;
    uint64_t text_length;
};

static bool size_add_ok(size_t a, size_t b, size_t *out) {
    if (b > SIZE_MAX - a) {
        return false;
    }
    *out = a + b;
    return true;
}

static bool size_mul_ok(size_t a, size_t b, size_t *out) {
    if (a != 0U && b > SIZE_MAX / a) {
        return false;
    }
    *out = a * b;
    return true;
}

static char *copy_bytes(const char *value, size_t length) {
    char *copy;
    size_t bytes;
    if (!size_add_ok(length, 1U, &bytes)) {
        return NULL;
    }
    copy = (char *)malloc(bytes);
    if (copy == NULL) {
        return NULL;
    }
    if (length != 0U && value != NULL) {
        memcpy(copy, value, length);
    }
    copy[length] = '\0';
    return copy;
}

static char *copy_cstr(const char *value) {
    return value == NULL ? NULL : copy_bytes(value, strlen(value));
}

static bool cstr_nonempty(const char *value) {
    return value != NULL && value[0] != '\0';
}

static bool cstr_equal(const char *a, const char *b) {
    return a != NULL && b != NULL && strcmp(a, b) == 0;
}

static bool ascii_equal_ci_n(const char *value, const char *other, size_t length) {
    size_t i;
    for (i = 0U; i < length; ++i) {
        if (tolower((unsigned char)value[i]) != tolower((unsigned char)other[i])) {
            return false;
        }
    }
    return true;
}

static bool ascii_space(unsigned char value) {
    return value == ' ' || value == '\t' || value == '\r' || value == '\n' ||
           value == '\v' || value == '\f';
}

static size_t trim_left(const char *value, size_t length) {
    size_t at = 0U;
    while (at < length && ascii_space((unsigned char)value[at])) {
        ++at;
    }
    return at;
}

static size_t trim_right(const char *value, size_t start, size_t length) {
    while (length > start && ascii_space((unsigned char)value[length - 1U])) {
        --length;
    }
    return length;
}

static char *trimmed_copy(const char *value, size_t length) {
    size_t start = trim_left(value, length);
    size_t end = trim_right(value, start, length);
    return copy_bytes(value + start, end - start);
}

static size_t utf8_sequence_length(const unsigned char *value, size_t length, size_t at) {
    unsigned char first;
    size_t needed;
    size_t i;
    if (at >= length) {
        return 0U;
    }
    first = value[at];
    if (first < 0x80U) {
        return 1U;
    }
    if (first >= 0xC2U && first <= 0xDFU) {
        needed = 2U;
    } else if (first >= 0xE0U && first <= 0xEFU) {
        needed = 3U;
    } else if (first >= 0xF0U && first <= 0xF4U) {
        needed = 4U;
    } else {
        return 0U;
    }
    if (needed > length - at) {
        return 0U;
    }
    for (i = 1U; i < needed; ++i) {
        if ((value[at + i] & 0xC0U) != 0x80U) {
            return 0U;
        }
    }
    if (needed == 3U && ((first == 0xE0U && value[at + 1U] < 0xA0U) ||
                         (first == 0xEDU && value[at + 1U] >= 0xA0U))) {
        return 0U;
    }
    if (needed == 4U && ((first == 0xF0U && value[at + 1U] < 0x90U) ||
                         (first == 0xF4U && value[at + 1U] >= 0x90U))) {
        return 0U;
    }
    return needed;
}

static bool valid_utf8(const uint8_t *value, uint64_t length) {
    uint64_t at = 0U;
    size_t sequence;
    if (length > (uint64_t)SIZE_MAX) {
        return false;
    }
    while (at < length) {
        sequence = utf8_sequence_length(value, (size_t)length, (size_t)at);
        if (sequence == 0U) {
            return false;
        }
        at += (uint64_t)sequence;
    }
    return true;
}

static size_t utf8_count(const char *value, size_t length) {
    size_t at = 0U;
    size_t count = 0U;
    size_t sequence;
    while (at < length) {
        sequence = utf8_sequence_length((const unsigned char *)value, length, at);
        if (sequence == 0U) {
            return SIZE_MAX;
        }
        at += sequence;
        ++count;
    }
    return count;
}

static ErmaoChapterStatus normalize_txt(const uint8_t *input, uint64_t length,
                                        uint8_t **output, uint64_t *output_length) {
    uint8_t *normalized;
    size_t input_size;
    size_t at = 0U;
    size_t out = 0U;
    if (input == NULL && length != 0U) {
        return ERMAO_CHAPTER_INVALID_INPUT;
    }
    if (!valid_utf8(input, length) || length > (uint64_t)SIZE_MAX - 1U) {
        return ERMAO_CHAPTER_INVALID_INPUT;
    }
    input_size = (size_t)length;
    normalized = (uint8_t *)malloc(input_size + 1U);
    if (normalized == NULL) {
        return ERMAO_CHAPTER_OUT_OF_MEMORY;
    }
    while (at < input_size) {
        if (input[at] == '\r') {
            if (at + 1U < input_size && input[at + 1U] == '\n') {
                ++at;
            }
            normalized[out++] = '\n';
            ++at;
        } else if (input[at] == '\n') {
            normalized[out++] = '\n';
            ++at;
        } else if (at + 3U <= input_size && input[at] == 0xE2U &&
                   input[at + 1U] == 0x80U &&
                   (input[at + 2U] == 0xA8U || input[at + 2U] == 0xA9U)) {
            normalized[out++] = '\n';
            at += 3U;
        } else {
            normalized[out++] = input[at++];
        }
    }
    normalized[out] = '\0';
    *output = normalized;
    *output_length = (uint64_t)out;
    return ERMAO_CHAPTER_OK;
}

static void entry_builder_dispose(EntryBuilder *builder) {
    uint32_t i;
    for (i = 0U; i < builder->count; ++i) {
        free((char *)builder->items[i].key);
        free((char *)builder->items[i].title);
        free((char *)builder->items[i].href);
    }
    free(builder->items);
    builder->items = NULL;
    builder->count = 0U;
    builder->capacity = 0U;
}

static bool entry_builder_reserve(EntryBuilder *builder, uint32_t needed) {
    uint32_t next;
    size_t bytes;
    ErmaoChapterEntry *items;
    if (needed <= builder->capacity) {
        return true;
    }
    next = builder->capacity == 0U ? 8U : builder->capacity;
    while (next < needed) {
        if (next > UINT32_MAX / 2U) {
            next = needed;
            break;
        }
        next *= 2U;
    }
    if (!size_mul_ok((size_t)next, sizeof(*items), &bytes)) {
        return false;
    }
    items = (ErmaoChapterEntry *)realloc(builder->items, bytes);
    if (items == NULL) {
        return false;
    }
    builder->items = items;
    builder->capacity = next;
    return true;
}

static char *make_key(uint32_t index) {
    char value[48];
    int written = snprintf(value, sizeof(value), "chapter-%u", (unsigned)index);
    return written < 0 || (size_t)written >= sizeof(value) ? NULL :
           copy_bytes(value, (size_t)written);
}

static char *make_txt_href(uint32_t index) {
    char value[96];
    int written = snprintf(value, sizeof(value), "text/chapter-%04u.xhtml#heading-000001",
                           (unsigned)(index + 1U));
    return written < 0 || (size_t)written >= sizeof(value) ? NULL :
           copy_bytes(value, (size_t)written);
}

static bool entry_builder_append(EntryBuilder *builder, const char *title, const char *href,
                                 uint64_t source_start, uint64_t source_end,
                                 uint64_t content_start, int32_t parent_index) {
    ErmaoChapterEntry *entry;
    char *key;
    char *title_copy;
    char *href_copy;
    if (builder->count == UINT32_MAX ||
        !entry_builder_reserve(builder, builder->count + 1U)) {
        return false;
    }
    key = make_key(builder->count);
    title_copy = title == NULL ? NULL : copy_cstr(title);
    href_copy = href == NULL ? NULL : copy_cstr(href);
    if (key == NULL || (title != NULL && title_copy == NULL) ||
        (href != NULL && href_copy == NULL)) {
        free(key);
        free(title_copy);
        free(href_copy);
        return false;
    }
    entry = &builder->items[builder->count];
    memset(entry, 0, sizeof(*entry));
    entry->index = builder->count;
    entry->parent_index = parent_index;
    entry->navigable = href_copy != NULL && href_copy[0] != '\0';
    entry->key = key;
    entry->title = title_copy;
    entry->href = href_copy;
    entry->source_start = source_start;
    entry->source_end = source_end;
    entry->content_start = content_start;
    ++builder->count;
    return true;
}

static ErmaoChapterResult *result_from_builder(EntryBuilder *builder, uint8_t *text,
                                               uint64_t text_length) {
    ErmaoChapterResult *result = (ErmaoChapterResult *)calloc(1U, sizeof(*result));
    uint32_t i;
    if (result == NULL) {
        entry_builder_dispose(builder);
        free(text);
        return NULL;
    }
    result->entries = builder->items;
    result->count = builder->count;
    result->text = text;
    result->text_length = text_length;
    for (i = 0U; i < result->count; ++i) {
        if (result->entries[i].navigable != 0U) {
            ++result->navigable_count;
        }
    }
    builder->items = NULL;
    builder->count = 0U;
    builder->capacity = 0U;
    return result;
}

static void txt_headings_dispose(TxtHeadingArray *headings) {
    uint32_t i;
    for (i = 0U; i < headings->count; ++i) {
        free(headings->items[i].title);
    }
    free(headings->items);
    headings->items = NULL;
    headings->count = 0U;
    headings->capacity = 0U;
}

static bool txt_heading_append(TxtHeadingArray *headings, size_t start, size_t end,
                               size_t content_start, char *title) {
    uint32_t next;
    size_t bytes;
    TxtHeading *items;
    if (headings->count == UINT32_MAX) {
        return false;
    }
    if (headings->count == headings->capacity) {
        next = headings->capacity == 0U ? 8U : headings->capacity * 2U;
        if (next < headings->capacity ||
            !size_mul_ok((size_t)next, sizeof(*items), &bytes)) {
            return false;
        }
        items = (TxtHeading *)realloc(headings->items, bytes);
        if (items == NULL) {
            return false;
        }
        headings->items = items;
        headings->capacity = next;
    }
    headings->items[headings->count].start = start;
    headings->items[headings->count].end = end;
    headings->items[headings->count].content_start = content_start;
    headings->items[headings->count].title = title;
    ++headings->count;
    return true;
}

static bool chinese_numeral(const char *value, size_t length, size_t *used) {
    static const char *const numerals[] = {
        "〇", "零", "一", "二", "三", "四", "五", "六", "七", "八",
        "九", "十", "百", "千", "万", "两", "0", "1", "2", "3", "4",
        "5", "6", "7", "8", "9", "０", "１", "２", "３", "４", "５",
        "６", "７", "８", "９"
    };
    size_t i;
    size_t size;
    for (i = 0U; i < sizeof(numerals) / sizeof(numerals[0]); ++i) {
        size = strlen(numerals[i]);
        if (length >= size && memcmp(value, numerals[i], size) == 0) {
            *used = size;
            return true;
        }
    }
    return false;
}

static bool chinese_heading_space(unsigned char value) {
    return value == ' ' || value == '\t';
}

static bool chinese_suffix_start(const char *value, size_t length, size_t at) {
    if (at >= length || chinese_heading_space((unsigned char)value[at]) ||
        value[at] == ':') {
        return true;
    }
    if (at + 3U <= length && (unsigned char)value[at] == 0xE3U &&
        (unsigned char)value[at + 1U] == 0x80U &&
        (unsigned char)value[at + 2U] == 0x80U) {
        return true;
    }
    return at + 3U <= length && (unsigned char)value[at] == 0xEFU &&
           (unsigned char)value[at + 1U] == 0xBCU &&
           (unsigned char)value[at + 2U] == 0x9AU;
}

static bool chinese_heading(const char *value, size_t length, size_t *after_number) {
    static const char *const endings[] = {"章", "节", "回", "卷", "篇", "部"};
    size_t at = 3U;
    size_t used;
    size_t ending_size;
    size_t i;
    bool found_number = false;
    if (length < 6U || memcmp(value, "第", 3U) != 0) {
        return false;
    }
    while (at < length && chinese_heading_space((unsigned char)value[at])) {
        ++at;
    }
    while (at < length && chinese_numeral(value + at, length - at, &used)) {
        at += used;
        found_number = true;
    }
    if (!found_number) {
        return false;
    }
    while (at < length && chinese_heading_space((unsigned char)value[at])) {
        ++at;
    }
    for (i = 0U; i < sizeof(endings) / sizeof(endings[0]); ++i) {
        ending_size = strlen(endings[i]);
        if (at + ending_size <= length && memcmp(value + at, endings[i], ending_size) == 0) {
            at += ending_size;
            if (!chinese_suffix_start(value, length, at)) {
                return false;
            }
            *after_number = at;
            return true;
        }
    }
    return false;
}

static bool roman_or_digit(unsigned char value) {
    switch ((unsigned char)tolower(value)) {
    case 'i':
    case 'v':
    case 'x':
    case 'l':
    case 'c':
    case 'd':
    case 'm':
    case '0':
    case '1':
    case '2':
    case '3':
    case '4':
    case '5':
    case '6':
    case '7':
    case '8':
    case '9':
        return true;
    default:
        return false;
    }
}

static bool latin_heading(const char *value, size_t length, size_t *after_number) {
    static const char *const prefixes[] = {"chapter", "part", "book"};
    size_t i;
    size_t prefix_size;
    size_t at;
    size_t number_start;
    for (i = 0U; i < sizeof(prefixes) / sizeof(prefixes[0]); ++i) {
        prefix_size = strlen(prefixes[i]);
        if (length < prefix_size) {
            continue;
        }
        if (!ascii_equal_ci_n(value, prefixes[i], prefix_size)) {
            continue;
        }
        at = prefix_size;
        if (at >= length || (value[at] != ' ' && value[at] != '\t')) {
            continue;
        }
        while (at < length && (value[at] == ' ' || value[at] == '\t')) {
            ++at;
        }
        number_start = at;
        while (at < length && roman_or_digit((unsigned char)value[at])) {
            ++at;
        }
        if (at == number_start) {
            continue;
        }
        if (at < length && value[at] != ' ' && value[at] != '\t' && value[at] != '.' &&
            value[at] != ':' && value[at] != '-' &&
            !(at + 3U <= length && (unsigned char)value[at] == 0xEFU &&
              (unsigned char)value[at + 1U] == 0xBCU &&
              (unsigned char)value[at + 2U] == 0x9AU)) {
            continue;
        }
        *after_number = at;
        return true;
    }
    return false;
}

static char *txt_title(const char *line, size_t length) {
    size_t left = trim_left(line, length);
    size_t right = trim_right(line, left, length);
    size_t after_number = 0U;
    if (right <= left || utf8_count(line + left, right - left) > 96U) {
        return NULL;
    }
    if (!chinese_heading(line + left, right - left, &after_number) &&
        !latin_heading(line + left, right - left, &after_number)) {
        return NULL;
    }
    return copy_bytes(line + left, right - left);
}

static bool txt_bare_heading(const char *title) {
    size_t length = strlen(title);
    size_t left = trim_left(title, length);
    size_t right = trim_right(title, left, length);
    size_t number_end = 0U;
    size_t at;
    if (right <= left ||
        (chinese_heading(title + left, right - left, &number_end) == false &&
         latin_heading(title + left, right - left, &number_end) == false)) {
        return false;
    }
    at = left + number_end;
    while (at < right) {
        if (title[at] == '.' || title[at] == ':' || title[at] == '-') {
            ++at;
        } else if (at + 3U <= right && (unsigned char)title[at] == 0xEFU &&
                   (unsigned char)title[at + 1U] == 0xBCU &&
                   (unsigned char)title[at + 2U] == 0x9AU) {
            at += 3U;
        } else if (ascii_space((unsigned char)title[at])) {
            ++at;
        } else {
            return false;
        }
    }
    return true;
}

static bool txt_heading_number_equal(const char *first, const char *second) {
    size_t first_length = strlen(first);
    size_t second_length = strlen(second);
    size_t first_left = trim_left(first, first_length);
    size_t second_left = trim_left(second, second_length);
    size_t first_right = trim_right(first, first_left, first_length);
    size_t second_right = trim_right(second, second_left, second_length);
    size_t first_number_end = 0U;
    size_t second_number_end = 0U;
    size_t i;
    if (first_right <= first_left || second_right <= second_left) {
        return false;
    }
    if ((!chinese_heading(first + first_left, first_right - first_left,
                          &first_number_end) &&
         !latin_heading(first + first_left, first_right - first_left,
                        &first_number_end)) ||
        (!chinese_heading(second + second_left, second_right - second_left,
                          &second_number_end) &&
         !latin_heading(second + second_left, second_right - second_left,
                        &second_number_end))) {
        return false;
    }
    if (first_number_end != second_number_end) {
        return false;
    }
    for (i = 0U; i < first_number_end; ++i) {
        if (tolower((unsigned char)first[first_left + i]) !=
            tolower((unsigned char)second[second_left + i])) {
            return false;
        }
    }
    return true;
}

static bool line_at(const uint8_t *text, size_t length, size_t start, size_t *end,
                    size_t *next) {
    size_t at;
    if (start >= length) {
        return false;
    }
    at = start;
    while (at < length && text[at] != '\n') {
        ++at;
    }
    *end = at;
    *next = at < length ? at + 1U : at;
    return true;
}

static bool blank_line(const uint8_t *text, size_t start, size_t end) {
    size_t at;
    for (at = start; at < end; ++at) {
        if (!ascii_space(text[at])) {
            return false;
        }
    }
    return true;
}

static bool txt_collect_headings(const uint8_t *text, size_t length,
                                 TxtHeadingArray *headings) {
    size_t cursor = 0U;
    size_t line_end;
    size_t next;
    while (line_at(text, length, cursor, &line_end, &next)) {
        char *title = txt_title((const char *)text + cursor, line_end - cursor);
        size_t full_end = line_end;
        size_t content_start = next;
        if (title != NULL) {
            size_t title_end;
            size_t title_next;
            size_t blank_end;
            size_t blank_next;
            char *continuation = NULL;
            bool only_number = txt_bare_heading(title);
            if (only_number && next < length &&
                line_at(text, length, next, &title_end, &title_next) &&
                title_end > next && !blank_line(text, next, title_end) &&
                title_next < length &&
                line_at(text, length, title_next, &blank_end, &blank_next) &&
                blank_line(text, title_next, blank_end)) {
                continuation = txt_title((const char *)text + next, title_end - next);
                if (continuation == NULL &&
                    utf8_count((const char *)text + next, title_end - next) <= 96U) {
                    size_t continuation_start = trim_left((const char *)text + next,
                                                           title_end - next);
                    size_t continuation_end = trim_right((const char *)text + next,
                                                         continuation_start, title_end - next);
                    size_t first_length = strlen(title);
                    size_t second_length = continuation_end - continuation_start;
                    if (second_length != 0U &&
                        utf8_count(title, first_length) != SIZE_MAX &&
                        utf8_count((const char *)text + next + continuation_start,
                                   second_length) != SIZE_MAX &&
                        utf8_count(title, first_length) +
                                utf8_count((const char *)text + next + continuation_start,
                                           second_length) + 1U <= 96U) {
                        char *merged = (char *)malloc(first_length + second_length + 2U);
                        if (merged == NULL) {
                            free(title);
                            return false;
                        }
                        memcpy(merged, title, first_length);
                        merged[first_length] = ' ';
                        memcpy(merged + first_length + 1U,
                               text + next + continuation_start, second_length);
                        merged[first_length + second_length + 1U] = '\0';
                        free(title);
                        title = merged;
                        full_end = title_end;
                        content_start = title_next;
                    }
                }
                free(continuation);
            }
            if (!txt_heading_append(headings, cursor, full_end, content_start, title)) {
                free(title);
                return false;
            }
        }
        cursor = next;
    }
    return true;
}

static bool txt_leading_toc(const TxtHeadingArray *headings, const uint8_t *text,
                            size_t length, uint32_t *drop_count) {
    uint32_t run = 0U;
    uint32_t i;
    if (headings->count < 3U) {
        return false;
    }
    while (run + 1U < headings->count) {
        size_t at = headings->items[run].end;
        size_t end = headings->items[run + 1U].start;
        bool blank = true;
        while (at < end) {
            size_t line_end = at;
            while (line_end < end && text[line_end] != '\n') {
                ++line_end;
            }
            if (!blank_line(text, at, line_end)) {
                blank = false;
                break;
            }
            at = line_end < end ? line_end + 1U : line_end;
        }
        if (!blank) {
            break;
        }
        ++run;
    }
    if (run < 2U || run + 1U >= headings->count) {
        return false;
    }
    /* The first real chapter can itself be separated from the next chapter
       by a blank line. Shrink the candidate prefix until every dropped title
       has an identical later occurrence. */
    (void)length;
    for (;;) {
        bool all_duplicate = true;
        for (i = 0U; i <= run; ++i) {
            uint32_t j;
            bool duplicate = false;
            for (j = run + 1U; j < headings->count; ++j) {
                if (txt_heading_number_equal(headings->items[i].title,
                                             headings->items[j].title)) {
                    duplicate = true;
                    break;
                }
            }
            if (!duplicate) {
                all_duplicate = false;
                break;
            }
        }
        if (all_duplicate) {
            *drop_count = run + 1U;
            return true;
        }
        if (run == 2U) {
            return false;
        }
        --run;
    }
}

static ErmaoChapterStatus parse_txt_internal(const uint8_t *input, uint64_t length,
                                             ErmaoChapterResult **result) {
    uint8_t *text = NULL;
    uint64_t text_length = 0U;
    TxtHeadingArray headings = {0};
    EntryBuilder builder = {0};
    ErmaoChapterStatus status;
    uint32_t drop_count = 0U;
    uint32_t i;
    status = normalize_txt(input, length, &text, &text_length);
    if (status != ERMAO_CHAPTER_OK) {
        return status;
    }
    if (!txt_collect_headings(text, (size_t)text_length, &headings)) {
        txt_headings_dispose(&headings);
        free(text);
        return ERMAO_CHAPTER_OUT_OF_MEMORY;
    }
    (void)txt_leading_toc(&headings, text, (size_t)text_length, &drop_count);
    for (i = drop_count; i < headings.count; ++i) {
        uint32_t index = builder.count;
        uint64_t end = i + 1U < headings.count ? headings.items[i + 1U].start : text_length;
        char *href = make_txt_href(index);
        bool appended;
        if (href == NULL) {
            txt_headings_dispose(&headings);
            entry_builder_dispose(&builder);
            free(text);
            return ERMAO_CHAPTER_OUT_OF_MEMORY;
        }
        appended = entry_builder_append(&builder, headings.items[i].title, href,
                                        headings.items[i].start, end,
                                        headings.items[i].content_start, -1);
        free(href);
        if (!appended) {
            txt_headings_dispose(&headings);
            entry_builder_dispose(&builder);
            free(text);
            return ERMAO_CHAPTER_OUT_OF_MEMORY;
        }
    }
    txt_headings_dispose(&headings);
    *result = result_from_builder(&builder, text, text_length);
    return *result == NULL ? ERMAO_CHAPTER_OUT_OF_MEMORY : ERMAO_CHAPTER_OK;
}

static void xml_node_dispose(XmlNode *node) {
    free(node->children);
    free(node->segments);
    node->children = NULL;
    node->segments = NULL;
}

static void xml_nodes_dispose(XmlNodeArray *nodes) {
    uint32_t i;
    for (i = 0U; i < nodes->count; ++i) {
        xml_node_dispose(&nodes->items[i]);
    }
    free(nodes->items);
    nodes->items = NULL;
    nodes->count = 0U;
    nodes->capacity = 0U;
}

static bool xml_children_append(XmlNode *node, uint32_t child) {
    uint32_t next;
    uint32_t *items;
    size_t bytes;
    if (node->child_count == node->child_capacity) {
        next = node->child_capacity == 0U ? 4U : node->child_capacity * 2U;
        if (next < node->child_capacity ||
            !size_mul_ok((size_t)next, sizeof(*items), &bytes)) {
            return false;
        }
        items = (uint32_t *)realloc(node->children, bytes);
        if (items == NULL) {
            return false;
        }
        node->children = items;
        node->child_capacity = next;
    }
    node->children[node->child_count++] = child;
    return true;
}

static bool xml_segment_append(XmlNode *node, uint32_t child_index, const char *text,
                               bool is_child) {
    uint32_t next;
    size_t bytes;
    XmlSegment *grown;
    if (node->segment_count == node->segment_capacity) {
        next = node->segment_capacity == 0U ? 4U : node->segment_capacity * 2U;
        if (next < node->segment_capacity ||
            !size_mul_ok((size_t)next, sizeof(*grown), &bytes)) {
            return false;
        }
        grown = (XmlSegment *)realloc(node->segments, bytes);
        if (grown == NULL) {
            return false;
        }
        node->segments = grown;
        node->segment_capacity = next;
    }
    node->segments[node->segment_count].child_index = child_index;
    node->segments[node->segment_count].text = text;
    node->segments[node->segment_count].is_child = is_child;
    ++node->segment_count;
    return true;
}

static bool xml_nodes_append(XmlNodeArray *nodes, const ErmaoChapterXmlEvent *event,
                             uint64_t source_start, int32_t parent, uint32_t *index) {
    uint32_t next;
    size_t bytes;
    XmlNode *items;
    if (nodes->count == UINT32_MAX) {
        return false;
    }
    if (nodes->count == nodes->capacity) {
        next = nodes->capacity == 0U ? 16U : nodes->capacity * 2U;
        if (next < nodes->capacity ||
            !size_mul_ok((size_t)next, sizeof(*items), &bytes)) {
            return false;
        }
        items = (XmlNode *)realloc(nodes->items, bytes);
        if (items == NULL) {
            return false;
        }
        nodes->items = items;
        nodes->capacity = next;
    }
    memset(&nodes->items[nodes->count], 0, sizeof(nodes->items[nodes->count]));
    nodes->items[nodes->count].name = event->name;
    nodes->items[nodes->count].attributes = event->attributes;
    nodes->items[nodes->count].attribute_count = event->attribute_count;
    nodes->items[nodes->count].target_href = event->target_href;
    nodes->items[nodes->count].source_start = source_start;
    nodes->items[nodes->count].parent = parent;
    *index = nodes->count++;
    return true;
}

static bool xml_parse_events(const ErmaoChapterXmlEvent *events, uint32_t count,
                             XmlNodeArray *nodes) {
    int32_t current_parent = -1;
    uint64_t start_ordinal = 0U;
    uint32_t i;
    bool okay = true;
    if (count != 0U && events == NULL) {
        return false;
    }
    for (i = 0U; i < count && okay; ++i) {
        const ErmaoChapterXmlEvent *event = &events[i];
        if (event->kind == ERMAO_CHAPTER_XML_START) {
            int32_t parent = current_parent;
            uint32_t index;
            if (nodes->count > (uint32_t)INT32_MAX || event->name == NULL ||
                (event->attribute_count != 0U && event->attributes == NULL)) {
                okay = false;
                break;
            }
            if (!xml_nodes_append(nodes, event, start_ordinal++, parent, &index)) {
                okay = false;
                break;
            }
            if (parent >= 0 && (!xml_children_append(&nodes->items[parent], index) ||
                                !xml_segment_append(&nodes->items[parent], index, NULL, true))) {
                okay = false;
                break;
            }
            current_parent = (int32_t)index;
        } else if (event->kind == ERMAO_CHAPTER_XML_TEXT) {
            if (current_parent >= 0 &&
                !xml_segment_append(&nodes->items[(uint32_t)current_parent], 0U,
                                    event->text, false)) {
                okay = false;
            }
        } else if (event->kind == ERMAO_CHAPTER_XML_END) {
            XmlNode *node;
            if (event->name == NULL || current_parent < 0) {
                okay = false;
                break;
            }
            node = &nodes->items[(uint32_t)current_parent];
            if (!cstr_equal(node->name, event->name)) {
                okay = false;
                break;
            }
            current_parent = node->parent;
        } else {
            okay = false;
        }
    }
    if (current_parent != -1) {
        okay = false;
    }
    return okay;
}

static bool xml_attribute(const XmlNode *node, const char *name, const char **value) {
    uint32_t i;
    for (i = 0U; i < node->attribute_count; ++i) {
        if (node->attributes[i].name != NULL &&
            cstr_equal(node->attributes[i].name, name)) {
            *value = node->attributes[i].value == NULL ? "" : node->attributes[i].value;
            return true;
        }
    }
    return false;
}

static bool ascii_prefix_ci(const char *value, const char *prefix, size_t length) {
    size_t i;
    for (i = 0U; i < length; ++i) {
        if (tolower((unsigned char)value[i]) != tolower((unsigned char)prefix[i])) {
            return false;
        }
    }
    return true;
}

static bool token_contains_ci(const char *value, const char *token) {
    size_t token_length = strlen(token);
    size_t at = 0U;
    while (value != NULL && value[at] != '\0') {
        size_t start;
        while (value[at] != '\0' && ascii_space((unsigned char)value[at])) {
            ++at;
        }
        start = at;
        while (value[at] != '\0' && !ascii_space((unsigned char)value[at])) {
            ++at;
        }
        if (at - start == token_length &&
            ascii_prefix_ci(value + start, token, token_length)) {
            return true;
        }
    }
    return false;
}

static bool xml_name_is(const XmlNode *node, const char *name) {
    return cstr_equal(node->name, name);
}

static bool node_list_append(NodeList *list, OutNode *node) {
    uint32_t next;
    size_t bytes;
    OutNode **grown;
    if (list->count == list->capacity) {
        next = list->capacity == 0U ? 4U : list->capacity * 2U;
        if (next < list->capacity ||
            !size_mul_ok((size_t)next, sizeof(*grown), &bytes)) {
            return false;
        }
        grown = (OutNode **)realloc(list->items, bytes);
        if (grown == NULL) {
            return false;
        }
        list->items = grown;
        list->capacity = next;
    }
    list->items[list->count++] = node;
    return true;
}

static void out_node_dispose(OutNode *node) {
    uint32_t i;
    if (node == NULL) {
        return;
    }
    for (i = 0U; i < node->child_count; ++i) {
        out_node_dispose(node->children[i]);
    }
    free(node->children);
    free(node->title);
    free(node->href);
    free(node);
}

static void node_list_dispose(NodeList *list) {
    uint32_t i;
    if (list == NULL) {
        return;
    }
    for (i = 0U; i < list->count; ++i) {
        out_node_dispose(list->items[i]);
    }
    free(list->items);
    list->items = NULL;
    list->count = 0U;
    list->capacity = 0U;
}

static char *xml_all_text(const XmlNodeArray *nodes, uint32_t index) {
    const XmlNode *node = &nodes->items[index];
    char *value = copy_bytes("", 0U);
    uint32_t i;
    if (value == NULL) {
        return NULL;
    }
    for (i = 0U; i < node->segment_count; ++i) {
        char *child = node->segments[i].is_child
                          ? xml_all_text(nodes, node->segments[i].child_index)
                          : copy_cstr(node->segments[i].text == NULL ? "" :
                                      node->segments[i].text);
        size_t old_length;
        size_t child_length;
        char *grown;
        size_t at;
        if (child == NULL) {
            free(value);
            return NULL;
        }
        old_length = strlen(value);
        child_length = strlen(child);
        grown = (char *)realloc(value, old_length + child_length + 1U);
        if (grown == NULL) {
            free(child);
            free(value);
            return NULL;
        }
        value = grown;
        for (at = 0U; at < child_length; ++at) {
            value[old_length + at] = child[at];
        }
        value[old_length + child_length] = '\0';
        free(child);
    }
    /* Collapse authored XML whitespace and trim it for title identity. */
    {
        size_t length = strlen(value);
        size_t read = 0U;
        size_t write = 0U;
        bool pending_space = false;
        while (read < length) {
            if (ascii_space((unsigned char)value[read])) {
                pending_space = write != 0U;
            } else {
                if (pending_space && write != 0U && value[write - 1U] != ' ') {
                    value[write++] = ' ';
                }
                value[write++] = value[read];
                pending_space = false;
            }
            ++read;
        }
        while (write != 0U && value[write - 1U] == ' ') {
            --write;
        }
        value[write] = '\0';
    }
    return value;
}

static char *xml_direct_title(const XmlNodeArray *nodes, uint32_t index,
                              const char *title_name) {
    const XmlNode *node = &nodes->items[index];
    uint32_t i;
    for (i = 0U; i < node->child_count; ++i) {
        if (xml_name_is(&nodes->items[node->children[i]], title_name)) {
            return xml_all_text(nodes, node->children[i]);
        }
    }
    return copy_bytes("", 0U);
}

static char *xml_ncx_title(const XmlNodeArray *nodes, uint32_t index) {
    const XmlNode *node = &nodes->items[index];
    uint32_t i;
    for (i = 0U; i < node->child_count; ++i) {
        const XmlNode *label = &nodes->items[node->children[i]];
        uint32_t j;
        if (!xml_name_is(label, "navLabel")) {
            continue;
        }
        for (j = 0U; j < label->child_count; ++j) {
            if (xml_name_is(&nodes->items[label->children[j]], "text")) {
                return xml_all_text(nodes, label->children[j]);
            }
        }
    }
    return copy_bytes("", 0U);
}

static const char *xml_child_href(const XmlNodeArray *nodes, uint32_t index,
                                  const char *child_name) {
    const XmlNode *node = &nodes->items[index];
    uint32_t i;
    for (i = 0U; i < node->child_count; ++i) {
        const XmlNode *child = &nodes->items[node->children[i]];
        if (xml_name_is(child, child_name) && cstr_nonempty(child->target_href)) {
            return child->target_href;
        }
    }
    return NULL;
}

static bool process_output(NodeList *output, char *title, const char *href,
                           uint64_t source_start, NodeList *children,
                           bool keep_without_href) {
    OutNode *node;
    uint32_t i;
    if (title == NULL) {
        node_list_dispose(children);
        return false;
    }
    if (title[0] == '\0') {
        free(title);
        for (i = 0U; i < children->count; ++i) {
            if (!node_list_append(output, children->items[i])) {
                for (; i < children->count; ++i) {
                    out_node_dispose(children->items[i]);
                }
                free(children->items);
                children->items = NULL;
                children->count = 0U;
                children->capacity = 0U;
                return false;
            }
        }
        free(children->items);
        children->items = NULL;
        children->count = 0U;
        children->capacity = 0U;
        return true;
    }
    if (!cstr_nonempty(href) && children->count == 0U && !keep_without_href) {
        free(title);
        node_list_dispose(children);
        return true;
    }
    node = (OutNode *)calloc(1U, sizeof(*node));
    if (node == NULL) {
        free(title);
        node_list_dispose(children);
        return false;
    }
    node->title = title;
    node->href = cstr_nonempty(href) ? copy_cstr(href) : NULL;
    node->source_start = source_start;
    if (cstr_nonempty(href) && node->href == NULL) {
        out_node_dispose(node);
        node_list_dispose(children);
        return false;
    }
    node->children = children->items;
    node->child_count = children->count;
    children->items = NULL;
    children->count = 0U;
    children->capacity = 0U;
    if (!node_list_append(output, node)) {
        out_node_dispose(node);
        return false;
    }
    return true;
}

static bool process_epub_li(const XmlNodeArray *nodes, uint32_t index, NodeList *output);

static bool collect_li_children(const XmlNodeArray *nodes, uint32_t index,
                                NodeList *output) {
    const XmlNode *node = &nodes->items[index];
    uint32_t i;
    for (i = 0U; i < node->child_count; ++i) {
        const XmlNode *child = &nodes->items[node->children[i]];
        if (xml_name_is(child, "li")) {
            if (!process_epub_li(nodes, node->children[i], output)) {
                return false;
            }
        } else if (!xml_name_is(child, "a") && !xml_name_is(child, "span")) {
            if (!collect_li_children(nodes, node->children[i], output)) {
                return false;
            }
        }
    }
    return true;
}

static bool process_epub_li(const XmlNodeArray *nodes, uint32_t index, NodeList *output) {
    const XmlNode *node = &nodes->items[index];
    uint32_t i;
    uint32_t title_index = UINT32_MAX;
    const char *href = NULL;
    char *title;
    NodeList children = {0};
    for (i = 0U; i < node->child_count; ++i) {
        const XmlNode *child = &nodes->items[node->children[i]];
        if (xml_name_is(child, "a") || xml_name_is(child, "span")) {
            title_index = node->children[i];
            if (xml_name_is(child, "a") && cstr_nonempty(child->target_href)) {
                href = child->target_href;
            }
            break;
        }
    }
    if (!collect_li_children(nodes, index, &children)) {
        node_list_dispose(&children);
        return false;
    }
    title = title_index == UINT32_MAX ? copy_bytes("", 0U) :
            xml_all_text(nodes, title_index);
    return process_output(output, title, href, node->source_start, &children, false);
}

static bool collect_epub_items(const XmlNodeArray *nodes, uint32_t index,
                               NodeList *output) {
    const XmlNode *node = &nodes->items[index];
    uint32_t i;
    for (i = 0U; i < node->child_count; ++i) {
        const XmlNode *child = &nodes->items[node->children[i]];
        if (xml_name_is(child, "li")) {
            if (!process_epub_li(nodes, node->children[i], output)) {
                return false;
            }
        } else if (!xml_name_is(child, "nav")) {
            if (!collect_epub_items(nodes, node->children[i], output)) {
                return false;
            }
        }
    }
    return true;
}

static bool process_ncx_point(const XmlNodeArray *nodes, uint32_t index,
                              NodeList *output) {
    const XmlNode *node = &nodes->items[index];
    NodeList children = {0};
    char *title;
    const char *href = xml_child_href(nodes, index, "content");
    uint32_t i;
    for (i = 0U; i < node->child_count; ++i) {
        if (xml_name_is(&nodes->items[node->children[i]], "navPoint") &&
            !process_ncx_point(nodes, node->children[i], &children)) {
            node_list_dispose(&children);
            return false;
        }
    }
    title = xml_ncx_title(nodes, index);
    return process_output(output, title, href, node->source_start, &children, false);
}

static bool xml_text_has_content(const char *text) {
    size_t at;
    if (text == NULL) {
        return false;
    }
    for (at = 0U; text[at] != '\0'; ++at) {
        if (!ascii_space((unsigned char)text[at])) {
            return true;
        }
    }
    return false;
}

static bool fb2_media_reference(const XmlNode *node) {
    static const char *const media_names[] = {
        "image", "img", "audio", "video", "object", "binary"
    };
    static const char *const reference_names[] = {
        "href", "src", "url"
    };
    uint32_t i;
    uint32_t j;
    bool media = false;
    for (i = 0U; i < sizeof(media_names) / sizeof(media_names[0]); ++i) {
        if (xml_name_is(node, media_names[i])) {
            media = true;
            break;
        }
    }
    if (!media) {
        return false;
    }
    for (i = 0U; i < node->attribute_count; ++i) {
        for (j = 0U; j < sizeof(reference_names) / sizeof(reference_names[0]); ++j) {
            if (cstr_equal(node->attributes[i].name, reference_names[j]) &&
                cstr_nonempty(node->attributes[i].value)) {
                return true;
            }
        }
    }
    return false;
}

static bool fb2_content_exists(const XmlNodeArray *nodes, uint32_t index) {
    const XmlNode *node = &nodes->items[index];
    uint32_t i;
    for (i = 0U; i < node->segment_count; ++i) {
        if (!node->segments[i].is_child &&
            xml_text_has_content(node->segments[i].text)) {
            return true;
        }
    }
    if (fb2_media_reference(node)) {
        return true;
    }
    for (i = 0U; i < node->child_count; ++i) {
        const XmlNode *child = &nodes->items[node->children[i]];
        if (xml_name_is(child, "title") || xml_name_is(child, "section")) {
            continue;
        }
        if (fb2_content_exists(nodes, node->children[i])) {
            return true;
        }
    }
    return false;
}

static bool process_fb2_section(const XmlNodeArray *nodes, uint32_t index,
                                NodeList *output) {
    const XmlNode *node = &nodes->items[index];
    NodeList children = {0};
    char *title;
    uint32_t i;
    for (i = 0U; i < node->child_count; ++i) {
        if (xml_name_is(&nodes->items[node->children[i]], "section") &&
            !process_fb2_section(nodes, node->children[i], &children)) {
            node_list_dispose(&children);
            return false;
        }
    }
    title = xml_direct_title(nodes, index, "title");
    {
        bool body_exists = fb2_content_exists(nodes, index);
        if (!body_exists && children.count == 0U) {
            free(title);
            return true;
        }
        return process_output(output, title, node->target_href, node->source_start,
                              &children, body_exists);
    }
}

static bool flatten_nodes(const NodeList *nodes, int32_t parent, EntryBuilder *builder) {
    uint32_t i;
    for (i = 0U; i < nodes->count; ++i) {
        OutNode *node = nodes->items[i];
        uint32_t output_index = builder->count;
        NodeList children = {node->children, node->child_count, 0U};
        if (!entry_builder_append(builder, node->title, node->href, node->source_start, 0U, 0U,
                                  parent)) {
            return false;
        }
        if (!flatten_nodes(&children, (int32_t)output_index, builder)) {
            return false;
        }
    }
    return true;
}

static ErmaoChapterStatus parse_xml_internal(uint32_t format,
                                             const ErmaoChapterXmlEvent *events,
                                             uint32_t count,
                                             ErmaoChapterResult **result) {
    XmlNodeArray nodes = {0};
    NodeList output = {0};
    EntryBuilder builder = {0};
    uint32_t i;
    bool okay = true;
    if (format != ERMAO_CHAPTER_EPUB_NAV && format != ERMAO_CHAPTER_EPUB_NCX &&
        format != ERMAO_CHAPTER_FB2) {
        return ERMAO_CHAPTER_INVALID_INPUT;
    }
    if (!xml_parse_events(events, count, &nodes)) {
        xml_nodes_dispose(&nodes);
        return ERMAO_CHAPTER_INVALID_INPUT;
    }
    if (format == ERMAO_CHAPTER_EPUB_NAV) {
        for (i = 0U; i < nodes.count; ++i) {
            const char *type = NULL;
            int32_t parent;
            bool nested = false;
            if (!xml_name_is(&nodes.items[i], "nav") ||
                !xml_attribute(&nodes.items[i], "type", &type) ||
                !token_contains_ci(type, "toc")) {
                continue;
            }
            parent = nodes.items[i].parent;
            while (parent >= 0) {
                const char *parent_type = NULL;
                if (xml_name_is(&nodes.items[parent], "nav") &&
                    xml_attribute(&nodes.items[parent], "type", &parent_type) &&
                    token_contains_ci(parent_type, "toc")) {
                    nested = true;
                    break;
                }
                parent = nodes.items[parent].parent;
            }
            if (!nested && !collect_epub_items(&nodes, i, &output)) {
                okay = false;
                break;
            }
        }
    } else if (format == ERMAO_CHAPTER_EPUB_NCX) {
        for (i = 0U; i < nodes.count; ++i) {
            int32_t parent = nodes.items[i].parent;
            if (xml_name_is(&nodes.items[i], "navPoint") &&
                (parent < 0 || !xml_name_is(&nodes.items[parent], "navPoint")) &&
                !process_ncx_point(&nodes, i, &output)) {
                okay = false;
                break;
            }
        }
    } else {
        for (i = 0U; i < nodes.count; ++i) {
            int32_t parent = nodes.items[i].parent;
            bool nested = false;
            if (!xml_name_is(&nodes.items[i], "section")) {
                continue;
            }
            while (parent >= 0) {
                if (xml_name_is(&nodes.items[parent], "section")) {
                    nested = true;
                    break;
                }
                parent = nodes.items[parent].parent;
            }
            if (!nested && !process_fb2_section(&nodes, i, &output)) {
                okay = false;
                break;
            }
        }
    }
    if (!okay || !flatten_nodes(&output, -1, &builder)) {
        entry_builder_dispose(&builder);
        node_list_dispose(&output);
        xml_nodes_dispose(&nodes);
        return ERMAO_CHAPTER_OUT_OF_MEMORY;
    }
    node_list_dispose(&output);
    xml_nodes_dispose(&nodes);
    *result = result_from_builder(&builder, NULL, 0U);
    return *result == NULL ? ERMAO_CHAPTER_OUT_OF_MEMORY : ERMAO_CHAPTER_OK;
}

static bool mobi_validate(const ErmaoChapterMobiNode *nodes, uint32_t count) {
    uint32_t i;
    if (count != 0U && nodes == NULL) {
        return false;
    }
    for (i = 0U; i < count; ++i) {
        int32_t parent = nodes[i].parent_index;
        if (parent < -1 || (parent >= 0 && (uint32_t)parent >= count) ||
            parent == (int32_t)i) {
            return false;
        }
    }
    for (i = 0U; i < count; ++i) {
        uint32_t at = i;
        uint32_t steps = 0U;
        while (nodes[at].parent_index >= 0) {
            at = (uint32_t)nodes[at].parent_index;
            ++steps;
            if (steps > count) {
                return false;
            }
        }
    }
    return true;
}

static void mobi_children_dispose(NodeList *children, uint32_t count) {
    uint32_t i;
    for (i = 0U; i < count; ++i) {
        free(children[i].items);
    }
    free(children);
}

static bool process_mobi_node(const ErmaoChapterMobiNode *nodes, uint32_t index,
                              const NodeList *children_by_node, NodeList *output) {
    NodeList children = {0};
    const char *source_title = nodes[index].title == NULL ? "" : nodes[index].title;
    char *title = trimmed_copy(source_title, strlen(source_title));
    uint32_t i;
    if (title == NULL) {
        return false;
    }
    for (i = 0U; i < children_by_node[index].count; ++i) {
        uint32_t child_index =
            (uint32_t)(uintptr_t)children_by_node[index].items[i];
        if (!process_mobi_node(nodes, child_index, children_by_node, &children)) {
            free(title);
            node_list_dispose(&children);
            return false;
        }
    }
    if (!process_output(output, title, nodes[index].target_href, index, &children, false)) {
        node_list_dispose(&children);
        return false;
    }
    return true;
}

static ErmaoChapterStatus parse_mobi_internal(const ErmaoChapterMobiNode *nodes,
                                              uint32_t count,
                                              ErmaoChapterResult **result) {
    NodeList *children;
    NodeList output = {0};
    EntryBuilder builder = {0};
    uint32_t i;
    if (!mobi_validate(nodes, count)) {
        return ERMAO_CHAPTER_INVALID_INPUT;
    }
    if (count == 0U) {
        *result = result_from_builder(&builder, NULL, 0U);
        return *result == NULL ? ERMAO_CHAPTER_OUT_OF_MEMORY : ERMAO_CHAPTER_OK;
    }
    children = (NodeList *)calloc(count, sizeof(*children));
    if (children == NULL) {
        return ERMAO_CHAPTER_OUT_OF_MEMORY;
    }
    for (i = 0U; i < count; ++i) {
        if (nodes[i].parent_index >= 0 &&
            !node_list_append(&children[nodes[i].parent_index],
                              (OutNode *)(uintptr_t)i)) {
            mobi_children_dispose(children, count);
            return ERMAO_CHAPTER_OUT_OF_MEMORY;
        }
    }
    for (i = 0U; i < count; ++i) {
        if (nodes[i].parent_index < 0 &&
            !process_mobi_node(nodes, i, children, &output)) {
            node_list_dispose(&output);
            mobi_children_dispose(children, count);
            return ERMAO_CHAPTER_OUT_OF_MEMORY;
        }
    }
    mobi_children_dispose(children, count);
    if (!flatten_nodes(&output, -1, &builder)) {
        entry_builder_dispose(&builder);
        node_list_dispose(&output);
        return ERMAO_CHAPTER_OUT_OF_MEMORY;
    }
    node_list_dispose(&output);
    *result = result_from_builder(&builder, NULL, 0U);
    return *result == NULL ? ERMAO_CHAPTER_OUT_OF_MEMORY : ERMAO_CHAPTER_OK;
}

uint32_t ermao_chapters_abi_version(void) {
    return ERMAO_ABI_VERSION;
}

ErmaoChapterStatus ermao_chapters_parse_txt(const uint8_t *utf8, uint64_t length,
                                             ErmaoChapterResult **result) {
    if (result == NULL) {
        return ERMAO_CHAPTER_INVALID_INPUT;
    }
    *result = NULL;
    return parse_txt_internal(utf8, length, result);
}

ErmaoChapterStatus ermao_chapters_parse_xml(uint32_t format,
                                             const ErmaoChapterXmlEvent *events,
                                             uint32_t count,
                                             ErmaoChapterResult **result) {
    if (result == NULL) {
        return ERMAO_CHAPTER_INVALID_INPUT;
    }
    *result = NULL;
    return parse_xml_internal(format, events, count, result);
}

ErmaoChapterStatus ermao_chapters_from_mobi(const ErmaoChapterMobiNode *nodes,
                                             uint32_t count,
                                             ErmaoChapterResult **result) {
    if (result == NULL) {
        return ERMAO_CHAPTER_INVALID_INPUT;
    }
    *result = NULL;
    return parse_mobi_internal(nodes, count, result);
}

uint32_t ermao_chapters_count(const ErmaoChapterResult *result) {
    return result == NULL ? 0U : result->count;
}

uint32_t ermao_chapters_navigable_count(const ErmaoChapterResult *result) {
    return result == NULL ? 0U : result->navigable_count;
}

const ErmaoChapterEntry *ermao_chapters_entry(const ErmaoChapterResult *result,
                                               uint32_t index) {
    if (result == NULL || index >= result->count) {
        return NULL;
    }
    return &result->entries[index];
}

const uint8_t *ermao_chapters_text(const ErmaoChapterResult *result) {
    return result == NULL ? NULL : result->text;
}

uint64_t ermao_chapters_text_length(const ErmaoChapterResult *result) {
    return result == NULL ? 0U : result->text_length;
}

void ermao_chapters_free(ErmaoChapterResult *result) {
    uint32_t i;
    if (result == NULL) {
        return;
    }
    for (i = 0U; i < result->count; ++i) {
        free((char *)result->entries[i].key);
        free((char *)result->entries[i].title);
        free((char *)result->entries[i].href);
    }
    free(result->entries);
    free(result->text);
    free(result);
}
