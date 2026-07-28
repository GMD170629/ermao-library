from app.modules.reader.public import progress_navigation, progress_percent_with_navigation


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
    progress = {"percent": 0, "extra": '{"currentHref":"Text/all.xhtml","sectionIndex":0}'}

    navigation = progress_navigation(progress, ANCHORED_UNITS)

    assert navigation["currentHref"] == "Text/all.xhtml"
    assert navigation["currentChapterTitle"] is None
    assert navigation["currentChapterSortOrder"] is None
    assert progress_percent_with_navigation(progress, ANCHORED_UNITS) == 0
