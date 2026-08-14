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
        "locationJson": '{"engine":"readium","platform":"web","version":"readium-ts:2.8.2","publication":{"originalFileHash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","parser":"epub-package:1","normalization":"shuku-epub-locator-dom-v2"},"payload":{"href":"text/all.xhtml","type":"application/xhtml+xml","locations":{"fragments":["chapter-2"]}}}',
    }

    navigation = progress_navigation(progress, ANCHORED_UNITS)

    assert navigation["currentHref"] == "Text/all.xhtml#chapter-2"
    assert navigation["currentChapterTitle"] == "第二章"
    assert navigation["currentChapterSortOrder"] == 2


def test_progress_navigation_projects_exact_readium_location_for_chapter_detail():
    progress = {
        "percent": 0.2,
        "locationJson": '{"engine":"readium","platform":"android","version":"readium-kotlin:3.3.0","publication":{"originalFileHash":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","parser":"shuku-txt:1","normalization":"shuku-txt-v1"},"payload":{"href":"txt-section:9","type":"application/xhtml+xml","locations":{"cssSelector":"#p-9"},"text":{"highlight":"第9章"}}}',
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
    assert navigation["currentSectionIndex"] is None
    assert navigation["progressExtra"] == {}


def test_progress_navigation_does_not_guess_ambiguous_resource_only_href():
    progress = {
        "percent": 0,
        "locationJson": '{"engine":"readium","platform":"ios","version":"readium-swift:3.8.0","publication":{"originalFileHash":"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","parser":"epub-package:1","normalization":"shuku-epub-locator-dom-v2"},"payload":{"href":"Text/all.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":"#body"}}}',
    }

    navigation = progress_navigation(progress, ANCHORED_UNITS)

    assert navigation["currentHref"] == "Text/all.xhtml"
    assert navigation["currentChapterTitle"] is None
    assert navigation["currentChapterSortOrder"] is None
    assert progress_percent_with_navigation(progress, ANCHORED_UNITS) == 0


def test_progress_navigation_does_not_estimate_mobi_chapter_from_unmatched_exact_href():
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
        "locationJson": '{"engine":"readium","platform":"web","version":"readium-ts:2.8.2","publication":{"originalFileHash":"sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd","parser":"libmobi:0.12@test","normalization":"ermao-mobi-core-v1+shuku-locator-dom-v2"},"payload":{"href":"missing.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":"#missing"}}}',
    }

    navigation = progress_navigation(progress, units)

    assert navigation["currentHref"] == "missing.xhtml"
    assert navigation["currentChapterTitle"] is None
    assert navigation["currentChapterSortOrder"] is None
    assert navigation["progressEstimated"] is False


def test_progress_navigation_does_not_accept_non_readium_location_shape():
    progress = {
        "percent": 42.5,
        "locationJson": '{"type":"reflowable","format":"epub","legacyRenderer":{"toc":{"navigationKey":"epub:chapter-2","index":1,"title":"Exact chapter"}}}',
    }
    units = [
        {**unit, "navigationKey": f"epub:chapter-{index + 1}"}
        for index, unit in enumerate(ANCHORED_UNITS)
    ]

    navigation = progress_navigation(progress, units)

    assert navigation["currentChapterTitle"] is None
    assert navigation["currentChapterSortOrder"] is None
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
        "locationJson": '{"engine":"readium","platform":"web","version":"readium-ts:2.8.2","publication":{"originalFileHash":"sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee","parser":"epub-package:1","normalization":"shuku-epub-locator-dom-v2"},"payload":{"href":"Text/all.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":"#body"}}}',
    }

    navigation = progress_navigation(progress, ANCHORED_UNITS)

    assert navigation["currentHref"] == "Text/all.xhtml"
    assert navigation["currentChapterSortOrder"] is None


def test_progress_navigation_uses_exact_reading_order_position_for_split_resources():
    progress = {
        "percent": 15.2,
        "locationJson": '{"kind":"reflowable","publication":{"originalFileHash":"sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff","parser":"epub-package:1","normalization":"shuku-epub-locator-dom-v2"},"engineLocator":{"engine":"readium","platform":"web","version":"readium-ts:2.8.2","payload":{"href":"text/part0008_split_001.html","locations":{"position":11,"progression":0.5}}}}',
    }
    units = [
        {
            "href": "text/part0003.html",
            "title": "第一部",
            "sortOrder": 1,
            "metadataJson": {"readingOrderPosition": 3},
        },
        {
            "href": "text/part0008_split_000.html",
            "title": "第四部 事件",
            "sortOrder": 4,
            "metadataJson": {"readingOrderPosition": 10},
        },
        {
            "href": "text/part0009.html",
            "title": "第五部",
            "sortOrder": 5,
            "metadataJson": {"readingOrderPosition": 13},
        },
    ]

    navigation = progress_navigation(progress, units)

    assert navigation["currentChapterIndex"] == 1
    assert navigation["currentChapterTitle"] == "第四部 事件"
    assert navigation["currentChapterSortOrder"] == 4


def test_progress_navigation_does_not_guess_between_anchors_at_one_position():
    progress = {
        "percent": 15.2,
        "locationJson": '{"engine":"readium","payload":{"href":"text/all.xhtml","locations":{"position":4}}}',
    }
    units = [
        {
            "href": "text/all.xhtml#one",
            "title": "第一章",
            "sortOrder": 0,
            "metadataJson": {"readingOrderPosition": 4},
        },
        {
            "href": "text/all.xhtml#two",
            "title": "第二章",
            "sortOrder": 1,
            "metadataJson": {"readingOrderPosition": 4},
        },
    ]

    navigation = progress_navigation(progress, units)

    assert navigation["currentChapterIndex"] is None
    assert navigation["currentChapterTitle"] is None
