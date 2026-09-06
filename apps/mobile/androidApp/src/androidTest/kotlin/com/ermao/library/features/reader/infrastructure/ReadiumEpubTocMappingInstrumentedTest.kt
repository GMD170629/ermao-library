package com.ermao.library.features.reader.infrastructure

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.shared.modules.reader.ReaderNavigationTargetInvalid
import com.ermao.library.shared.modules.reader.ReaderNavigationTargetReflowable
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.readium.r2.shared.publication.Link
import org.readium.r2.shared.publication.Manifest
import org.readium.r2.shared.publication.Metadata
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.util.Url
import org.readium.r2.shared.util.mediatype.MediaType

@RunWith(AndroidJUnit4::class)
class ReadiumEpubTocMappingInstrumentedTest {
    @Test
    fun preservesCoreIdentityAndAuthoredFragmentWhenLocatorUsesResourcePath() {
        val publication = Publication(Manifest(metadata = Metadata(), readingOrder = listOf(link("chapter.xhtml", "chapter-0"))))
        try {
            val mapper = ReadiumLocatorMapper()
            val entry = mapReadiumTocEntries(listOf(link("chapter.xhtml#second", "chapter-7"))) {
                publication.locatorFromLink(it)?.let(mapper::toDomain)
            }.single()
            assertEquals("chapter-7", entry.id)
            assertEquals(7, entry.index)
            assertEquals("chapter.xhtml", (entry.location as ReflowReaderLocation).resourceKey)
            val target = requireNotNull(mapper.navigationLocator(entry.target, publication))
            assertEquals(listOf("second"), target.locations.fragments)
        } finally {
            publication.close()
        }
    }

    @Test
    fun preservesNonNavigableGroupsAndDistinctKeysForRepeatedTargets() {
        val children = listOf(link("chapter.xhtml#same", "chapter-1"), link("chapter.xhtml#same", "chapter-2"))
        val group = link("", "chapter-0").copy(children = children)
        val mapped = mapReadiumTocEntries(listOf(group)) {
            it.href.toString().takeIf(String::isNotBlank)?.let { href -> ReflowReaderLocation(resourceKey = href.substringBefore('#')) }
        }
        assertEquals(1, mapped.size)
        assertEquals("chapter-0", mapped.single().id)
        assertTrue(mapped.single().target is ReaderNavigationTargetInvalid)
        assertEquals(listOf("chapter-1", "chapter-2"), mapped.single().children.map { it.id })
        assertEquals(listOf("chapter.xhtml#same", "chapter.xhtml#same"), mapped.single().children.map {
            (it.target as ReaderNavigationTargetReflowable).href
        })
    }

    @Test(expected = IllegalArgumentException::class)
    fun missingCoreIdentityFailsInsteadOfInventingAnotherIdentity() {
        mapReadiumTocEntries(listOf(Link(href = requireNotNull(Url("chapter.xhtml")), title = "Title"))) {
            ReflowReaderLocation(resourceKey = "chapter.xhtml")
        }
    }

    private fun link(href: String, key: String) = Link(
        href = requireNotNull(Url(href.ifEmpty { "#" })), mediaType = MediaType.XHTML, title = key,
    ).addProperties(mapOf("shuku:navigationKey" to key))
}
