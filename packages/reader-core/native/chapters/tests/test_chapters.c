#include "ermao_chapters.h"

#include <stdio.h>
#include <string.h>

static int failures = 0;

#define CHECK(condition)                                                        \
    do {                                                                        \
        if (!(condition)) {                                                     \
            fprintf(stderr, "check failed at %s:%d: %s\n", __FILE__, __LINE__,  \
                    #condition);                                               \
            ++failures;                                                         \
        }                                                                       \
    } while (0)

static void test_txt(void) {
    const char input[] =
        "前言\r\nChapter\tIV\r\nA standalone title\r\n\r\n正文\r"
        "\nChapter 2: Two\r\nsecond body";
    const char expected_text[] =
        "前言\nChapter\tIV\nA standalone title\n\n正文\nChapter 2: Two\nsecond body";
    ErmaoChapterResult *result = NULL;
    const ErmaoChapterEntry *first;
    const ErmaoChapterEntry *second;
    ErmaoChapterStatus status = ermao_chapters_parse_txt(
        (const uint8_t *)input, (uint64_t)strlen(input), &result);
    CHECK(status == ERMAO_CHAPTER_OK);
    CHECK(result != NULL);
    CHECK(ermao_chapters_count(result) == 2U);
    CHECK(ermao_chapters_navigable_count(result) == 2U);
    CHECK(ermao_chapters_text_length(result) == (uint64_t)strlen(expected_text));
    CHECK(memcmp(ermao_chapters_text(result), expected_text, strlen(expected_text)) == 0);
    first = ermao_chapters_entry(result, 0U);
    second = ermao_chapters_entry(result, 1U);
    CHECK(first != NULL && second != NULL);
    CHECK(first != NULL && strcmp(first->title, "Chapter\tIV A standalone title") == 0);
    CHECK(first != NULL && first->source_start == strlen("前言\n"));
    CHECK(first != NULL && first->content_start == strlen("前言\nChapter\tIV\nA standalone title\n"));
    CHECK(first != NULL && strcmp(first->href,
                                  "text/chapter-0001.xhtml#heading-000001") == 0);
    CHECK(second != NULL && second->source_start > first->source_start);
    CHECK(second != NULL && strcmp(second->key, "chapter-1") == 0);
    ermao_chapters_free(result);
}

static void test_txt_without_headings(void) {
    const char input[] = "plain\rtext\u2028without headings";
    const char expected[] = "plain\ntext\nwithout headings";
    ErmaoChapterResult *result = NULL;
    CHECK( ermao_chapters_parse_txt((const uint8_t *)input, strlen(input), &result) ==
           ERMAO_CHAPTER_OK);
    CHECK(result != NULL && ermao_chapters_count(result) == 0U);
    CHECK(result != NULL && ermao_chapters_text_length(result) == strlen(expected));
    CHECK(result != NULL && memcmp(ermao_chapters_text(result), expected, strlen(expected)) == 0);
    ermao_chapters_free(result);
}

static void test_txt_leading_sequence_and_chinese_digits(void) {
    const char toc_and_book[] =
        "Chapter 1\n\nChapter 2\n\nChapter 3\n\n"
        "Chapter 1\nbody one\nChapter 2\nbody two\nChapter 3\nbody three";
    const char chinese[] = "第1章\n一\n第１２章：二\n二\n";
    const char spaced_chinese[] =
        "序言\n第 1 章 书库星舰\n正文\n第\t２\t节\t下一节\n内容";
    const char invalid_spaced_chinese[] =
        "第 章\n正文\n第 1 2 章\n正文\n第 1 题\n正文";
    ErmaoChapterResult *result = NULL;
    const ErmaoChapterEntry *entry;
    const ErmaoChapterEntry *second_entry;
    CHECK(ermao_chapters_parse_txt((const uint8_t *)toc_and_book,
                                   strlen(toc_and_book), &result) == ERMAO_CHAPTER_OK);
    CHECK(result != NULL && ermao_chapters_count(result) == 3U);
    entry = ermao_chapters_entry(result, 0U);
    CHECK(entry != NULL && strcmp(entry->title, "Chapter 1") == 0);
    ermao_chapters_free(result);
    result = NULL;
    CHECK(ermao_chapters_parse_txt((const uint8_t *)chinese, strlen(chinese), &result) ==
          ERMAO_CHAPTER_OK);
    CHECK(result != NULL && ermao_chapters_count(result) == 2U);
    ermao_chapters_free(result);
    result = NULL;
    CHECK(ermao_chapters_parse_txt((const uint8_t *)spaced_chinese,
                                   strlen(spaced_chinese), &result) == ERMAO_CHAPTER_OK);
    CHECK(result != NULL && ermao_chapters_count(result) == 2U);
    CHECK(result != NULL && ermao_chapters_navigable_count(result) == 2U);
    CHECK(result != NULL && ermao_chapters_text_length(result) == strlen(spaced_chinese));
    CHECK(result != NULL && memcmp(ermao_chapters_text(result), spaced_chinese,
                                   strlen(spaced_chinese)) == 0);
    entry = ermao_chapters_entry(result, 0U);
    second_entry = ermao_chapters_entry(result, 1U);
    CHECK(entry != NULL && strcmp(entry->title, "第 1 章 书库星舰") == 0);
    CHECK(entry != NULL && entry->source_start == strlen("序言\n"));
    CHECK(entry != NULL && entry->source_end == strlen("序言\n第 1 章 书库星舰\n正文\n"));
    CHECK(entry != NULL && entry->content_start == strlen("序言\n第 1 章 书库星舰\n"));
    CHECK(second_entry != NULL && strcmp(second_entry->title, "第\t２\t节\t下一节") == 0);
    CHECK(second_entry != NULL && second_entry->source_start ==
          strlen("序言\n第 1 章 书库星舰\n正文\n"));
    CHECK(second_entry != NULL && second_entry->content_start ==
          strlen("序言\n第 1 章 书库星舰\n正文\n第\t２\t节\t下一节\n"));
    ermao_chapters_free(result);
    result = NULL;
    CHECK(ermao_chapters_parse_txt((const uint8_t *)invalid_spaced_chinese,
                                   strlen(invalid_spaced_chinese), &result) == ERMAO_CHAPTER_OK);
    CHECK(result != NULL && ermao_chapters_count(result) == 0U);
    ermao_chapters_free(result);
}

static void test_txt_bare_punctuation_heading(void) {
    const char input[] = "CHAPTER I.\nDown the Rabbit-Hole\n\nAlice body";
    ErmaoChapterResult *result = NULL;
    const ErmaoChapterEntry *entry;
    CHECK(ermao_chapters_parse_txt((const uint8_t *)input, strlen(input), &result) ==
          ERMAO_CHAPTER_OK);
    CHECK(result != NULL && ermao_chapters_count(result) == 1U);
    entry = ermao_chapters_entry(result, 0U);
    CHECK(entry != NULL && strcmp(entry->title, "CHAPTER I. Down the Rabbit-Hole") == 0);
    ermao_chapters_free(result);
}

static void test_epub_nav(void) {
    static const ErmaoChapterAttribute attrs[] = {{"type", "toc"}};
    static const ErmaoChapterXmlEvent events[] = {
        {ERMAO_CHAPTER_XML_START, "nav", NULL, attrs, 1U, NULL},
        {ERMAO_CHAPTER_XML_START, "ol", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "li", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "a", NULL, NULL, 0U, "OEBPS/c1.xhtml#one"},
        {ERMAO_CHAPTER_XML_TEXT, NULL, " One ", NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "a", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "ol", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "li", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "a", NULL, NULL, 0U, "OEBPS/c2.xhtml"},
        {ERMAO_CHAPTER_XML_TEXT, NULL, "Child", NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "a", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "li", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "ol", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "li", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "ol", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "nav", NULL, NULL, 0U, NULL},
    };
    ErmaoChapterResult *result = NULL;
    const ErmaoChapterEntry *first;
    const ErmaoChapterEntry *child;
    CHECK(ermao_chapters_parse_xml(ERMAO_CHAPTER_EPUB_NAV, events,
                                   (uint32_t)(sizeof(events) / sizeof(events[0])),
                                   &result) == ERMAO_CHAPTER_OK);
    CHECK(result != NULL && ermao_chapters_count(result) == 2U);
    first = ermao_chapters_entry(result, 0U);
    child = ermao_chapters_entry(result, 1U);
    CHECK(first != NULL && strcmp(first->title, "One") == 0 && first->parent_index == -1);
    CHECK(child != NULL && strcmp(child->title, "Child") == 0 && child->parent_index == 0);
    CHECK(child != NULL && child->source_start == 5U);
    ermao_chapters_free(result);
}

static void test_xml_inline_text_order(void) {
    static const ErmaoChapterAttribute attrs[] = {{"type", "toc"}};
    static const ErmaoChapterXmlEvent events[] = {
        {ERMAO_CHAPTER_XML_START, "nav", NULL, attrs, 1U, NULL},
        {ERMAO_CHAPTER_XML_START, "li", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "a", NULL, NULL, 0U, "inline.xhtml"},
        {ERMAO_CHAPTER_XML_TEXT, NULL, "A", NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "strong", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_TEXT, NULL, "B", NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "strong", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_TEXT, NULL, "C", NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "a", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "li", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "nav", NULL, NULL, 0U, NULL},
    };
    ErmaoChapterResult *result = NULL;
    const ErmaoChapterEntry *entry;
    CHECK(ermao_chapters_parse_xml(ERMAO_CHAPTER_EPUB_NAV, events,
                                   (uint32_t)(sizeof(events) / sizeof(events[0])),
                                   &result) == ERMAO_CHAPTER_OK);
    entry = ermao_chapters_entry(result, 0U);
    CHECK(entry != NULL && strcmp(entry->title, "ABC") == 0);
    ermao_chapters_free(result);
}

static void test_ncx_and_fb2(void) {
    static const ErmaoChapterXmlEvent ncx[] = {
        {ERMAO_CHAPTER_XML_START, "navPoint", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "navLabel", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "text", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_TEXT, NULL, "Root", NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "text", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "navLabel", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "content", NULL, NULL, 0U, "c.xhtml"},
        {ERMAO_CHAPTER_XML_END, "content", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "navPoint", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "navLabel", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "text", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_TEXT, NULL, "Child", NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "text", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "navLabel", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "content", NULL, NULL, 0U, "c2.xhtml"},
        {ERMAO_CHAPTER_XML_END, "content", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "navPoint", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "navPoint", NULL, NULL, 0U, NULL},
    };
    static const ErmaoChapterXmlEvent fb2[] = {
        {ERMAO_CHAPTER_XML_START, "FictionBook", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "section", NULL, NULL, 0U, "fb2/section-0001.xhtml#chapter-node-1"},
        {ERMAO_CHAPTER_XML_START, "title", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_TEXT, NULL, " Part ", NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "em", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_TEXT, NULL, "One", NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "em", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_TEXT, NULL, " ", NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "title", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "p", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_TEXT, NULL, "body", NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "p", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "section", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "title", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_TEXT, NULL, "Child", NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "title", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_START, "p", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_TEXT, NULL, "child body", NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "p", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "section", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "section", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "FictionBook", NULL, NULL, 0U, NULL},
    };
    ErmaoChapterResult *result = NULL;
    const ErmaoChapterEntry *entry;
    CHECK(ermao_chapters_parse_xml(ERMAO_CHAPTER_EPUB_NCX, ncx,
                                   (uint32_t)(sizeof(ncx) / sizeof(ncx[0])),
                                   &result) == ERMAO_CHAPTER_OK);
    CHECK(result != NULL && ermao_chapters_count(result) == 2U);
    entry = ermao_chapters_entry(result, 1U);
    CHECK(entry != NULL && entry->parent_index == 0 && strcmp(entry->title, "Child") == 0);
    ermao_chapters_free(result);
    result = NULL;
    CHECK(ermao_chapters_parse_xml(ERMAO_CHAPTER_FB2, fb2,
                                   (uint32_t)(sizeof(fb2) / sizeof(fb2[0])),
                                   &result) == ERMAO_CHAPTER_OK);
    CHECK(result != NULL && ermao_chapters_count(result) == 2U);
    entry = ermao_chapters_entry(result, 0U);
    CHECK(entry != NULL && strcmp(entry->title, "Part One") == 0);
    CHECK(entry != NULL && entry->href != NULL &&
          strcmp(entry->href, "fb2/section-0001.xhtml#chapter-node-1") == 0);
    ermao_chapters_free(result);
}

static void test_xml_malformed(void) {
    static const ErmaoChapterAttribute attrs[] = {{"type", "toc"}};
    static const ErmaoChapterXmlEvent events[] = {
        {ERMAO_CHAPTER_XML_START, "nav", NULL, attrs, 1U, NULL},
        {ERMAO_CHAPTER_XML_START, "li", NULL, NULL, 0U, NULL},
        {ERMAO_CHAPTER_XML_END, "nav", NULL, NULL, 0U, NULL},
    };
    ErmaoChapterResult *result = NULL;
    CHECK(ermao_chapters_parse_xml(ERMAO_CHAPTER_EPUB_NAV, events,
                                   (uint32_t)(sizeof(events) / sizeof(events[0])),
                                   &result) == ERMAO_CHAPTER_INVALID_INPUT);
    CHECK(result == NULL);
}

static void test_mobi(void) {
    static const ErmaoChapterMobiNode nodes[] = {
        {-1, "Root", "root.xhtml"},
        {0, "", NULL},
        {1, "Child", "child.xhtml"},
        {-1, "Dropped", NULL},
    };
    static const ErmaoChapterMobiNode invalid[] = {
        {1, "A", "a"},
        {0, "B", "b"},
    };
    static const ErmaoChapterMobiNode forward_parent[] = {
        {1, "Child", "child.xhtml"},
        {-1, "Root", "root.xhtml"},
    };
    ErmaoChapterResult *result = NULL;
    const ErmaoChapterEntry *entry;
    CHECK(ermao_chapters_from_mobi(nodes, 4U, &result) == ERMAO_CHAPTER_OK);
    CHECK(result != NULL && ermao_chapters_count(result) == 2U);
    entry = ermao_chapters_entry(result, 1U);
    CHECK(entry != NULL && entry->parent_index == 0 && strcmp(entry->key, "chapter-1") == 0);
    ermao_chapters_free(result);
    result = NULL;
    CHECK(ermao_chapters_from_mobi(invalid, 2U, &result) == ERMAO_CHAPTER_INVALID_INPUT);
    CHECK(result == NULL);
    result = NULL;
    CHECK(ermao_chapters_from_mobi(forward_parent, 2U, &result) == ERMAO_CHAPTER_OK);
    CHECK(result != NULL && ermao_chapters_count(result) == 2U);
    entry = ermao_chapters_entry(result, 0U);
    CHECK(entry != NULL && entry->parent_index == -1 && strcmp(entry->title, "Root") == 0);
    entry = ermao_chapters_entry(result, 1U);
    CHECK(entry != NULL && entry->parent_index == 0 && strcmp(entry->title, "Child") == 0);
    ermao_chapters_free(result);
}

int main(void) {
    CHECK(ermao_chapters_abi_version() == 1U);
    test_txt();
    test_txt_without_headings();
    test_txt_leading_sequence_and_chinese_digits();
    test_txt_bare_punctuation_heading();
    test_epub_nav();
    test_xml_inline_text_order();
    test_ncx_and_fb2();
    test_xml_malformed();
    test_mobi();
    if (failures != 0) {
        fprintf(stderr, "%d test checks failed\n", failures);
        return 1;
    }
    puts("ermao_chapters tests passed");
    return 0;
}
