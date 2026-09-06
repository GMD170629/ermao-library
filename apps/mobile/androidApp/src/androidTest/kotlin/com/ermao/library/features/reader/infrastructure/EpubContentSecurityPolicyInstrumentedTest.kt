package com.ermao.library.features.reader.infrastructure

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyResourceRole
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.readium.r2.shared.util.AbsoluteUrl
import org.readium.r2.shared.util.FileExtension
import org.readium.r2.shared.util.Try
import org.readium.r2.shared.util.Url
import org.readium.r2.shared.util.asset.ContainerAsset
import org.readium.r2.shared.util.data.Container
import org.readium.r2.shared.util.data.ReadError
import org.readium.r2.shared.util.format.Format
import org.readium.r2.shared.util.format.FormatSpecification
import org.readium.r2.shared.util.format.Specification
import org.readium.r2.shared.util.mediatype.MediaType
import org.readium.r2.shared.util.resource.Resource
import org.readium.r2.streamer.PublicationOpener
import org.readium.r2.streamer.parser.epub.EpubParser

@RunWith(AndroidJUnit4::class)
class EpubContentSecurityPolicyInstrumentedTest {
    @Test
    fun protectedContainerAssetReachesPublicationOpenerBeforeFirstReadingOrderRead() = runTest {
        val resources = linkedMapOf(
            "META-INF/container.xml" to """
                <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
                  <rootfiles><rootfile full-path="OPS/package.bin" media-type="application/oebps-package+xml"/></rootfiles>
                </container>
            """.trimIndent().encodeToByteArray(),
            "OPS/package.bin" to """
                <package xmlns="http://www.idpf.org/2007/opf" version="3.0">
                  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Test</dc:title></metadata>
                  <manifest><item id="chapter" href="chapter.bin" media-type="application/future"/></manifest>
                  <spine><itemref idref="chapter"/></spine>
                </package>
            """.trimIndent().encodeToByteArray(),
            "OPS/chapter.bin" to "<html><head></head><body><p>Readable</p></body></html>".encodeToByteArray(),
        )
        val resolver = EpubContentSecurityPolicy.ArchiveResourceRoleResolver()
        val protected = EpubContentSecurityPolicy.protectAsset(
            ContainerAsset(epubFormat(), MemoryContainer(resources)),
            onFailure = { error, _ -> throw AssertionError("protected resource failed", error) },
            resourceRoles = resolver,
        )
        val publication = PublicationOpener(EpubParser()).open(
            asset = protected,
            allowUserInteraction = false,
            onCreatePublication = {
                resolver.markReadingOrder(manifest.readingOrder.mapNotNull { it.url().path })
            },
        ).getOrNull() ?: error("Publication opener rejected protected asset")

        val readingOrder = publication.readingOrder.single()
        val chapter = checkNotNull(publication.get(readingOrder))
        val bytes = chapter.read().getOrNull() ?: error("First reading-order read failed")
        assertTrue(bytes.decodeToString().contains("data-shuku-safety-policy-version"))
        assertEquals(ReaderSafetyResourceRole.READING_ORDER, resolver.roleFor("OPS/chapter.bin"))
        assertEquals(ReaderSafetyResourceRole.CONTROL_DOCUMENT, resolver.roleFor("OPS/package.bin"))
        publication.close()
    }

    private fun epubFormat() = Format(
        specification = FormatSpecification(Specification.Epub),
        mediaType = MediaType("application/epub+zip")!!,
        fileExtension = FileExtension("epub"),
    )

    private class MemoryContainer(
        values: Map<String, ByteArray>,
    ) : Container<Resource> {
        private val resources = values.mapKeys { Url(it.key)!! }

        override val entries: Set<Url> = resources.keys

        override fun get(url: Url): Resource? = resources[url]?.let(::MemoryResource)

        override fun close() = Unit
    }

    private class MemoryResource(
        private val value: ByteArray,
    ) : Resource {
        override val sourceUrl: AbsoluteUrl? = null

        override suspend fun properties() = Try.success(Resource.Properties())

        override suspend fun read(range: LongRange?): Try<ByteArray, ReadError> =
            Try.success(if (range == null) value else value.sliceArray(range.map(Long::toInt)))

        override suspend fun length(): Try<Long, ReadError> = Try.success(value.size.toLong())

        override fun close() = Unit
    }
}
