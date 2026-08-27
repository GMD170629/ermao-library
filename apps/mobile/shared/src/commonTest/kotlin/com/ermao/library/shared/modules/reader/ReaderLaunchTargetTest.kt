package com.ermao.library.shared.modules.reader

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ReaderLaunchTargetTest {
    @Test fun fragmentNavigationRequiresRecapturedAnchorEvidence() {
        assertFalse(matchesReaderNavigationHref("chapter.xhtml", "chapter.xhtml#p2", emptySet(), "#p1"))
        assertTrue(matchesReaderNavigationHref("./chapter.xhtml", "chapter.xhtml#p2", setOf("p2"), null))
        assertTrue(matchesReaderNavigationHref("chapter.xhtml", "chapter.xhtml#p2", emptySet(), "#p2 > span"))
        assertFalse(matchesReaderNavigationHref("other.xhtml", "chapter.xhtml#p2", setOf("p2"), "#p2"))
        assertFalse(matchesReaderNavigationHref("chapter.xhtml", "chapter.xhtml#p2", emptySet(), "#p20"))
    }
    @Test fun reflowableUsesServerHref() {
        assertEquals(ReaderNavigationTargetReflowable("Text/chapter.xhtml#p2"), readingUnitLaunchTarget("reflowable", "Text/chapter.xhtml#p2", null))
    }

    @Test fun pdfUsesOneBasedServerPageNumber() {
        assertEquals(ReaderNavigationTargetPdf(11), readingUnitLaunchTarget("pdf", null, 12))
    }

    @Test fun comicRequiresBothPageAndResourceHref() {
        assertIs<ReaderNavigationTargetInvalid>(readingUnitLaunchTarget("comic", null, 3))
        assertEquals(ReaderNavigationTargetComic(2, "page/003.jpg"), readingUnitLaunchTarget("comic", "page/003.jpg", 3))
    }

    @Test fun malformedExplicitPayloadStaysExplicitlyInvalid() {
        assertIs<ReaderNavigationTargetInvalid>(decodeReaderLaunchTarget("{broken"))
        assertEquals(null, decodeReaderLaunchTarget(null))
    }

    @Test fun invalidDecodedPageCannotBecomeAResumeRequest() {
        assertIs<ReaderNavigationTargetInvalid>(decodeReaderLaunchTarget(encodeReaderLaunchTarget(ReaderNavigationTargetPdf(-1))))
        assertIs<ReaderNavigationTargetInvalid>(decodeReaderLaunchTarget(encodeReaderLaunchTarget(ReaderNavigationTargetReflowable(""))))
    }
}
