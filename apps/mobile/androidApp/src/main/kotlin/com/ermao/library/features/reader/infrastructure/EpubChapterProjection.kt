@file:OptIn(org.readium.r2.shared.InternalReadiumApi::class)

package com.ermao.library.features.reader.infrastructure

import com.ermao.library.chapter.infrastructure.ChapterCore
import com.ermao.library.chapter.infrastructure.ChapterCoreResult
import com.ermao.library.chapter.infrastructure.ChapterCoreXmlAttribute
import com.ermao.library.chapter.infrastructure.ChapterCoreXmlEvent
import org.readium.r2.shared.publication.Link
import org.readium.r2.shared.util.Url
import org.readium.r2.shared.util.fromEpubHref
import org.readium.r2.shared.util.getOrElse
import org.readium.r2.shared.util.RelativeUrl
import org.readium.r2.shared.util.asset.ContainerAsset
import org.readium.r2.shared.util.data.Container
import org.readium.r2.shared.util.data.ReadException
import org.readium.r2.shared.util.mediatype.MediaType
import org.readium.r2.shared.util.resource.Resource
import org.xml.sax.Attributes
import org.xml.sax.EntityResolver
import org.xml.sax.InputSource
import org.xml.sax.SAXException
import org.xml.sax.SAXParseException
import org.xml.sax.helpers.DefaultHandler
import java.io.ByteArrayInputStream
import javax.xml.parsers.SAXParserFactory

/**
 * Projects an EPUB's authored navigation from the protected archive container.
 *
 * The publication opener still owns the EPUB publication. This adapter only reads
 * the already protected resources, resolves targets against the OPF manifest, and
 * delegates chapter selection/tree semantics to ChapterCore.
 */
internal object EpubChapterProjection {
    /** Projects the optional EPUB navigation; missing optional resources produce an empty TOC. */
    suspend fun project(asset: ContainerAsset): List<Link> {
        return projectInternal(asset)
    }

    private suspend fun projectInternal(asset: ContainerAsset): List<Link> {
        val indexed = indexContainer(asset.container)
        val containerPath = indexed.keys.firstOrNull { it == CONTAINER_PATH } ?: return emptyList()
        val containerBytes = read(indexed, asset.container, containerPath) ?: return emptyList()
        val opfPath = parseRootfile(containerBytes, indexed.keys) ?: return emptyList()
        val opfBytes = read(indexed, asset.container, opfPath) ?: return emptyList()
        val packageInfo = parsePackage(opfBytes, opfPath, indexed.keys)
        if (packageInfo.manifest.isEmpty()) return emptyList()

        val navLinks = packageInfo.navPath?.let { navPath ->
            val bytes = read(indexed, asset.container, navPath)
            bytes?.let {
                parseOptionalNavigation(it, navPath, packageInfo.manifestPaths, ERMAO_CHAPTER_EPUB_NAV)
            }
        }.orEmpty()
        if (navLinks.isNotEmpty()) return navLinks

        val ncxLinks = packageInfo.ncxPath?.let { ncxPath ->
            val bytes = read(indexed, asset.container, ncxPath)
            bytes?.let {
                parseOptionalNavigation(it, ncxPath, packageInfo.manifestPaths, ERMAO_CHAPTER_EPUB_NCX)
            }
        }.orEmpty()
        return ncxLinks
    }

    private data class ManifestItem(
        val id: String,
        val href: String,
        val mediaType: String,
        val properties: Set<String>,
    )

    private data class PackageInfo(
        val manifest: List<ManifestItem>,
        val navPath: String?,
        val ncxPath: String?,
    ) {
        val manifestPaths: Set<String> = manifest.mapTo(linkedSetOf()) { it.href }
    }

    private fun indexContainer(container: Container<Resource>): Map<String, Url> {
        val indexed = linkedMapOf<String, Url>()
        for (url in container.entries) {
            val rawPath = url.path ?: continue
            AndroidEpubArchiveSafetyPreflight.canonicalPath(rawPath)?.let { path ->
                indexed.putIfAbsent(path, url.removeQuery().removeFragment())
            }
        }
        return indexed
    }

    private suspend fun read(
        indexed: Map<String, Url>,
        container: Container<Resource>,
        path: String,
    ): ByteArray? {
        val url = indexed[path] ?: return null
        val resource = container[url] ?: return null
        return resource.read().getOrElse { failure ->
            throw ReadException(failure)
        }
    }

    private fun parseRootfile(bytes: ByteArray, available: Set<String>): String? {
        var candidate: String? = null
        parseXml(bytes, object : StrictHandler() {
            override fun startElement(
                uri: String?,
                localName: String,
                qName: String,
                attributes: Attributes,
            ) {
                if (candidate != null || local(localName, qName) != "rootfile") return
                val raw = attribute(attributes, "full-path") ?: return
                val path = AndroidEpubArchiveSafetyPreflight.canonicalPath(raw) ?: return
                if (path in available) candidate = path
            }
        })
        return candidate
    }

    private fun parsePackage(bytes: ByteArray, opfPath: String, available: Set<String>): PackageInfo {
        val basePath = opfPath.substringBeforeLast('/', "")
        val manifest = mutableListOf<ManifestItem>()
        var spineToc: String? = null
        parseXml(bytes, object : StrictHandler() {
            override fun startElement(
                uri: String?,
                localName: String,
                qName: String,
                attributes: Attributes,
            ) {
                when (local(localName, qName)) {
                    "item" -> {
                        val id = attribute(attributes, "id")?.trim().orEmpty()
                        val rawHref = attribute(attributes, "href")?.trim().orEmpty()
                        val href = resolvePath(basePath, rawHref, available)
                        if (id.isNotEmpty() && href != null) {
                            manifest += ManifestItem(
                                id = id,
                                href = href,
                                mediaType = attribute(attributes, "media-type")?.trim().orEmpty(),
                                properties = attribute(attributes, "properties")
                                    .orEmpty()
                                    .split(Regex("\\s+"))
                                    .filter(String::isNotEmpty)
                                    .toSet(),
                            )
                        }
                    }
                    "spine" -> spineToc = attribute(attributes, "toc")?.trim()?.takeIf(String::isNotEmpty)
                }
            }
        })
        val navPath = manifest.firstOrNull { "nav" in it.properties }?.href
        val ncxPath = manifest.firstOrNull { it.id == spineToc }?.href ?: manifest.firstOrNull {
            it.mediaType.equals("application/x-dtbncx+xml", ignoreCase = true)
        }?.href
        return PackageInfo(manifest, navPath, ncxPath)
    }

    private fun parseNavigation(
        bytes: ByteArray,
        documentPath: String,
        manifestPaths: Set<String>,
        format: Int,
    ): List<Link> {
        val events = mutableListOf<ChapterCoreXmlEvent>()
        parseXml(bytes, object : StrictHandler() {
            override fun startElement(
                uri: String?,
                localName: String,
                qName: String,
                attributes: Attributes,
            ) {
                val name = local(localName, qName)
                val mappedAttributes = (0 until attributes.length).map { index ->
                    ChapterCoreXmlAttribute(
                        name = local(attributes.getLocalName(index), attributes.getQName(index)),
                        value = attributes.getValue(index),
                    )
                }.toTypedArray()
                val rawTarget = attribute(attributes, "href") ?: attribute(attributes, "src")
                events += ChapterCoreXmlEvent(
                    kind = XML_START,
                    name = name,
                    attributes = mappedAttributes,
                    href = rawTarget?.let { resolveTarget(documentPath, it, manifestPaths) },
                )
            }

            override fun characters(ch: CharArray, start: Int, length: Int) {
                if (length > 0) {
                    events += ChapterCoreXmlEvent(kind = XML_TEXT, text = String(ch, start, length))
                }
            }

            override fun endElement(uri: String?, localName: String, qName: String) {
                events += ChapterCoreXmlEvent(kind = XML_END, name = local(localName, qName))
            }
        })
        if (format == ERMAO_CHAPTER_EPUB_NAV &&
            events.firstOrNull { it.kind == XML_START }?.name != "html"
        ) {
            return emptyList()
        }
        val result = ChapterCore.parseXml(format = format, events = events)
        return result.toLinks()
    }

    /** A malformed optional navigation document permits the NCX fallback. */
    private fun parseOptionalNavigation(
        bytes: ByteArray,
        documentPath: String,
        manifestPaths: Set<String>,
        format: Int,
    ): List<Link> = try {
        parseNavigation(bytes, documentPath, manifestPaths, format)
    } catch (_: SAXParseException) {
        emptyList()
    }

    private fun ChapterCoreResult.toLinks(): List<Link> {
        val childrenByParent = entries.indices.groupBy { entries[it].parentIndex }

        fun make(index: Int): Link {
            val entry = entries[index]
            val children = childrenByParent[index].orEmpty().map(::make)
            val href = entry.href.orEmpty()
            val link = Link(
                // Readium's Url parser rejects an empty string. A fragment-only URL is
                // the SDK representation of a structural Link with no target.
                href = requireNotNull(if (href.isEmpty()) Url("#") else Url(href)),
                mediaType = MediaType.XHTML,
                title = entry.title,
                children = children,
            )
            return link.addProperties(mapOf("shuku:navigationKey" to entry.key))
        }

        return childrenByParent[null].orEmpty().map(::make)
    }

    private fun resolvePath(basePath: String, raw: String, available: Set<String>): String? {
        val resolved = resolveUrl(basePath, raw) ?: return null
        val path = AndroidEpubArchiveSafetyPreflight.canonicalPath(
            resolved.removeFragment().path ?: return null,
        )
            ?: return null
        return path.takeIf { it in available }
    }

    private fun resolveTarget(documentPath: String, raw: String, known: Set<String>): String? {
        val basePath = documentPath.substringBeforeLast('/', "")
        val documentName = documentPath.substringAfterLast('/')
        val href = if (raw.startsWith("#")) documentName + raw else raw
        val resolved = resolveUrl(basePath, href) ?: return null
        val path = AndroidEpubArchiveSafetyPreflight.canonicalPath(
            resolved.removeFragment().path ?: return null,
        )
            ?: return null
        if (path !in known) return null
        val fragment = resolved.fragment?.takeIf(String::isNotEmpty)
        return if (fragment == null) path else "$path#$fragment"
    }

    private fun resolveUrl(basePath: String, raw: String): Url? {
        val base = Url.fromDecodedPath(if (basePath.isEmpty()) "./" else "$basePath/") ?: return null
        val other = Url.fromEpubHref(raw) as? RelativeUrl ?: return null
        return base.resolve(other).normalize()
    }

    private fun parseXml(bytes: ByteArray, handler: StrictHandler) {
        val factory = SAXParserFactory.newInstance().apply { isNamespaceAware = true }
        val reader = factory.newSAXParser().xmlReader.apply {
            entityResolver = EntityResolver { _, _ -> throw SAXException("External XML is prohibited") }
            contentHandler = handler
            errorHandler = handler
        }
        reader.parse(InputSource(ByteArrayInputStream(bytes)))
    }

    private abstract class StrictHandler : DefaultHandler() {
        override fun error(exception: SAXParseException): Nothing = throw exception
        override fun fatalError(exception: SAXParseException): Nothing = throw exception
    }

    private fun attribute(attributes: Attributes, name: String): String? =
        (0 until attributes.length).firstNotNullOfOrNull { index ->
            val localName = local(attributes.getLocalName(index), attributes.getQName(index))
            localName.takeIf { it == name }?.let { attributes.getValue(index) }
        }

    private fun local(localName: String, qualifiedName: String): String =
        localName.ifBlank { qualifiedName.substringAfterLast(':') }

    private const val CONTAINER_PATH = "META-INF/container.xml"
    private const val XML_START = 1
    private const val XML_TEXT = 2
    private const val XML_END = 3
    private const val ERMAO_CHAPTER_EPUB_NAV = 1
    private const val ERMAO_CHAPTER_EPUB_NCX = 2
}
