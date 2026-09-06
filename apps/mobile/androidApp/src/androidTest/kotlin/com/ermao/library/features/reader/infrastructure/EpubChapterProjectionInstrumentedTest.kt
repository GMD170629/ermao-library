package com.ermao.library.features.reader.infrastructure

import androidx.test.ext.junit.runners.AndroidJUnit4
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
import org.readium.r2.shared.util.data.CompositeContainer
import org.readium.r2.shared.util.data.Container
import org.readium.r2.shared.util.data.ReadError
import org.readium.r2.shared.util.data.ReadException
import org.readium.r2.shared.util.format.Format
import org.readium.r2.shared.util.format.FormatSpecification
import org.readium.r2.shared.util.format.Specification
import org.readium.r2.shared.util.mediatype.MediaType
import org.readium.r2.shared.util.resource.Resource
import org.readium.r2.shared.util.resource.SingleResourceContainer
import org.readium.r2.shared.util.resource.StringResource

@RunWith(AndroidJUnit4::class)
class EpubChapterProjectionInstrumentedTest {
    @Test
    fun protectedNavPreservesGroupsDuplicateTargetsEmojiAndFragmentOnlyLinks() = runTest {
        val links = EpubChapterProjection.project(protectedAsset(navigationResources()))

        assertEquals(1, links.size)
        assertEquals("部 😀", links.single().title)
        assertEquals("#", links.single().href.toString())
        assertEquals(3, links.single().children.size)
        assertEquals(
            listOf("第一", "第二同目标", "本页"),
            links.single().children.map { it.title },
        )
        assertEquals(
            listOf("chapter-1", "chapter-2", "chapter-3"),
            links.single().children.map { it.key() },
        )
        assertEquals(
            "OPS/text/one.xhtml#one",
            links.single().children[0].href.toString(),
        )
        assertEquals(
            "OPS/text/one.xhtml#one",
            links.single().children[1].href.toString(),
        )
        assertEquals(
            "OPS/nav/nav.xhtml#local",
            links.single().children[2].href.toString(),
        )
    }

    @Test
    fun malformedNavFallsBackToNcx() = runTest {
        val links = EpubChapterProjection.project(rawAsset(navigationFallbackResources()))

        assertEquals(listOf("NCX 章节"), links.map { it.title })
        assertEquals("OPS/text/one.xhtml#one", links.single().href.toString())
    }

    @Test
    fun spineNcxIsUsedEvenWhenItsMediaTypeIsUnknown() = runTest {
        val links = EpubChapterProjection.project(rawAsset(unknownNcxMediaResources()))

        assertEquals(listOf("兼容 NCX"), links.map { it.title })
        assertEquals("OPS/text/one.xhtml#one", links.single().href.toString())
    }

    @Test
    fun missingNavAndNcxProducesAnEmptyToc() = runTest {
        assertTrue(EpubChapterProjection.project(rawAsset(noNavigationResources())).isEmpty())
    }

    @Test
    fun resourceReadFailureIsNotConvertedToAnEmptyToc() = runTest {
        val failing = ContainerAsset(
            epubFormat(),
            SingleResourceContainer(
                requireNotNull(Url("META-INF/container.xml")),
                FailingResource,
            ),
        )
        var thrown = false
        try {
            EpubChapterProjection.project(failing)
        } catch (_: ReadException) {
            thrown = true
        }
        assertTrue("A protected-resource read failure must remain observable", thrown)
    }

    private fun protectedAsset(resources: Map<String, String>): ContainerAsset {
        val protected = EpubContentSecurityPolicy.protectAsset(
            asset = rawAsset(resources),
            onFailure = { error, role ->
                throw AssertionError("fixture protection failed for $role", error)
            },
        )
        return requireNotNull(protected as? ContainerAsset)
    }

    private fun rawAsset(resources: Map<String, String>): ContainerAsset {
        val containers = resources.map { (path, value) ->
            SingleResourceContainer(
                requireNotNull(Url(path)),
                StringResource(value),
            )
        }
        val container: Container<Resource> = CompositeContainer(containers)
        return ContainerAsset(epubFormat(), container)
    }

    private fun navigationResources(): Map<String, String> = mapOf(
        "META-INF/container.xml" to containerXml(),
        "OPS/package.opf" to """
            <package xmlns="http://www.idpf.org/2007/opf" version="3.0">
              <manifest>
                <item id="nav" href="nav/nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
                <item id="one" href="text/one.xhtml" media-type="application/xhtml+xml"/>
                <item id="two" href="text/two.xhtml" media-type="application/xhtml+xml"/>
              </manifest>
              <spine><itemref idref="one"/><itemref idref="two"/></spine>
            </package>
        """.trimIndent(),
        "OPS/nav/nav.xhtml" to """
            <html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
              <head></head><body><nav epub:type="toc"><ol>
                <li><span>部 😀</span><ol>
                  <li><a href="../text/one.xhtml#one">第一</a></li>
                  <li><a href="../text/one.xhtml#one">第二同目标</a></li>
                  <li><a href="#local">本页</a></li>
                </ol></li>
              </ol></nav><section id="local">正文</section></body>
            </html>
        """.trimIndent(),
        "OPS/text/one.xhtml" to "<html><head/><body><h1 id=\"one\">一</h1></body></html>",
        "OPS/text/two.xhtml" to "<html><head/><body><h1 id=\"two\">二</h1></body></html>",
    )

    private fun navigationFallbackResources(): Map<String, String> = baseResources(
        nav = "<html><body><nav><ol><li><a href=\"../text/one.xhtml#one\">坏目录",
        ncx = ncx("NCX 章节"),
        ncxMediaType = "application/x-dtbncx+xml",
    )

    private fun unknownNcxMediaResources(): Map<String, String> = baseResources(
        nav = null,
        ncx = ncx("兼容 NCX"),
        ncxMediaType = "application/future-navigation",
    )

    private fun noNavigationResources(): Map<String, String> = mapOf(
        "META-INF/container.xml" to containerXml(),
        "OPS/package.opf" to """
            <package xmlns="http://www.idpf.org/2007/opf" version="3.0">
              <manifest><item id="one" href="text/one.xhtml" media-type="application/xhtml+xml"/></manifest>
              <spine><itemref idref="one"/></spine>
            </package>
        """.trimIndent(),
        "OPS/text/one.xhtml" to "<html><head/><body><h1 id=\"one\">一</h1></body></html>",
    )

    private fun baseResources(
        nav: String?,
        ncx: String,
        ncxMediaType: String,
    ): Map<String, String> = buildMap {
        put("META-INF/container.xml", containerXml())
        put(
            "OPS/package.opf",
            """
                <package xmlns="http://www.idpf.org/2007/opf" version="3.0">
                  <manifest>
                    ${if (nav != null) "<item id=\"nav\" href=\"nav/nav.xhtml\" media-type=\"application/xhtml+xml\" properties=\"nav\"/>" else ""}
                    <item id="ncx" href="nav/toc.ncx" media-type="$ncxMediaType"/>
                    <item id="one" href="text/one.xhtml" media-type="application/xhtml+xml"/>
                  </manifest>
                  <spine toc="ncx"><itemref idref="one"/></spine>
                </package>
            """.trimIndent(),
        )
        nav?.let { put("OPS/nav/nav.xhtml", it) }
        put("OPS/nav/toc.ncx", ncx)
        put("OPS/text/one.xhtml", "<html><head/><body><h1 id=\"one\">一</h1></body></html>")
    }

    private fun ncx(title: String): String = """
        <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
          <navMap><navPoint><navLabel><text>$title</text></navLabel>
            <content src="../text/one.xhtml#one"/>
          </navPoint></navMap>
        </ncx>
    """.trimIndent()

    private fun containerXml(): String = """
        <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
          <rootfiles><rootfile full-path="OPS/package.opf" media-type="application/oebps-package+xml"/></rootfiles>
        </container>
    """.trimIndent()

    private fun epubFormat() = Format(
        specification = FormatSpecification(Specification.Epub),
        mediaType = MediaType("application/epub+zip")!!,
        fileExtension = FileExtension("epub"),
    )

    private fun org.readium.r2.shared.publication.Link.key(): String? =
        properties.otherProperties["shuku:navigationKey"]?.toString()

    private object FailingResource : Resource {
        override val sourceUrl: AbsoluteUrl? = null
        override suspend fun properties() = Try.success(Resource.Properties())
        override suspend fun read(range: LongRange?): Try<ByteArray, ReadError> =
            Try.failure(ReadError.Decoding("fixture read failure"))
        override suspend fun length(): Try<Long, ReadError> = Try.failure(
            ReadError.Decoding("fixture length failure"),
        )
        override fun close() = Unit
    }
}
