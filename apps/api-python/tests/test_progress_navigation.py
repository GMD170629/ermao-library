from app.modules.reader.public import (
    progress_navigation,
    progress_percent_with_navigation,
)

ANCHORED_UNITS = [
    {"href": "Text/all.xhtml#chapter-1", "title": "第一章", "sortOrder": 1},
    {"href": "Text/all.xhtml#chapter-2", "title": "第二章", "sortOrder": 2},
    {"href": "Text/all.xhtml#chapter-3", "title": "第三章", "sortOrder": 3},
]


def test_progress_navigation_preserves_exact_fragment_for_shared_xhtml_resource():
    progress = {
        "percent": 12,
        "locationJson": '{"type":"reflowable","format":"epub","href":"text/all.xhtml#chapter-2"}',
    }

    navigation = progress_navigation(progress, ANCHORED_UNITS)

    assert navigation["currentHref"] == "Text/all.xhtml#chapter-2"
    assert navigation["currentChapterTitle"] == "第二章"
    assert navigation["currentChapterSortOrder"] == 2


def test_progress_navigation_projects_reader_v3_location_for_chapter_detail():
    progress = {
        "percent": 0.2,
        "locationJson": '{"type":"reflowable","format":"txt","href":"txt-section:9","foliate":{"toc":{"index":9,"title":"第9章","href":"txt-section:9","navigationKey":"unit-9"},"section":{"current":9,"total":2000}}}',
    }
    units = [
        {
            "id": f"unit-{index}",
            "href": f"txt-section:{index}",
            "title": f"第{index}章",
            "sortOrder": index,
        }
        for index in range(12)
    ]

    navigation = progress_navigation(progress, units)

    assert navigation["currentHref"] == "txt-section:9"
    assert navigation["currentChapterTitle"] == "第9章"
    assert navigation["currentChapterSortOrder"] == 9
    assert navigation["currentChapterIndex"] == 9
    assert navigation["currentSectionIndex"] == 9
    assert navigation["progressExtra"] == {}


def test_progress_navigation_does_not_guess_ambiguous_resource_only_href():
    progress = {
        "percent": 0,
        "locationJson": '{"type":"reflowable","format":"epub","href":"Text/all.xhtml","foliate":{"section":{"current":0}}}',
    }

    navigation = progress_navigation(progress, ANCHORED_UNITS)

    assert navigation["currentHref"] == "Text/all.xhtml"
    assert navigation["currentChapterTitle"] is None
    assert navigation["currentChapterSortOrder"] is None
    assert progress_percent_with_navigation(progress, ANCHORED_UNITS) == 0


def test_progress_navigation_does_not_estimate_mobi_chapter_without_exact_navigation():
    units = [
        {
            "href": f"filepos:{index * 100}",
            "title": f"章{index}",
            "sortOrder": index,
            "navigationKey": f"mobi:{index}",
        }
        for index in range(38)
    ]
    progress = {
        "percent": 11.201454819672687,
        "locationJson": '{"type":"reflowable","format":"mobi","cfi":"epubcfi(/6/14!/4/4,/86,/128/1:134)","progression":0.11201454819672686}',
    }

    navigation = progress_navigation(progress, units)

    assert navigation["currentHref"] is None
    assert navigation["currentChapterTitle"] is None
    assert navigation["currentChapterSortOrder"] is None
    assert navigation["progressEstimated"] is False


def test_progress_navigation_uses_foliate_toc_index_without_section_guessing():
    progress = {
        "percent": 42.5,
        "locationJson": '{"type":"reflowable","format":"epub","foliate":{"toc":{"navigationKey":"epub:chapter-2","index":1,"title":"Exact chapter"},"section":{"current":8,"total":12},"location":{"current":41,"next":43,"total":100}}}',
    }
    units = [
        {**unit, "navigationKey": f"epub:chapter-{index + 1}"}
        for index, unit in enumerate(ANCHORED_UNITS)
    ]

    navigation = progress_navigation(progress, units)

    assert navigation["currentChapterTitle"] == ANCHORED_UNITS[1]["title"]
    assert navigation["currentChapterSortOrder"] == 2
    assert navigation["progressEstimated"] is False


def test_progress_navigation_ignores_removed_legacy_extra_fields():
    units = [
        {**unit, "navigationKey": f"epub:chapter-{index + 1}"}
        for index, unit in enumerate(ANCHORED_UNITS)
    ]
    progress = {
        "percent": 50,
        "extra": '{"navigationKey":"epub:chapter-2","navigationFingerprint":"old"}',
        "locationJson": '{"type":"reflowable","format":"epub","progression":0.5}',
    }

    navigation = progress_navigation(progress, units)

    assert navigation["currentChapterTitle"] is None
    assert navigation["currentChapterSortOrder"] is None


def test_progress_navigation_does_not_override_unmatched_href_with_percent():
    progress = {
        "percent": 50,
        "locationJson": '{"type":"reflowable","format":"epub","href":"Text/all.xhtml"}',
    }

    navigation = progress_navigation(progress, ANCHORED_UNITS)

    assert navigation["currentHref"] == "Text/all.xhtml"
    assert navigation["currentChapterSortOrder"] is None
