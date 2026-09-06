package com.ermao.library.features.reader.infrastructure

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.chapter.infrastructure.ChapterCore
import com.ermao.library.chapter.infrastructure.ChapterCoreMobiNode
import com.ermao.library.chapter.infrastructure.ChapterCoreXmlAttribute
import com.ermao.library.chapter.infrastructure.ChapterCoreXmlEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Device-level conformance checks for the JNI boundary around the shared
 * chapter core. These tests deliberately call the public ChapterCore facade;
 * they do not duplicate the native parser or reader publication adapters.
 */
@RunWith(AndroidJUnit4::class)
class ChapterCoreInstrumentedTest {
    @Test
    fun txtFactorySeparatesBodyResourcePathsFromTocAnchors() = kotlinx.coroutines.runBlocking {
        val context = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().targetContext
        val file = java.io.File.createTempFile("chapter-core-", ".txt", context.cacheDir)
        try {
            file.writeText(syntheticTxtWithPrintedContents())
            val publication = TxtReadiumPublicationFactory().open(file, "Test")
            try {
                assertEquals(12, publication.tableOfContents.size)
                assertTrue(publication.readingOrder.all { '#' !in it.href.toString() })
                publication.tableOfContents.forEach { entry ->
                    val path = entry.href.toString().substringBefore('#')
                    val resourceLink = publication.readingOrder.single { it.href.toString() == path }
                    val bytes = requireNotNull(publication.get(resourceLink)).read().getOrNull()
                    val text = requireNotNull(bytes).decodeToString()
                    assertTrue(text.contains("id=\"heading-000001\""))
                }
            } finally {
                publication.close()
            }
            file.writeText("Ordinary body without authored headings.")
            val noToc = TxtReadiumPublicationFactory().open(file, "Test")
            try {
                assertTrue(noToc.tableOfContents.isEmpty())
                val bytes = requireNotNull(noToc.get(noToc.readingOrder.single())).read().getOrNull()
                assertTrue(requireNotNull(bytes).decodeToString().contains("Ordinary body"))
            } finally {
                noToc.close()
            }
        } finally {
            file.delete()
        }
    }

    @Test
    fun txtDropsPrintedTableOfContentsAndKeepsTwelveChapterRanges() {
        val input = syntheticTxtWithPrintedContents()
        val result = ChapterCore.parseTxt(input)
        val normalized = input.replace("\r\n", "\n")

        assertEquals(12, result.entries.size)
        assertEquals(12, result.entries.count { it.navigable })
        result.entries.forEachIndexed { index, entry ->
            assertEquals(index, entry.index)
            assertEquals(null, entry.parentIndex)
            assertEquals("chapter-$index", entry.key)
            assertEquals(
                "text/chapter-${"%04d".format(index + 1)}.xhtml#heading-000001",
                entry.href,
            )
            if (index > 0) {
                assertTrue(result.entries[index - 1].sourceStart < entry.sourceStart)
                assertEquals(entry.sourceStart, result.entries[index - 1].sourceEnd)
            }
        }

        val firstTitle = "Chapter I. Alpha"
        val firstTitleChars = normalized.indexOf(firstTitle)
        val firstTitleEnd = normalized.indexOf('\n', firstTitleChars)
        val secondTitleChars = normalized.indexOf("Chapter II. Beta")
        assertTrue(firstTitleChars >= 0)
        assertEquals(
            normalized.substring(0, firstTitleChars).toByteArray().size.toLong(),
            result.entries.first().sourceStart,
        )
        assertEquals(
            normalized.substring(0, firstTitleEnd + 1).toByteArray().size.toLong(),
            result.entries.first().contentStart,
        )
        assertEquals(
            normalized.substring(0, secondTitleChars).toByteArray().size.toLong(),
            result.entries.first().sourceEnd,
        )
        assertEquals(
            normalized.toByteArray().size.toLong(),
            result.entries.last().sourceEnd,
        )
    }

    @Test
    fun txtWithoutHeadingsReturnsNormalizedBodyInsteadOfSyntheticEntry() {
        val result = ChapterCore.parseTxt("导言\r\nemoji \uD83D\uDE00")

        assertTrue(result.entries.isEmpty())
        assertEquals("导言\nemoji \uD83D\uDE00", result.text)
    }

    @Test
    fun xmlTitleUsesStandardUtf8ForSupplementaryUnicode() {
        val result = ChapterCore.parseXml(
            format = 1,
            events = listOf(
                xmlStart(
                    "nav",
                    attributes = listOf(ChapterCoreXmlAttribute("type", "toc")),
                ),
                xmlStart("ol"),
                xmlStart("li"),
                xmlStart("a", href = "chapter.xhtml"),
                xmlText("Chapter \uD83D\uDE00"),
                xmlEnd("a"),
                xmlEnd("li"),
                xmlEnd("ol"),
                xmlEnd("nav"),
            ),
        )

        assertEquals(1, result.entries.size)
        assertEquals("Chapter \uD83D\uDE00", result.entries.single().title)
        assertEquals("chapter.xhtml", result.entries.single().href)
    }

    @Test
    fun mobiPromotesEmptyTitleParentAndRejectsInvalidParent() {
        val result = ChapterCore.fromMobi(
            listOf(
                ChapterCoreMobiNode(null, "Root", "root.xhtml"),
                ChapterCoreMobiNode(0, "", null),
                ChapterCoreMobiNode(1, "Child", "child.xhtml"),
                ChapterCoreMobiNode(null, "Dropped", null),
            ),
        )

        assertEquals(listOf("Root", "Child"), result.entries.map { it.title })
        assertEquals(listOf(null, 0), result.entries.map { it.parentIndex })
        assertEquals(listOf("chapter-0", "chapter-1"), result.entries.map { it.key })
        assertEquals(listOf("root.xhtml", "child.xhtml"), result.entries.map { it.href })

        val invalidParent = runCatching {
            ChapterCore.fromMobi(
                listOf(ChapterCoreMobiNode(4, "Invalid", "invalid.xhtml")),
            )
        }.exceptionOrNull()
        assertTrue(invalidParent is IllegalArgumentException)
    }

    @Test
    fun mobiAcceptsAForwardParentIndexAndRestoresPreorder() {
        val result = ChapterCore.fromMobi(
            listOf(
                ChapterCoreMobiNode(1, "Child", "child.xhtml"),
                ChapterCoreMobiNode(null, "Root", "root.xhtml"),
            ),
        )

        assertEquals(listOf("Root", "Child"), result.entries.map { it.title })
        assertEquals(listOf(null, 0), result.entries.map { it.parentIndex })
        assertEquals(listOf("chapter-0", "chapter-1"), result.entries.map { it.key })
        assertEquals(listOf("root.xhtml", "child.xhtml"), result.entries.map { it.href })
    }

    private fun syntheticTxtWithPrintedContents(): String = buildString {
        append("Preface\r\n")
        repeat(12) { index ->
            append("Chapter ${roman(index + 1)}.\r\n\r\n")
        }
        repeat(12) { index ->
            append("Chapter ${roman(index + 1)}. ${chapterTitle(index)}\r\n")
            append("Body ${index + 1}\r\n")
        }
    }

    private fun chapterTitle(index: Int): String = when (index) {
        0 -> "Alpha"
        1 -> "Beta"
        else -> "Chapter ${index + 1}"
    }

    private fun roman(value: Int): String = when (value) {
        1 -> "I"
        2 -> "II"
        3 -> "III"
        4 -> "IV"
        5 -> "V"
        6 -> "VI"
        7 -> "VII"
        8 -> "VIII"
        9 -> "IX"
        10 -> "X"
        11 -> "XI"
        12 -> "XII"
        else -> error("unsupported test numeral")
    }

    private fun xmlStart(
        name: String,
        href: String? = null,
        attributes: List<ChapterCoreXmlAttribute> = emptyList(),
    ): ChapterCoreXmlEvent = ChapterCoreXmlEvent(
        kind = START,
        name = name,
        attributes = attributes.toTypedArray(),
        href = href,
    )

    private fun xmlText(value: String): ChapterCoreXmlEvent = ChapterCoreXmlEvent(
        kind = TEXT,
        text = value,
    )

    private fun xmlEnd(name: String): ChapterCoreXmlEvent = ChapterCoreXmlEvent(
        kind = END,
        name = name,
    )

    private companion object {
        const val START = 1
        const val TEXT = 2
        const val END = 3
    }
}
