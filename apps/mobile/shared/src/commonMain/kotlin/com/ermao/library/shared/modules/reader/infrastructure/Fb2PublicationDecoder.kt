package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.modules.reader.domain.ReaderSafetyBudgetName
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyFacade
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyPolicy
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyRuleId

/** XML is read by the platform; this adapter owns the server's FB2 v1 virtual resource contract. */
data class Fb2EmbeddedImage(val identifier: String, val mediaType: String, val encoded: String)
data class Fb2ImageLink(val identifier: String, val href: String, val mediaType: String)
data class Fb2TextResource(val href: String, val title: String, val xhtml: String)
data class Fb2NavigationEntry(val href: String, val title: String, val children: List<Fb2NavigationEntry>)
data class Fb2PublicationDocument(
    val title: String,
    val language: String?,
    val resources: List<Fb2TextResource>,
    val tableOfContents: List<Fb2NavigationEntry>,
    val images: List<Fb2ImageLink>,
    val stylesheetHref: String = "fb2/reader.css",
    val stylesheet: String = FB2_STYLESHEET,
)

class Fb2XmlPolicy {
    /** An ISO-8859-1 byte-preserving probe, never a decoding of publication text. */
    @Throws(IllegalArgumentException::class)
    fun prepare(probe: String): String {
        require(probe.isNotEmpty()) { "FB2 source is empty" }
        if (Regex("<!DOCTYPE\\b|<!ENTITY\\b", RegexOption.IGNORE_CASE)
            .containsMatchIn(probe.replace("\u0000", ""))
        ) {
            ReaderSafetyFacade().reject(ReaderSafetyRuleId.REFLOWABLE_REJECT_XML_ENTITY)
        }
        if (Regex("\\bxmlns:l\\s*=").containsMatchIn(probe) ||
            !Regex("\\bxmlns:xlink\\s*=\\s*(['\"])http://www\\.w3\\.org/1999/xlink\\1")
                .containsMatchIn(probe)
        ) return probe
        // The original file stays untouched. Only the documented legacy XLink attribute is repaired.
        return Regex("(\\s)l:href(\\s*=)").replace(probe) { "${it.groupValues[1]}xlink:href${it.groupValues[2]}" }
    }
}

/** One instance per parse; bounded mixed content preserves inline text, images, tables and notes. */
class Fb2PublicationDecoder {
    private val stack = mutableListOf<Fb2Element>()
    private var root: Fb2Element? = null
    private var elementCount = 0L
    private var characterCount = 0L
    private var textByteCount = 0L

    @Throws(IllegalArgumentException::class)
    fun startElement(name: String, attributes: Map<String, String>) {
        val maxDepth = ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.FB2_MAX_DEPTH)
        val maxNodes = ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.FB2_MAX_NODES)
        if (stack.size.toLong() >= maxDepth || elementCount >= maxNodes) {
            ReaderSafetyFacade().reject(ReaderSafetyRuleId.FB2_STRUCTURE_BUDGET)
        }
        elementCount += 1
        if (stack.isEmpty()) require(root == null && name == "FictionBook") { "FB2 root is invalid" }
        val element = Fb2Element(name, attributes.toMap())
        stack.lastOrNull()?.content?.add(element) ?: run { root = element }
        stack += element
    }

    @Throws(IllegalArgumentException::class)
    fun text(value: String) {
        val characterLimit = ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.FB2_TEXT_MAX_CHARACTERS)
        val byteLimit = ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.FB2_TEXT_MAX_BYTES)
        val nextCharacters = value.length.toLong()
        val nextBytes = value.encodeToByteArray().size.toLong()
        if (nextCharacters > characterLimit - characterCount || nextBytes > byteLimit - textByteCount) {
            ReaderSafetyFacade().reject(ReaderSafetyRuleId.FB2_STRUCTURE_BUDGET)
        }
        characterCount += nextCharacters
        textByteCount += nextBytes
        val parent = stack.lastOrNull() ?: return
        val previous = parent.content.lastOrNull()
        if (previous is Fb2Text) previous.value.append(value) else parent.content += Fb2Text(StringBuilder(value))
    }

    @Throws(IllegalArgumentException::class)
    fun endElement(name: String) {
        require(stack.lastOrNull()?.name == name) { "FB2 XML nesting is invalid" }
        stack.removeAt(stack.lastIndex)
    }

    @Throws(IllegalArgumentException::class)
    fun embeddedImages(): List<Fb2EmbeddedImage> {
        val seen = mutableSetOf<String>()
        return completedRoot().children("binary").mapNotNull { element ->
            val identifier = element.attribute("id").orEmpty().trim()
            val mediaType = element.attribute("content-type").orEmpty().trim().lowercase()
            if (identifier.isEmpty() || ReaderSafetyPolicy.fb2EmbeddedImageExtension(mediaType) == null) {
                return@mapNotNull null
            }
            require(seen.add(identifier)) { "FB2 binary identifier is duplicated" }
            val encoded = element.plainText().filterNot(Char::isWhitespace)
            if (encoded.length.toLong() >
                ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.FB2_ENCODED_IMAGE_MAX_BYTES)
            ) {
                return@mapNotNull null
            }
            Fb2EmbeddedImage(identifier, mediaType, encoded)
        }
    }

    @Throws(IllegalArgumentException::class)
    fun finish(fallbackTitle: String, images: List<Fb2ImageLink>): Fb2PublicationDocument {
        val document = completedRoot()
        val titleInfo = document.descendant("description")?.descendant("title-info")
        val title = titleInfo?.descendant("book-title")?.normalizedText()?.takeIf(String::isNotEmpty)
            ?: fallbackTitle
        val language = titleInfo?.descendant("lang")?.normalizedText()?.takeIf(String::isNotEmpty)
        val embeddedImages = embeddedImages().associateBy(Fb2EmbeddedImage::identifier)
        val imageHrefs = images.associate { it.identifier to it.href }
        require(imageHrefs.size == images.size && images.all { image ->
            embeddedImages[image.identifier]?.mediaType == image.mediaType
        }) {
            "FB2 images were not validated"
        }
        require(images.all { image ->
            val extension = ReaderSafetyPolicy.fb2EmbeddedImageExtension(image.mediaType)
                ?: return@all false
            Regex("fb2/images/[a-f0-9]{20}${Regex.escape(extension)}").matches(image.href)
        }) {
            "FB2 image path is invalid"
        }
        val renderer = Fb2Renderer(imageHrefs)
        val sections = renderer.sections(document, title)
        require(sections.isNotEmpty()) { "FB2 reading order is empty" }
        return Fb2PublicationDocument(
            title = title,
            language = language,
            resources = sections.map { section ->
                Fb2TextResource(section.href, section.title, """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="${(language ?: "und").fb2Escaped()}">
<head><meta charset="utf-8"/><title>${section.title.fb2Escaped()}</title>
<link rel="stylesheet" type="text/css" href="reader.css"/></head>
<body>${renderer.render(section, 1)}</body></html>""")
            },
            tableOfContents = sections.map(Fb2Section::navigation),
            images = images.toList(),
        )
    }

    private fun completedRoot(): Fb2Element {
        require(stack.isEmpty()) { "FB2 XML is incomplete" }
        return requireNotNull(root) { "FB2 XML is empty" }
    }
}

private sealed interface Fb2Content
private class Fb2Text(val value: StringBuilder) : Fb2Content
private class Fb2Element(val name: String, val attributes: Map<String, String>) : Fb2Content {
    val content = mutableListOf<Fb2Content>()
    fun children(name: String): List<Fb2Element> = content.filterIsInstance<Fb2Element>().filter { it.name == name }
    fun attribute(name: String): String? = attributes.entries.firstOrNull { it.key.substringAfterLast(':') == name }?.value
    fun descendants(): Sequence<Fb2Element> = sequence {
        yield(this@Fb2Element)
        content.filterIsInstance<Fb2Element>().forEach { yieldAll(it.descendants()) }
    }
    fun descendant(name: String): Fb2Element? = descendants().firstOrNull { it.name == name }
    fun plainText(): String = buildString { appendTextTo(this) }
    private fun appendTextTo(target: StringBuilder) {
        content.forEach { when (it) {
            is Fb2Text -> target.append(it.value)
            is Fb2Element -> it.appendTextTo(target)
        } }
    }
    fun normalizedText(): String = plainText().map { if (it.isWhitespace() || it == '\u0085') ' ' else it }
        .joinToString("").splitToSequence(' ').filter(String::isNotEmpty).joinToString(" ")
}

private data class Fb2Section(
    val element: Fb2Element,
    val href: String,
    val anchor: String,
    val title: String,
    val children: List<Fb2Section>,
) {
    fun navigation(): Fb2NavigationEntry = Fb2NavigationEntry("$href#$anchor", title, children.map(Fb2Section::navigation))
}

private class Fb2Renderer(private val imageHrefs: Map<String, String>) {
    private val anchors = mutableMapOf<Fb2Element, String>()
    private val targets = mutableMapOf<String, String>()
    private var sectionCount = 0

    private fun anchor(element: Fb2Element, href: String): String = anchors.getOrPut(element) {
        if (anchors.size.toLong() >= ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.FB2_MAX_NODES)) {
            ReaderSafetyFacade().reject(ReaderSafetyRuleId.FB2_STRUCTURE_BUDGET)
        }
        val anchor = "fb2-node-${(anchors.size + 1).toString().padStart(6, '0')}"
        element.attribute("id")?.trim()?.takeIf(String::isNotEmpty)?.let { identifier ->
            require(identifier !in targets) { "FB2 identifier is duplicated" }
            targets[identifier] = "$href#$anchor"
        }
        anchor
    }

    fun sections(root: Fb2Element, title: String): List<Fb2Section> = buildList {
        root.children("body").forEach { body ->
            body.children("section").ifEmpty { listOf(body) }.forEach { element ->
                val href = "fb2/section-${(size + 1).toString().padStart(4, '0')}.xhtml"
                add(section(element, href, "$title ${size + 1}"))
                element.descendants().filter { it.attribute("id") != null }.forEach { anchor(it, href) }
            }
        }
    }

    private fun section(element: Fb2Element, href: String, fallback: String): Fb2Section {
        sectionCount += 1
        if (sectionCount.toLong() > ReaderSafetyPolicy.budget(ReaderSafetyBudgetName.FB2_MAX_NODES)) {
            ReaderSafetyFacade().reject(ReaderSafetyRuleId.FB2_STRUCTURE_BUDGET)
        }
        val anchor = anchor(element, href)
        val title = element.children("title").firstOrNull()?.normalizedText()?.takeIf(String::isNotEmpty) ?: fallback
        return Fb2Section(element, href, anchor, title, element.children("section").mapIndexed { index, child ->
            section(child, href, "$title ${index + 1}")
        })
    }

    fun render(section: Fb2Section, depth: Int): String = buildString {
        val heading = depth.coerceAtMost(6)
        append("<section id=\"${section.anchor}\"><h$heading>${section.title.fb2Escaped()}</h$heading>")
        section.element.content.filterIsInstance<Fb2Element>()
            .filter { it.name !in setOf("title", "section") }.forEach { append(renderElement(it)) }
        section.children.forEach { append(render(it, depth + 1)) }
        append("</section>")
    }

    private fun renderElement(element: Fb2Element): String {
        val name = element.name
        if (name in setOf("section", "title", "binary")) return ""
        if (name == "empty-line") return "<br/>"
        if (name == "image") {
            val href = imageHrefs[element.attribute("href").orEmpty().removePrefix("#")] ?: return ""
            return "<img src=\"${href.removePrefix("fb2/").fb2Escaped()}\" alt=\"\"/>"
        }
        val content = element.content.joinToString("") { when (it) {
            is Fb2Text -> it.value.toString().fb2Escaped()
            is Fb2Element -> renderElement(it)
        } }
        if (name == "a") {
            val target = targets[element.attribute("href").orEmpty().removePrefix("#")] ?: return content
            return "<a href=\"${target.removePrefix("fb2/").fb2Escaped()}\">$content</a>"
        }
        val tag = ELEMENT_TAGS[name] ?: return content
        val id = anchors[element]?.let { " id=\"$it\"" }.orEmpty()
        val style = if (name == "stanza") " class=\"stanza\"" else ""
        return "<$tag$id$style>$content</$tag>"
    }
}

private fun String.fb2Escaped(): String = replace("&", "&amp;").replace("<", "&lt;")
    .replace(">", "&gt;").replace("\"", "&quot;").replace("'", "&apos;")

private val ELEMENT_TAGS = mapOf(
    "p" to "p", "subtitle" to "h3", "emphasis" to "em", "strong" to "strong",
    "strikethrough" to "s", "sub" to "sub", "sup" to "sup", "code" to "code",
    "poem" to "blockquote", "cite" to "blockquote", "epigraph" to "blockquote", "annotation" to "aside",
    "stanza" to "div", "v" to "p", "text-author" to "p", "table" to "table",
    "tr" to "tr", "th" to "th", "td" to "td",
)
private const val FB2_STYLESHEET = """body {
  margin: 0; padding: 1rem; line-height: 1.6; overflow-wrap: anywhere;
}
section { margin: 0 0 2rem; } h1,h2,h3,h4,h5,h6 { line-height: 1.3; }
p { margin: 0 0 1em; } img { max-width: 100%; height: auto; }
blockquote { margin: 1em 1.5em; } .stanza { margin: 1em 0; }
"""
