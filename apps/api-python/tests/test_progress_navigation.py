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
    progress = {"percent": 12, "extra": '{"currentHref":"text/all.xhtml#chapter-2"}'}

    navigation = progress_navigation(progress, ANCHORED_UNITS)

    assert navigation["currentHref"] == "Text/all.xhtml#chapter-2"
    assert navigation["currentChapterTitle"] == "第二章"
    assert navigation["currentChapterSortOrder"] == 2


def test_progress_navigation_does_not_guess_ambiguous_resource_only_href():
    progress = {
        "percent": 0,
        "extra": '{"currentHref":"Text/all.xhtml","sectionIndex":0}',
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
        "extra": '{"cfi":"epubcfi(/6/14!/4/4,/86,/128/1:134)","currentHref":null,"progression":0.11201454819672686,"sourceFormat":"mobi"}',
    }

    navigation = progress_navigation(progress, units)

    assert navigation["currentHref"] is None
    assert navigation["currentChapterTitle"] is None
    assert navigation["currentChapterSortOrder"] is None
    assert navigation["progressEstimated"] is False


def test_progress_navigation_uses_foliate_toc_index_without_section_guessing():
    progress = {
        "percent": 42.5,
        "extra": '{"navigationKey":"epub:chapter-2","chapterIndex":1,"chapterTitle":"Exact chapter","sectionIndex":8,"sectionTotal":12,"locationCurrent":41,"locationNext":43,"locationTotal":100}',
    }
    units = [
        {**unit, "navigationKey": f"epub:chapter-{index + 1}"}
        for index, unit in enumerate(ANCHORED_UNITS)
    ]

    navigation = progress_navigation(progress, units)

    assert navigation["currentChapterTitle"] == ANCHORED_UNITS[1]["title"]
    assert navigation["currentChapterSortOrder"] == 2
    assert navigation["progressEstimated"] is False


def test_progress_navigation_rejects_stale_navigation_fingerprint():
    units = [
        {**unit, "navigationKey": f"epub:chapter-{index + 1}"}
        for index, unit in enumerate(ANCHORED_UNITS)
    ]
    progress = {
        "percent": 50,
        "extra": '{"navigationKey":"epub:chapter-2","navigationFingerprint":"old"}',
    }

    navigation = progress_navigation(progress, units, navigation_fingerprint="new")

    assert navigation["currentChapterTitle"] is None
    assert navigation["currentChapterSortOrder"] is None


def test_progress_navigation_does_not_override_unmatched_href_with_percent():
    progress = {"percent": 50, "extra": '{"currentHref":"Text/all.xhtml"}'}

    navigation = progress_navigation(progress, ANCHORED_UNITS)

    assert navigation["currentHref"] == "Text/all.xhtml"
    assert navigation["currentChapterSortOrder"] is None
