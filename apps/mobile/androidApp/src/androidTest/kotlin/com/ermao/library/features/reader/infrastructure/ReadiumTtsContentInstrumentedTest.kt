package com.ermao.library.features.reader.infrastructure

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.mobi.infrastructure.MobiReadiumPublicationFactory
import java.io.File
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.readium.r2.shared.ExperimentalReadiumApi
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.publication.services.content.Content
import org.readium.r2.shared.publication.services.content.content
import org.readium.r2.shared.util.Try
import org.readium.r2.shared.util.Url
import org.readium.r2.shared.util.data.Container
import org.readium.r2.shared.util.data.ReadError
import org.readium.r2.shared.util.resource.InMemoryResource
import org.readium.r2.shared.util.resource.Resource

/** Exercises the same in-memory Publications consumed by the native Reader, without synthesis. */
@OptIn(ExperimentalReadiumApi::class)
@RunWith(AndroidJUnit4::class)
class ReadiumTtsContentInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()

    @Test
    fun txtContentPreservesUnicodeAndResumesFromAnEmittedParagraphLocator() = runBlocking {
        val first = "第一段中文，包含 emoji 😀 和 e\u0301。"
        val second = "Second paragraph. Another sentence in the same paragraph."
        withOriginal("txt", "$first\n\n$second".encodeToByteArray()) { file ->
            val publication = TxtReadiumPublicationFactory().open(file, "TTS fixture")
            try {
                val elements = textElements(publication)
                assertEquals(listOf("TTS fixture", first, second), elements.map { it.text })
                assertReadingOrderLocators(publication, elements)
                val resumed = checkNotNull(publication.content(elements.last().locator)).iterator()
                assertTrue(resumed.hasNext())
                assertEquals(second, (resumed.next() as Content.TextElement).text)
            } finally {
                publication.close()
            }
        }
    }

    @Test
    fun fb2ContentTraversesTheExistingReadingOrderAndKeepsMarkupAsText() = runBlocking {
        val xml = """
            <?xml version="1.0" encoding="UTF-8"?>
            <FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
              <description><title-info><book-title>TTS fixture</book-title><lang>zh</lang></title-info></description>
              <body>
                <section><title><p>第一章</p></title><p>中文<strong>正文</strong> 😀。</p></section>
                <section><title><p>Second chapter</p></title><p>Final paragraph.</p></section>
              </body>
            </FictionBook>
        """.trimIndent()
        withOriginal("fb2", xml.encodeToByteArray()) { file ->
            val publication = Fb2ReadiumPublicationFactory().open(file, "TTS fixture")
            try {
                val elements = textElements(publication)
                val text = elements.joinToString("\n") { it.text }
                assertTrue(text.contains("中文正文 😀。"))
                assertTrue(text.contains("Final paragraph."))
                assertFalse(text.contains("<strong>"))
                assertReadingOrderLocators(publication, elements)
                assertEquals(
                    publication.readingOrder.map { it.href.toString() },
                    elements.map { it.locator.href.toString() }.distinct(),
                )
            } finally {
                publication.close()
            }
        }
    }

    @Test
    fun mobiContentUsesTheSameSecurityDecoratedLazyContainer() = runBlocking {
        val original = instrumentation.context.assets.open("01-basic-mobi6.mobi").use { it.readBytes() }
        withOriginal("mobi", original) { file ->
            val opened = MobiReadiumPublicationFactory().open(file, EpubContentSecurityPolicy::applyMobi)
            try {
                val elements = textElements(opened.publication)
                assertTrue(elements.any { it.text.isNotBlank() })
                assertReadingOrderLocators(opened.publication, elements)
            } finally {
                opened.publication.close()
            }
        }
    }

    @Test
    fun firstMobiElementUsesFinalTransformedBytesWithoutReadingLaterResources() = runBlocking {
        val original = instrumentation.context.assets.open("test.azw3").use { it.readBytes() }
        withOriginal("azw3", original) { file ->
            lateinit var probe: FirstResourceProbeContainer
            val opened = MobiReadiumPublicationFactory().open(file) { container ->
                FirstResourceProbeContainer(EpubContentSecurityPolicy.applyMobi(container))
                    .also { probe = it }
            }
            try {
                assertTrue("Fixture must have later resources", opened.publication.readingOrder.size > 1)
                val first = opened.publication.readingOrder.first().url()
                probe.firstHref = first
                assertTrue(probe.readHrefs.isEmpty())

                val iterator = checkNotNull(opened.publication.content()).iterator()
                assertTrue(iterator.hasNext())
                val element = iterator.next() as Content.TextElement

                assertEquals(FirstResourceProbeContainer.CANARY, element.text)
                assertEquals(first, element.locator.href)
                assertEquals(listOf(first), probe.readHrefs)
            } finally {
                opened.publication.close()
            }
        }
    }

    /** A distinct final-container body proves extraction did not fall back to the raw MOBI bytes. */
    private class FirstResourceProbeContainer(
        private val delegate: Container<Resource>,
    ) : Container<Resource> {
        var firstHref: Url? = null
        val readHrefs = mutableListOf<Url>()
        override val entries: Set<Url> get() = delegate.entries

        override fun get(url: Url): Resource? {
            val resource = if (url == firstHref) {
                InMemoryResource("<html><body><p>$CANARY</p></body></html>".encodeToByteArray())
            } else {
                delegate[url] ?: return null
            }
            return object : Resource by resource {
                override suspend fun read(range: LongRange?): Try<ByteArray, ReadError> {
                    readHrefs += url
                    return resource.read(range)
                }
            }
        }

        override fun close() = delegate.close()

        companion object {
            const val CANARY = "TTS_FINAL_CONTAINER_CANARY"
        }
    }

    private suspend fun textElements(publication: Publication): List<Content.TextElement> {
        val iterator = checkNotNull(publication.content()) { "Publication has no ContentService" }.iterator()
        return buildList {
            while (iterator.hasNext()) {
                val element = iterator.next()
                if (element is Content.TextElement) add(element)
            }
        }.also { assertTrue("ContentService yielded no text", it.isNotEmpty()) }
    }

    private fun assertReadingOrderLocators(publication: Publication, elements: List<Content.TextElement>) {
        val hrefs = publication.readingOrder.map { it.href.toString() }.toSet()
        elements.forEach { assertTrue(it.locator.href.toString() in hrefs) }
    }

    private suspend fun withOriginal(extension: String, bytes: ByteArray, action: suspend (File) -> Unit) {
        val directory = File(instrumentation.targetContext.cacheDir, "tts-content-${System.nanoTime()}")
        check(directory.mkdir())
        val file = File(directory, "original.$extension")
        try {
            file.writeBytes(bytes)
            action(file)
            assertArrayEquals(bytes, file.readBytes())
            assertEquals(listOf(file.name), directory.list()?.toList())
        } finally {
            directory.deleteRecursively()
        }
    }
}
