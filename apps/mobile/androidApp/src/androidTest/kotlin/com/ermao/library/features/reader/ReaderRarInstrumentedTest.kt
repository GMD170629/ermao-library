package com.ermao.library.features.reader

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.archive.infrastructure.ArchiveCore
import com.ermao.library.features.reader.infrastructure.AndroidReaderPublicationStore
import com.ermao.library.features.reader.infrastructure.CbzReadiumPublicationFactory
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import java.io.File
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ReaderRarInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context: Context = instrumentation.targetContext
    private val testContext: Context = instrumentation.context
    private val publicationStore = AndroidReaderPublicationStore(context)
    private val publishedResourceIds = mutableListOf<String>()

    @After
    fun removeArtifacts() = runBlocking {
        publishedResourceIds.forEach { publicationStore.delete(it) }
    }

    @Test
    fun opensOriginalRar5AndCbrWithoutConversionOrUnpacking() = runBlocking {
        val fixtures = listOf(
            Fixture("山海邮差/单行本/02 雨师借伞.rar", ReaderSourceFormat.Rar),
            Fixture("山海邮差/典藏版/终章/04 归山.cbr", ReaderSourceFormat.Cbr),
        )

        fixtures.forEach { fixture ->
            val resourceId = "archive-reader-${UUID.randomUUID()}"
            publishedResourceIds += resourceId
            val source = testContext.assets.open(fixture.assetPath).use { input ->
                publicationStore.publishLocalPublication(
                    resourceId = resourceId,
                    displayTitle = fixture.assetPath.substringAfterLast('/'),
                    input = input,
                    sourceFormat = fixture.sourceFormat,
                )
            }
            val original = publicationStore.resolve(source)

            ArchiveCore.open(original).use { archive ->
                assertEquals("libarchive 3.8.9", ArchiveCore.version)
                assertTrue(archive.pages.isNotEmpty())
                assertTrue(archive.readPage(0).isNotEmpty())
            }
            val pages = CbzReadiumPublicationFactory().indexPages(original)
            assertTrue(pages.isNotEmpty())
            assertEquals(pages.indices.map { "pages/$it" }, pages.map { it.resourceHref })
        }
    }

    private data class Fixture(
        val assetPath: String,
        val sourceFormat: ReaderSourceFormat,
    )
}
