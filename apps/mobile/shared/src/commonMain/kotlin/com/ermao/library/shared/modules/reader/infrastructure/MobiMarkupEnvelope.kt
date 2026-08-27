package com.ermao.library.shared.modules.reader.infrastructure

/** Repairs only the XML envelope of libmobi's legacy HTML, never its locator body. */
class MobiMarkupEnvelope {
    @Throws(IllegalArgumentException::class)
    fun prepare(markup: String): String {
        require(markup.length in 1..64 * 1024 * 1024) { "MOBI markup exceeds the size limit" }
        val root = ROOT.find(markup) ?: return markup
        val tag = root.groups[1] ?: return markup
        val attributes = tag.value
        val declarations = buildString {
            if (!DEFAULT_NAMESPACE.containsMatchIn(attributes)) append(" xmlns=\"http://www.w3.org/1999/xhtml\"")
            if (!MBP_NAMESPACE.containsMatchIn(attributes)) append(" xmlns:mbp=\"urn:shuku:mobipocket\"")
        }
        if (declarations.isEmpty()) return markup
        val opening = attributes.dropLast(1) + declarations + ">"
        return markup.replaceRange(tag.range, opening)
    }

    private companion object {
        // Anchor to the real root: a fake <html> in a comment or CDATA must never match.
        val ROOT = Regex("""^\s*(?:<\?xml\b[^?]*\?>\s*)?(<html\b[^>]*>)""", RegexOption.IGNORE_CASE)
        val DEFAULT_NAMESPACE = Regex("""\sxmlns\s*=""", RegexOption.IGNORE_CASE)
        val MBP_NAMESPACE = Regex("""\sxmlns:mbp\s*=""", RegexOption.IGNORE_CASE)
    }
}
