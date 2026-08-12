package com.ermao.library.features.reader.infrastructure

import org.jsoup.Jsoup
import org.jsoup.nodes.Document
import org.jsoup.parser.Parser
import org.readium.r2.shared.util.Try
import org.readium.r2.shared.util.data.Container
import org.readium.r2.shared.util.resource.Resource
import org.readium.r2.shared.util.resource.TransformingContainer
import org.readium.r2.shared.util.resource.TransformingResource

internal object EpubContentSecurityPolicy {
    fun apply(container: Container<Resource>): Container<Resource> = TransformingContainer(container) { url, resource ->
        if (url.path?.substringAfterLast('.', missingDelimiterValue = "")?.lowercase() in HTML_EXTENSIONS) {
            TransformingResource(resource) { bytes ->
                Try.success(sanitizeHtml(bytes))
            }
        } else {
            resource
        }
    }

    internal fun sanitizeHtml(bytes: ByteArray): ByteArray {
        val document = Jsoup.parse(bytes.toString(Charsets.UTF_8), "", Parser.xmlParser())
        document.outputSettings().syntax(Document.OutputSettings.Syntax.xml)
        document.select("script, iframe, object, embed, meta[http-equiv=refresh]").remove()
        document.allElements.forEach { element ->
            element.attributes().asList()
                .filter { attribute -> attribute.key.startsWith("on", ignoreCase = true) }
                .forEach { attribute -> element.removeAttr(attribute.key) }

            URL_ATTRIBUTES.forEach { attribute ->
                val value = element.attr(attribute).trim()
                if (value.isEmpty()) return@forEach
                val isExternalAnchor = element.normalName() == "a" && attribute == "href" && value.isSafeExternalUrl()
                if (!isExternalAnchor && value.isUnsafeResourceUrl()) element.removeAttr(attribute)
                if (value.isDangerousScheme()) element.removeAttr(attribute)
            }
        }
        document.select("style").forEach { style ->
            style.text(style.data().removeRemoteCssReferences())
        }
        document.select("[style]").forEach { element ->
            element.attr("style", element.attr("style").removeRemoteCssReferences())
        }
        return document.outerHtml().toByteArray(Charsets.UTF_8)
    }

    private fun String.isUnsafeResourceUrl(): Boolean {
        val normalized = lowercase()
        return normalized.startsWith("http:") ||
            normalized.startsWith("https:") ||
            normalized.startsWith("//") ||
            normalized.startsWith("file:") ||
            normalized.startsWith("content:")
    }

    private fun String.isDangerousScheme(): Boolean {
        val normalized = lowercase()
        return normalized.startsWith("javascript:") ||
            normalized.startsWith("file:") ||
            normalized.startsWith("content:") ||
            normalized.startsWith("intent:")
    }

    private fun String.isSafeExternalUrl(): Boolean {
        val normalized = lowercase()
        return normalized.startsWith("https:") || normalized.startsWith("http:")
    }

    private fun String.removeRemoteCssReferences(): String =
        replace(REMOTE_CSS_URL, "url()")
            .replace(REMOTE_CSS_IMPORT, "")

    private val HTML_EXTENSIONS = setOf("html", "xhtml", "htm")
    private val URL_ATTRIBUTES = setOf("href", "src", "xlink:href", "poster", "action", "formaction")
    private val REMOTE_CSS_URL = Regex("url\\s*\\(\\s*['\"]?(?:https?:)?//[^)]*\\)", RegexOption.IGNORE_CASE)
    private val REMOTE_CSS_IMPORT = Regex("@import\\s+(?:url\\s*\\()?['\"]?(?:https?:)?//[^;]+;", RegexOption.IGNORE_CASE)
}
