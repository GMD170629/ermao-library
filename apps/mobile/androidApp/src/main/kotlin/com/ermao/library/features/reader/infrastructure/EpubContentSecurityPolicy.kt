package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.MobiMarkupEnvelope
import java.io.StringReader
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction
import java.text.Normalizer
import javax.xml.parsers.DocumentBuilderFactory
import javax.xml.parsers.ParserConfigurationException
import org.readium.r2.shared.util.Try
import org.readium.r2.shared.util.data.Container
import org.readium.r2.shared.util.data.ReadError
import org.readium.r2.shared.util.resource.Resource
import org.readium.r2.shared.util.resource.TransformingContainer
import org.readium.r2.shared.util.resource.TransformingResource
import org.xml.sax.InputSource
import org.w3c.dom.Element
import org.w3c.dom.Node

internal object EpubContentSecurityPolicy {
    private const val MAXIMUM_MARKUP_BYTES = 64 * 1024 * 1024
    private const val PROFILE = "android-v3"
    private const val CONTENT_SECURITY_POLICY =
        "default-src 'none'; base-uri 'none'; connect-src 'none'; form-action 'none'; " +
            "frame-src 'none'; child-src 'none'; object-src 'none'; " +
            "script-src https://*/readium/scripts/readium-reflowable.js " +
            "https://*/readium/scripts/readium-fixed.js; script-src-attr 'none'; " +
            "style-src 'self' https://*/readium/readium-css/ blob: 'unsafe-inline'; " +
            "img-src 'self' blob: data:; " +
            "font-src 'self' https://*/readium/readium-css/fonts/ https://*/readium/fonts/ https://*/fonts/reader/ blob: data:; " +
            "media-src 'self' blob: data:"
    private const val DEVICE_VIEWPORT =
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\"/>"
    private const val SECURITY_STYLE =
        "iframe,frame,object,embed,applet{display:none!important;}" +
            "input,button,select,textarea{pointer-events:none!important;}"

    private fun securityHead(viewport: String): String =
        "<meta http-equiv=\"Content-Security-Policy\" content=\"$CONTENT_SECURITY_POLICY\" " +
            "data-shuku-security-profile=\"$PROFILE\"/>" + viewport +
            "<style data-shuku-security-profile=\"$PROFILE\">$SECURITY_STYLE</style>"

    /** Only accepts output from the owned TXT/FB2 templates, never original chapters. */
    fun generatedChapter(markup: String): ByteArray =
        markup.replaceFirst("<head>", "<head>" + securityHead(DEVICE_VIEWPORT)).toByteArray(Charsets.UTF_8)

    fun apply(container: Container<Resource>, onFailure: ((Exception) -> Unit)? = null): Container<Resource> =
        transformMarkup(container, ::decorateHtml, onFailure)

    fun applyMobi(container: Container<Resource>): Container<Resource> =
        transformMarkup(container, ::decorateMobiHtml)

    internal fun decorateMobiHtml(bytes: ByteArray): ByteArray = decorateHtml(
        MobiMarkupEnvelope().prepare(bytes.decodeToString(throwOnInvalidSequence = true)).encodeToByteArray(),
    )

    private fun transformMarkup(
        container: Container<Resource>,
        decorate: (ByteArray) -> ByteArray,
        onFailure: ((Exception) -> Unit)? = null,
    ): Container<Resource> =
        TransformingContainer(container) { url, resource ->
            if (url.path?.substringAfterLast('.', missingDelimiterValue = "")?.lowercase() in HTML_EXTENSIONS) {
                TransformingResource(resource) { bytes ->
                    try {
                        Try.success(decorate(bytes))
                    } catch (error: Exception) {
                        onFailure?.invoke(error)
                        Try.failure(ReadError.Decoding(error))
                    }
                }
            } else {
                resource
            }
        }

    internal fun decorateHtml(bytes: ByteArray): ByteArray {
        val validated = decodeAndValidate(bytes)
        val markup = validated.markup
        val lexicalMarkup = maskNonMarkup(markup)
        val open = HEAD_OPEN.find(lexicalMarkup)
            ?: throw IllegalArgumentException("Publication XHTML head is missing")
        val close = HEAD_CLOSE.find(lexicalMarkup, open.range.last + 1)
            ?: throw IllegalArgumentException("Publication XHTML head is not closed")
        val headStart = open.range.last + 1
        val originalHead = markup.substring(headStart, close.range.first)
        val safeHead = META_TAG.replace(BASE_TAG.replace(originalHead, "")) { match ->
            val value = HTTP_EQUIV.find(match.value)?.groups?.get("value")?.value?.trim()?.lowercase()
            if (value == "content-security-policy" || value == "refresh") "" else match.value
        }
        val viewport = if (META_TAG.findAll(safeHead).any { match ->
                NAME.find(match.value)?.groups?.get("value")?.value?.trim()?.lowercase() == "viewport"
            }
        ) {
            ""
        } else {
            DEVICE_VIEWPORT
        }
        val decoration = securityHead(viewport)
        val decorated = markup.substring(0, headStart) + decoration + safeHead + markup.substring(close.range.first)
        val declaration = XML_DECLARATION.find(decorated)
        val utf8Markup = if (declaration == null) {
            decorated
        } else {
            decorated.replaceRange(
                declaration.range,
                XML_ENCODING.replaceFirst(declaration.value, "encoding=\"utf-8\""),
            )
        }
        val decoratedBytes = utf8Markup.toByteArray(Charsets.UTF_8)
        return decoratedBytes
    }

    internal fun locatorBodyProjection(bytes: ByteArray): List<Map<String, String>> =
        decodeAndValidate(bytes).bodyProjection.map { element ->
            buildMap {
                put("path", element.path)
                put("localName", element.localName)
                element.id?.let { put("id", it) }
                element.text?.let { put("text", it) }
            }
        }

    private data class ValidatedMarkup(
        val markup: String,
        val bodyProjection: List<LocatorElementProjection>,
    )

    private data class LocatorElementProjection(
        val path: String,
        val localName: String,
        val id: String?,
        val text: String?,
    )

    private fun decodeAndValidate(bytes: ByteArray): ValidatedMarkup {
        require(bytes.isNotEmpty() && bytes.size <= MAXIMUM_MARKUP_BYTES) {
            "Publication markup exceeds the size limit"
        }
        val markup = when {
            bytes.startsWith(UTF_8_BOM) -> strictDecode(bytes, Charsets.UTF_8, UTF_8_BOM.size)
            bytes.startsWith(UTF_16_LE_BOM) -> strictDecode(bytes, Charsets.UTF_16LE, UTF_16_LE_BOM.size)
            bytes.startsWith(UTF_16_BE_BOM) -> strictDecode(bytes, Charsets.UTF_16BE, UTF_16_BE_BOM.size)
            else -> {
                val encoding = XML_DECLARATION.find(bytes.copyOfRange(0, minOf(bytes.size, 512)).toString(Charsets.US_ASCII))
                    ?.let { XML_ENCODING.find(it.value)?.groups?.get("encoding")?.value }
                    ?.lowercase()
                    ?.replace('_', '-')
                    ?: "utf-8"
                require(encoding == "utf-8" || encoding == "utf8") {
                    "Publication markup encoding is unsupported"
                }
                strictDecode(bytes, Charsets.UTF_8, 0)
            }
        }
        validateDeclarations(markup)
        val parserMarkup = replaceStandardEntitiesForParsing(markup)
        val factory = DocumentBuilderFactory.newInstance().apply {
            isNamespaceAware = true
            isExpandEntityReferences = false
        }
        disableXIncludeWhenSupported(factory)
        disableFeatureWhenSupported(factory, "http://xml.org/sax/features/external-general-entities")
        disableFeatureWhenSupported(factory, "http://xml.org/sax/features/external-parameter-entities")
        disableFeatureWhenSupported(factory, "http://apache.org/xml/features/nonvalidating/load-external-dtd")
        val document = factory.newDocumentBuilder().apply {
            setEntityResolver { _, _ -> InputSource(StringReader("")) }
        }.parse(InputSource(StringReader(parserMarkup)))
        require((document.documentElement.localName ?: document.documentElement.nodeName).lowercase() == "html") {
            "Publication XHTML root must be html"
        }
        val children = document.documentElement.childNodes
        var heads = 0
        var bodies = 0
        for (index in 0 until children.length) {
            val child = children.item(index)
            val name = (child.localName ?: child.nodeName).lowercase()
            if (name == "head") heads += 1
            if (name == "body") bodies += 1
        }
        require(heads == 1 && bodies == 1) {
            "Publication XHTML must contain one head and one body"
        }
        val body = (0 until children.length)
            .map(children::item)
            .filterIsInstance<Element>()
            .single { localName(it) == "body" }
        return ValidatedMarkup(markup, projectElement(body, "/body[1]"))
    }

    private fun disableXIncludeWhenSupported(factory: DocumentBuilderFactory) {
        try {
            factory.isXIncludeAware = false
        } catch (_: UnsupportedOperationException) {
            // Android's platform parser reports XInclude as unsupported; it cannot expand it.
            return
        }
    }

    private fun disableFeatureWhenSupported(factory: DocumentBuilderFactory, feature: String) {
        try {
            factory.setFeature(feature, false)
        } catch (_: ParserConfigurationException) {
            // Android rejects unsupported SAX flags. Lexical declaration checks and the
            // empty EntityResolver below still prevent external entity or DTD expansion.
            return
        }
    }

    private fun validateDeclarations(markup: String) {
        val lexicalMarkup = maskNonMarkup(markup)
        require(!ENTITY_OPEN.containsMatchIn(lexicalMarkup)) {
            "Publication markup contains unsafe declarations"
        }
        val opens = DOCTYPE_OPEN.findAll(lexicalMarkup).toList()
        if (opens.isEmpty()) return
        val declarations = DOCTYPE_DECLARATION.findAll(lexicalMarkup).toList()
        require(
            opens.size == 1 &&
                declarations.size == 1 &&
                opens.single().range.first == declarations.single().range.first &&
                SAFE_EPUB_DOCTYPE.matches(declarations.single().value) &&
                lexicalMarkup.substring(0, declarations.single().range.first).isBlank(),
        ) { "Publication markup contains unsafe declarations" }
    }

    private fun replaceStandardEntitiesForParsing(markup: String): String {
        val lexicalMarkup = maskNonMarkup(markup)
        val result = StringBuilder(markup)
        STANDARD_ENTITY_REFERENCE.findAll(lexicalMarkup).toList().asReversed().forEach { match ->
            result.replace(match.range.first, match.range.last + 1, "&#xA0;")
        }
        return result.toString()
    }

    private fun projectElement(element: Element, path: String): List<LocatorElementProjection> {
        val name = localName(element)
        val text = if (name in LOCATOR_BLOCKS) normalizeLocatorText(element.textContent) else null
        val records = mutableListOf(
            LocatorElementProjection(
                path = path,
                localName = name,
                id = element.getAttributeNode("id")?.value,
                text = text,
            ),
        )
        val siblingCounts = mutableMapOf<String, Int>()
        for (index in 0 until element.childNodes.length) {
            val child = element.childNodes.item(index)
            if (child.nodeType != Node.ELEMENT_NODE) continue
            val childElement = child as Element
            val childName = localName(childElement)
            val ordinal = siblingCounts.getOrDefault(childName, 0) + 1
            siblingCounts[childName] = ordinal
            records += projectElement(childElement, "$path/$childName[$ordinal]")
        }
        return records
    }

    private fun localName(element: Element): String =
        (element.localName ?: element.nodeName.substringAfterLast(':')).lowercase()

    private fun normalizeLocatorText(value: String): String = Normalizer
        .normalize(value.replace("\r\n", "\n").replace('\r', '\n'), Normalizer.Form.NFC)
        .replace(UNICODE_WHITESPACE, " ")
        .trim()

    private fun strictDecode(bytes: ByteArray, charset: java.nio.charset.Charset, offset: Int): String = try {
        charset.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
            .decode(java.nio.ByteBuffer.wrap(bytes, offset, bytes.size - offset))
            .toString()
    } catch (error: CharacterCodingException) {
        throw IllegalArgumentException("Publication markup encoding is invalid", error)
    }

    private fun ByteArray.startsWith(prefix: ByteArray): Boolean =
        size >= prefix.size && prefix.indices.all { this[it] == prefix[it] }

    private fun maskNonMarkup(markup: String): String {
        val masked = markup.toCharArray()
        NON_MARKUP.findAll(markup).forEach { match ->
            for (index in match.range) masked[index] = ' '
        }
        return masked.concatToString()
    }

    private val HTML_EXTENSIONS = setOf("html", "xhtml", "htm")
    private val LOCATOR_BLOCKS = setOf(
        "h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "blockquote",
        "figcaption", "td", "th",
    )
    private val UNICODE_WHITESPACE = Regex("[\\s\\p{Z}]+")
    private val UTF_8_BOM = byteArrayOf(0xEF.toByte(), 0xBB.toByte(), 0xBF.toByte())
    private val UTF_16_LE_BOM = byteArrayOf(0xFF.toByte(), 0xFE.toByte())
    private val UTF_16_BE_BOM = byteArrayOf(0xFE.toByte(), 0xFF.toByte())
    private val XML_DECLARATION = Regex("<\\?xml\\b[^?]*\\?>", RegexOption.IGNORE_CASE)
    private val XML_ENCODING = Regex(
        "encoding\\s*=\\s*['\"](?<encoding>[^'\"]+)['\"]",
        RegexOption.IGNORE_CASE,
    )
    private val HEAD_OPEN = Regex("<(?:[A-Za-z_][\\w.-]*:)?head\\b[^>]*>", RegexOption.IGNORE_CASE)
    private val HEAD_CLOSE = Regex("</(?:[A-Za-z_][\\w.-]*:)?head\\s*>", RegexOption.IGNORE_CASE)
    private val BASE_TAG = Regex("<(?:[A-Za-z_][\\w.-]*:)?base\\b[^>]*(?:/\\s*)?>", RegexOption.IGNORE_CASE)
    private val META_TAG = Regex("<(?:[A-Za-z_][\\w.-]*:)?meta\\b[^>]*(?:/\\s*)?>", RegexOption.IGNORE_CASE)
    private val HTTP_EQUIV = Regex(
        "\\bhttp-equiv\\s*=\\s*['\"](?<value>[^'\"]+)['\"]",
        RegexOption.IGNORE_CASE,
    )
    private val NAME = Regex(
        "\\bname\\s*=\\s*['\"](?<value>[^'\"]+)['\"]",
        RegexOption.IGNORE_CASE,
    )
    private val NON_MARKUP = Regex(
        "<!--.*?-->|<!\\[CDATA\\[.*?]]>|<\\?.*?\\?>",
        setOf(RegexOption.DOT_MATCHES_ALL),
    )
    private val DOCTYPE_OPEN = Regex("<!DOCTYPE\\b", RegexOption.IGNORE_CASE)
    private val DOCTYPE_DECLARATION = Regex(
        "<!DOCTYPE\\b[^>]*>",
        setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL),
    )
    private val ENTITY_OPEN = Regex("<!ENTITY\\b", RegexOption.IGNORE_CASE)
    private val SAFE_EPUB_DOCTYPE = Regex(
        """<!DOCTYPE\s+html\s*(?:PUBLIC\s+[\"']-//W3C//DTD\s+XHTML\s+""" +
            """(?:1\.1|1\.0\s+(?:Strict|Transitional|Frameset))//EN[\"']\s+""" +
            """[\"']https?://www\.w3\.org/TR/(?:xhtml11/DTD/xhtml11\.dtd|""" +
            """xhtml1/DTD/xhtml1-(?:strict|transitional|frameset)\.dtd)[\"'])?\s*>""",
        RegexOption.IGNORE_CASE,
    )
    private val STANDARD_ENTITY_REFERENCE = Regex("&nbsp;")
}
