package com.ermao.library.shared.modules.reader.domain

/** A stable security finding that can cross the Kotlin/native boundary safely. */
data class ReaderSafetyFailure(
    val ruleId: String,
    val errorCode: String,
) {
    init {
        require(ruleId.isNotBlank()) { "Reader safety rule id is blank" }
        require(errorCode.isNotBlank()) { "Reader safety error code is blank" }
    }
}

/** A required policy algorithm that the selected engine or platform cannot implement. */
data class ReaderSafetyImplementationFailure(
    val ruleId: String,
    val errorCode: String,
) {
    init {
        require(ruleId.isNotBlank()) { "Reader safety target rule id is blank" }
        require(errorCode.isNotBlank()) { "Reader safety implementation error code is blank" }
    }
}

/** Sanitized XHTML plus the parser-safe representation used by native XML parsers. */
data class ReaderSanitizedMarkup(
    val markup: String,
    val parserMarkup: String,
    val changed: Boolean,
)

sealed interface ReaderSafetyMarkupResult {
    data class Accepted(val value: ReaderSanitizedMarkup) : ReaderSafetyMarkupResult
    data class Rejected(val failure: ReaderSafetyFailure) : ReaderSafetyMarkupResult
}

/**
 * The one mobile-owned markup detector/action facade. Platform readers only provide their
 * parser and renderer adapters; declaration, body, URI, and CSS findings are decided here.
 */
class ReaderSafetyFacade {
    fun sanitizeMarkup(markup: String, sourceByteCount: Long = -1L): ReaderSafetyMarkupResult {
        val prepared = when (val result = prepareXmlMarkup(markup, sourceByteCount)) {
            is ReaderSafetyMarkupResult.Accepted -> result.value
            is ReaderSafetyMarkupResult.Rejected -> return result
        }
        var sanitized = prepared.markup
        sanitized = sanitizeElements(sanitized, ReaderSafetyPolicy.reflowableProfile.sanitizedElements)
        sanitized = sanitizeElements(sanitized, ReaderSafetyPolicy.reflowableProfile.svgSanitizedElements)
        sanitized = sanitizeMetaElements(sanitized)
        sanitized = sanitizeAttributes(sanitized)
        sanitized = sanitizeStyleElements(sanitized)
        return ReaderSafetyMarkupResult.Accepted(
            ReaderSanitizedMarkup(
                markup = sanitized,
                parserMarkup = replaceGeneratedEntitiesForParsing(sanitized),
                changed = prepared.changed || sanitized != prepared.markup,
            ),
        )
    }

    /**
     * Prepares a reflowable reading-order resource for an XML parser. This is deliberately
     * separate from the HTML sanitizer: the parser copy may remove DTD dependencies and
     * literalize entity references while the verified publication remains untouched.
     */
    fun prepareXmlMarkup(markup: String, sourceByteCount: Long = -1L): ReaderSafetyMarkupResult =
        prepareXml(
            markup = markup,
            sourceByteCount = sourceByteCount,
            maximumBytes = budget("reflowableMarkupMaxBytes"),
            sizeRule = ReaderSafetyRuleId.REFLOWABLE_MARKUP_MAX_BYTES,
        )

    /** Prepares a bounded EPUB/FB2 XML control document such as OPF, NCX, or container.xml. */
    fun prepareXmlControlDocument(
        markup: String,
        sourceByteCount: Long = -1L,
    ): ReaderSafetyMarkupResult = prepareXml(
        markup = markup,
        sourceByteCount = sourceByteCount,
        maximumBytes = budget("xmlControlDocumentMaxBytes"),
        sizeRule = ReaderSafetyRuleId.REFLOWABLE_XML_CONTROL_DOCUMENT_MAX_BYTES,
    )

    /** Returns the first real element after lexical comments, CDATA, PIs and DTDs are masked. */
    fun rootElementName(markup: String): String? {
        val prepared = when (val result = prepareXmlMarkup(markup)) {
            is ReaderSafetyMarkupResult.Accepted -> result.value.markup
            is ReaderSafetyMarkupResult.Rejected -> return null
        }
        return ROOT_ELEMENT.find(NON_MARKUP.replace(prepared) { " ".repeat(it.value.length) })
            ?.groups?.get("name")?.value?.lowercase()
    }

    /** Applies the generated CSS sanitizer to a standalone stylesheet in memory. */
    fun sanitizeCss(css: String, sourceByteCount: Long = -1L): ReaderSafetyMarkupResult {
        val wrapped = "<style>$css</style>"
        return when (val result = sanitizeMarkup(wrapped, sourceByteCount)) {
            is ReaderSafetyMarkupResult.Rejected -> result
            is ReaderSafetyMarkupResult.Accepted -> {
                val body = STYLE_ELEMENT.find(result.value.markup)
                    ?.groups?.get("body")?.value
                    ?: return ReaderSafetyMarkupResult.Rejected(failureFor(ReaderSafetyRuleId.REFLOWABLE_SANITIZE_CSS))
                ReaderSafetyMarkupResult.Accepted(
                    ReaderSanitizedMarkup(
                        markup = body,
                        parserMarkup = body,
                        changed = body != css,
                    ),
                )
            }
        }
    }

    /** Classifies an authored user-navigation URL using the generated URI policy. */
    fun allowsAuthoredUserNavigation(value: String): Boolean = !isUnsafeUserNavigation(value)

    fun requirePreparedXmlMarkup(markup: String, sourceByteCount: Long = -1L): ReaderSanitizedMarkup =
        when (val result = prepareXmlMarkup(markup, sourceByteCount)) {
            is ReaderSafetyMarkupResult.Accepted -> result.value
            is ReaderSafetyMarkupResult.Rejected -> throw ReaderSafetyException(result.failure)
        }

    fun requirePreparedXmlControlDocument(
        markup: String,
        sourceByteCount: Long = -1L,
    ): ReaderSanitizedMarkup = when (val result = prepareXmlControlDocument(markup, sourceByteCount)) {
        is ReaderSafetyMarkupResult.Accepted -> result.value
        is ReaderSafetyMarkupResult.Rejected -> throw ReaderSafetyException(result.failure)
    }

    /**
     * Extracts EPUB package document references from a safely prepared container.xml.
     *
     * This is reference extraction only. XML well-formedness and readability remain the native
     * publication parser's responsibility after [requirePreparedXmlControlDocument] has removed
     * parser dependencies and literalized unsafe entity references.
     */
    fun requireContainerRootFilePaths(
        markup: String,
        sourceByteCount: Long = -1L,
    ): List<String> {
        val prepared = requirePreparedXmlControlDocument(markup, sourceByteCount).parserMarkup
        val masked = maskNonMarkup(prepared)
        return ROOTFILE_TAG.findAll(masked).mapNotNull { match ->
            val tag = prepared.substring(match.range)
            ATTRIBUTE.findAll(tag)
                .firstOrNull { attribute ->
                    attribute.groups["name"]?.value?.substringAfterLast(':')
                        ?.equals("full-path", ignoreCase = true) == true
                }
                ?.let { attribute ->
                    attribute.groups["double"]?.value
                        ?: attribute.groups["single"]?.value
                        ?: attribute.groups["bare"]?.value
                }
                ?.let(::decodeXmlAttributeValue)
                ?.trim()
                ?.takeIf(String::isNotEmpty)
        }.toList()
    }

    fun requireSanitizedMarkup(markup: String, sourceByteCount: Long = -1L): ReaderSanitizedMarkup =
        when (val result = sanitizeMarkup(markup, sourceByteCount)) {
            is ReaderSafetyMarkupResult.Accepted -> result.value
            is ReaderSafetyMarkupResult.Rejected ->
                throw ReaderSafetyException(result.failure)
        }

    fun failureFor(rule: ReaderSafetyRuleId): ReaderSafetyFailure {
        val errorCode = ReaderSafetyPolicy.rule(rule).errorCode
            ?: error("Reader safety blocking rule has no error code: ${rule.wireValue}")
        return ReaderSafetyFailure(rule.wireValue, errorCode.name)
    }

    fun reject(rule: ReaderSafetyRuleId): Nothing =
        throw ReaderSafetyException(failureFor(rule))

    fun platformFailureFor(rule: ReaderSafetyRuleId): ReaderSafetyImplementationFailure =
        implementationFailureFor(
            rule = rule,
            errorCode = ReaderSafetyErrorCode.PLATFORM_POLICY_ALGORITHM_UNSUPPORTED,
        )

    fun engineFailureFor(rule: ReaderSafetyRuleId): ReaderSafetyImplementationFailure =
        implementationFailureFor(
            rule = rule,
            errorCode = ReaderSafetyErrorCode.ENGINE_POLICY_ALGORITHM_UNSUPPORTED,
        )

    fun rejectUnsupportedPlatformAlgorithm(rule: ReaderSafetyRuleId): Nothing =
        throw ReaderSafetyImplementationException(platformFailureFor(rule))

    private fun implementationFailureFor(
        rule: ReaderSafetyRuleId,
        errorCode: ReaderSafetyErrorCode,
    ): ReaderSafetyImplementationFailure {
        check(errorCode in ReaderSafetyPolicy.implementationFailureCodes)
        return ReaderSafetyImplementationFailure(rule.wireValue, errorCode.name)
    }

    private fun rejected(rule: ReaderSafetyRuleId): ReaderSafetyMarkupResult.Rejected =
        ReaderSafetyMarkupResult.Rejected(failureFor(rule))

    private fun prepareXml(
        markup: String,
        sourceByteCount: Long,
        maximumBytes: Long,
        sizeRule: ReaderSafetyRuleId,
    ): ReaderSafetyMarkupResult {
        if (markup.isEmpty() || markup.isBlank()) {
            return rejected(ReaderSafetyRuleId.REFLOWABLE_REQUIRED_READING_ORDER_MARKUP)
        }
        val measuredBytes = if (sourceByteCount >= 0) {
            maxOf(sourceByteCount, markup.encodeToByteArray().size.toLong())
        } else {
            markup.encodeToByteArray().size.toLong()
        }
        if (measuredBytes > maximumBytes) return rejected(sizeRule)

        val preparation = XmlControlPreprocessor(
            namedEntityCodepoints = ReaderSafetyPolicy.reflowableProfile.namedEntityCodepoints,
            maximumExpansionBytes = maximumBytes,
        ).prepare(markup)
        return ReaderSafetyMarkupResult.Accepted(
            ReaderSanitizedMarkup(
                markup = preparation.markup,
                parserMarkup = replaceGeneratedEntitiesForParsing(preparation.markup),
                changed = preparation.changed,
            ),
        )
    }

    private fun sanitizeAttributes(markup: String): String {
        val output = StringBuilder(markup.length)
        var cursor = 0
        while (cursor < markup.length) {
            val opening = markup.indexOf('<', cursor)
            if (opening < 0) {
                output.append(markup, cursor, markup.length)
                break
            }
            output.append(markup, cursor, opening)
            val next = markup.getOrNull(opening + 1)
            if (next == null || next == '/' || next == '!' || next == '?') {
                output.append('<')
                cursor = opening + 1
                continue
            }
            val closing = findTagEnd(markup, opening + 1)
            if (closing < 0) {
                output.append(markup, opening, markup.length)
                break
            }
            val tag = markup.substring(opening, closing + 1)
            val rawElement = TAG_NAME.find(tag)?.groups?.get("name")?.value
            if (rawElement == null) {
                output.append(tag)
            } else {
                output.append(sanitizeOpeningTag(tag, rawElement.substringAfterLast(':').lowercase()))
            }
            cursor = closing + 1
        }
        return output.toString()
    }

    private fun findTagEnd(markup: String, start: Int): Int {
        var quote: Char? = null
        for (index in start until markup.length) {
            val character = markup[index]
            if (quote != null) {
                if (character == quote) quote = null
            } else if (character == '\'' || character == '"') {
                quote = character
            } else if (character == '>') {
                return index
            }
        }
        return -1
    }

    private fun sanitizeOpeningTag(tag: String, element: String): String = ATTRIBUTE.replace(tag) { match ->
        val originalName = match.groups["name"]?.value ?: return@replace match.value
        val name = originalName.lowercase()
        val value = match.groups["double"]?.value
            ?: match.groups["single"]?.value
            ?: match.groups["bare"]?.value
            ?: ""
        val profile = ReaderSafetyPolicy.reflowableProfile
        if (name in profile.sanitizedAttributes ||
            profile.sanitizedAttributePrefixes.any { prefix -> name.startsWith(prefix.lowercase()) }
        ) {
            return@replace ""
        }
        val policy = profile.uriAttributePolicies.firstOrNull { candidate ->
            candidate.attribute.equals(name, ignoreCase = true) &&
                candidate.elements.any { allowed -> allowed == "*" || allowed.equals(element, ignoreCase = true) }
        } ?: return@replace match.value
        val replacement = sanitizeUriAttribute(value, policy)
            ?: return@replace ""
        if (replacement == value) return@replace match.value
        " $originalName=\"${escapeAttributeValue(replacement)}\""
    }

    private fun sanitizeUriAttribute(
        value: String,
        policy: ReaderSafetyUriAttributePolicy,
    ): String? = when (policy.purpose) {
        ReaderSafetyUriPurpose.ALWAYS_REMOVE -> null
        ReaderSafetyUriPurpose.USER_NAVIGATION ->
            value.takeUnless(::isUnsafeUserNavigation)
        ReaderSafetyUriPurpose.SUBRESOURCE -> when (policy.syntax) {
            ReaderSafetyUriSyntax.SCALAR -> value.takeUnless(::isUnsafeSubresource)
            ReaderSafetyUriSyntax.SRCSET -> value.split(',').mapNotNull { component ->
                val candidate = component.trim()
                val url = candidate.split(WHITESPACE, limit = 2).firstOrNull().orEmpty()
                candidate.takeIf { url.isNotEmpty() && !isUnsafeSubresource(url) }
            }.takeIf { it.isNotEmpty() }?.joinToString(", ")
            ReaderSafetyUriSyntax.SPACE_SEPARATED -> value.split(WHITESPACE).filter { candidate ->
                candidate.isNotEmpty() && !isUnsafeSubresource(candidate)
            }.takeIf { it.isNotEmpty() }?.joinToString(" ")
            ReaderSafetyUriSyntax.CSS -> sanitizeCss(value).takeIf(String::isNotBlank)
        }
    }

    private fun isUnsafeSubresource(value: String): Boolean {
        val candidate = value.trim()
        if (candidate.isEmpty() || candidate.startsWith('#')) return false
        if (candidate.startsWith("//")) return true
        val scheme = authoredScheme(candidate) ?: return false
        val profile = ReaderSafetyPolicy.reflowableProfile
        return scheme in profile.blockedAuthorSchemes || scheme in profile.remoteSubresourceSchemes
    }

    private fun isUnsafeUserNavigation(value: String): Boolean {
        val candidate = value.trim()
        if (candidate.isEmpty() || candidate.startsWith('#')) return false
        if (candidate.startsWith("//")) return true
        val scheme = authoredScheme(candidate) ?: return false
        return scheme in ReaderSafetyPolicy.reflowableProfile.blockedAuthorSchemes
    }

    private fun authoredScheme(value: String): String? {
        val colon = value.indexOf(':')
        if (colon <= 0) return null
        val boundary = listOf(value.indexOf('/'), value.indexOf('?'), value.indexOf('#'))
            .filter { it >= 0 }
            .minOrNull() ?: Int.MAX_VALUE
        if (colon > boundary) return null
        return value.substring(0, colon).replace(CONTROL_OR_SPACE, "").lowercase()
    }

    private fun escapeAttributeValue(value: String): String =
        value.replace("\"", "&quot;").replace("<", "&lt;")

    private fun sanitizeStyleElements(markup: String): String = STYLE_ELEMENT.replace(markup) { match ->
        val bodyGroup = match.groups["body"] ?: return@replace match.value
        val sanitized = sanitizeCss(bodyGroup.value)
        val relativeStart = match.value.indexOf(bodyGroup.value, startIndex = match.value.indexOf('>') + 1)
        if (relativeStart < 0) return@replace match.value
        val relativeEnd = relativeStart + bodyGroup.value.length
        match.value.replaceRange(relativeStart, relativeEnd, sanitized)
    }

    private fun sanitizeCss(value: String): String {
        var sanitized = value
        for (construct in ReaderSafetyPolicy.reflowableProfile.cssSanitizedConstructs) {
            sanitized = when (construct) {
                "REMOTE_IMPORT" -> CSS_IMPORT.replace(sanitized) { match ->
                    val url = match.groups["quoted"]?.value ?: match.groups["bare"]?.value.orEmpty()
                    if (isUnsafeSubresource(url)) "" else match.value
                }
                "REMOTE_URL" -> CSS_URL.replace(sanitized) { match ->
                    val url = match.groups["quoted"]?.value ?: match.groups["bare"]?.value.orEmpty()
                    if (isUnsafeSubresource(url)) "url(\"\")" else match.value
                }
                "EXPRESSION" -> removeCssDeclarations(sanitized, CSS_EXPRESSION_DECLARATION)
                "BEHAVIOR" -> removeCssDeclarations(sanitized, CSS_BEHAVIOR_DECLARATION)
                "MOZ_BINDING" -> removeCssDeclarations(sanitized, CSS_MOZ_BINDING_DECLARATION)
                else -> rejectUnsupportedPlatformAlgorithm(
                    ReaderSafetyRuleId.REFLOWABLE_SANITIZE_CSS,
                )
            }
        }
        if (cssHasActiveConstruct(sanitized)) return ""
        var previous: String
        do {
            previous = sanitized
            sanitized = EMPTY_CSS_RULE.replace(sanitized, "")
        } while (sanitized != previous)
        return sanitized
    }

    private fun removeCssDeclarations(source: String, pattern: Regex): String =
        pattern.replace(source) { match ->
            val prefix = match.groups["prefix"]?.value.orEmpty()
            val terminator = match.groups["terminator"]?.value.orEmpty()
            prefix + terminator.takeIf { it == "}" }.orEmpty()
        }

    private fun cssHasActiveConstruct(source: String): Boolean {
        val normalized = decodeCssForDetection(source).lowercase()
        return ReaderSafetyPolicy.reflowableProfile.cssSanitizedConstructs.any { construct ->
            when (construct) {
                "REMOTE_IMPORT" -> CSS_IMPORT.findAll(normalized).any { match ->
                    val url = match.groups["quoted"]?.value ?: match.groups["bare"]?.value.orEmpty()
                    isUnsafeSubresource(url)
                }
                "REMOTE_URL" -> CSS_URL.findAll(normalized).any { match ->
                    val url = match.groups["quoted"]?.value ?: match.groups["bare"]?.value.orEmpty()
                    isUnsafeSubresource(url)
                }
                "EXPRESSION" -> CSS_EXPRESSION.containsMatchIn(normalized)
                "BEHAVIOR" -> CSS_BEHAVIOR.containsMatchIn(normalized)
                "MOZ_BINDING" -> CSS_MOZ_BINDING.containsMatchIn(normalized)
                else -> rejectUnsupportedPlatformAlgorithm(
                    ReaderSafetyRuleId.REFLOWABLE_SANITIZE_CSS,
                )
            }
        }
    }

    private fun decodeCssForDetection(source: String): String = CSS_ESCAPE.replace(source) { match ->
        val hexadecimal = match.groups["hex"]?.value
        if (hexadecimal != null) {
            hexadecimal.toIntOrNull(16)?.takeIf { it in 1..0x7f }?.toChar()?.toString().orEmpty()
        } else {
            match.groups["escaped"]?.value.orEmpty()
        }
    }

    private fun replaceGeneratedEntitiesForParsing(markup: String): String {
        fun replaceMarkup(segment: String): String = NAMED_ENTITY_REFERENCE.replace(segment) { match ->
            val name = match.groups["name"]?.value ?: return@replace match.value
            val codepoint = ReaderSafetyPolicy.reflowableProfile.namedEntityCodepoints[name]
                ?: return@replace match.value
            "&#$codepoint;"
        }

        val output = StringBuilder(markup.length)
        var cursor = 0
        NON_MARKUP.findAll(markup).forEach { match ->
            output.append(replaceMarkup(markup.substring(cursor, match.range.first)))
            output.append(match.value)
            cursor = match.range.last + 1
        }
        output.append(replaceMarkup(markup.substring(cursor)))
        return output.toString()
    }

    private fun maskNonMarkup(markup: String): String {
        val masked = markup.toCharArray()
        NON_MARKUP.findAll(markup).forEach { match ->
            for (index in match.range) masked[index] = ' '
        }
        return masked.concatToString()
    }

    private fun budget(wireValue: String): Long {
        val name = ReaderSafetyBudgetName.entries.first { it.wireValue == wireValue }
        return ReaderSafetyPolicy.budget(name)
    }

    private fun decodeXmlAttributeValue(value: String): String = XML_ATTRIBUTE_ENTITY.replace(value) { match ->
        val token = match.value.removePrefix("&").removeSuffix(";")
        val codePoint = when {
            token.startsWith("#x", ignoreCase = true) -> token.substring(2).toIntOrNull(16)
            token.startsWith('#') -> token.substring(1).toIntOrNull()
            else -> ReaderSafetyPolicy.reflowableProfile.namedEntityCodepoints[token]
        } ?: return@replace match.value
        if (codePoint !in 0..0x10FFFF || codePoint in 0xD800..0xDFFF) {
            return@replace match.value
        }
        if (codePoint <= 0xFFFF) {
            codePoint.toChar().toString()
        } else {
            val adjusted = codePoint - 0x10000
            buildString {
                append((0xD800 + (adjusted shr 10)).toChar())
                append((0xDC00 + (adjusted and 0x3FF)).toChar())
            }
        }
    }

    private fun sanitizeMetaElements(markup: String): String = META_ELEMENT.replace(markup) { match ->
        val httpEquiv = ATTRIBUTE.findAll(match.value).firstOrNull { attribute ->
            attribute.groups["name"]?.value.equals("http-equiv", ignoreCase = true)
        }?.let { attribute ->
            attribute.groups["double"]?.value
                ?: attribute.groups["single"]?.value
                ?: attribute.groups["bare"]?.value
        }
        if (httpEquiv?.trim()?.lowercase() in ReaderSafetyPolicy.reflowableProfile.sanitizedMetaHttpEquivValues
        ) "" else match.value
    }

    private fun sanitizeElements(markup: String, names: List<String>): String =
        names.filter(String::isNotBlank).fold(markup) { current, name ->
            val escapedName = Regex.escape(name)
            val selfClosing = Regex(
                "(?is)<$escapedName\\b[^>]*/\\s*>",
                RegexOption.IGNORE_CASE,
            )
            val paired = Regex(
                "(?is)<$escapedName\\b[^>]*>.*?</$escapedName\\s*>",
                RegexOption.IGNORE_CASE,
            )
            val withoutSelfClosing = selfClosing.replace(current, "")
            paired.replace(withoutSelfClosing, "")
        }

    private companion object {
        val META_ELEMENT = Regex("<meta\\b[^>]*>?", RegexOption.IGNORE_CASE)
        val STYLE_ELEMENT = Regex(
            "(?is)<style\\b[^>]*>(?<body>.*?)</style\\s*>",
        )
        val ATTRIBUTE = Regex(
            """(?is)\s+(?<name>[A-Za-z_:][\w:.-]*)\s*=\s*(?:"(?<double>[^"]*)"|'(?<single>[^']*)'|(?<bare>[^\s>]+))""",
        )
        val TAG_NAME = Regex("""(?is)^<\s*(?<name>[A-Za-z_][\w:.-]*)""")
        val WHITESPACE = Regex("\\s+")
        val CONTROL_OR_SPACE = Regex("[\\u0000-\\u0020]")
        val NAMED_ENTITY_REFERENCE = Regex("&(?<name>[A-Za-z][A-Za-z0-9]+);")
        val CSS_IMPORT = Regex(
            """(?is)@import\s+(?:url\(\s*)?(?:["'](?<quoted>.*?)["']|(?<bare>[^\s;)]+))\s*\)?[^;]*;""",
        )
        val CSS_URL = Regex(
            """(?is)url\(\s*(?:["'](?<quoted>.*?)["']|(?<bare>(?:[^()]|\([^()]*\))*))\s*\)""",
        )
        val CSS_EXPRESSION = Regex("expression\\s*\\(", RegexOption.IGNORE_CASE)
        val CSS_BEHAVIOR = Regex("\\bbehavior\\s*:", RegexOption.IGNORE_CASE)
        val CSS_MOZ_BINDING = Regex("-moz-binding\\s*:", RegexOption.IGNORE_CASE)
        val CSS_EXPRESSION_DECLARATION = Regex(
            """(?is)(?<prefix>^|[;{])\s*[-A-Za-z_][\w-]*\s*:[^;{}]*expression\s*\([^;{}]*(?<terminator>;|\})""",
        )
        val CSS_BEHAVIOR_DECLARATION = Regex(
            """(?is)(?<prefix>^|[;{])\s*behavior\s*:[^;{}]*(?<terminator>;|\})""",
        )
        val CSS_MOZ_BINDING_DECLARATION = Regex(
            """(?is)(?<prefix>^|[;{])\s*-moz-binding\s*:[^;{}]*(?<terminator>;|\})""",
        )
        val EMPTY_CSS_RULE = Regex("""(?is)[^{}]+\{\s*\}""")
        val CSS_ESCAPE = Regex("""\\(?:(?<hex>[0-9a-fA-F]{1,6})\s?|(?<escaped>.))""")
        val NON_MARKUP = Regex(
            "(?s)<!--.*?-->|<!\\[CDATA\\[.*?]]>|<\\?.*?\\?>",
        )
        val ROOT_ELEMENT = Regex("<\\s*(?!/)(?:[A-Za-z_][\\w.-]*:)?(?<name>[A-Za-z][\\w.-]*)\\b")
        val ROOTFILE_TAG = Regex(
            "(?is)<\\s*(?:[A-Za-z_][\\w.-]*:)?rootfile\\b[^>]*>",
        )
        val XML_ATTRIBUTE_ENTITY = Regex("&(?:#x[0-9A-Fa-f]+|#[0-9]+|[A-Za-z][A-Za-z0-9]+);")
    }
}

private data class PreparedXml(
    val markup: String,
    val changed: Boolean,
)

private data class XmlEntityDeclaration(
    val value: String?,
    val external: Boolean,
    val parameter: Boolean,
)

/**
 * XML control preparation is intentionally a small lexical pass. It does not become an XML
 * parser, and it never attempts to decide whether the document is readable. The native parser
 * remains authoritative for well-formedness and structure after this in-memory dependency
 * removal pass.
 */
private class XmlControlPreprocessor(
    private val namedEntityCodepoints: Map<String, Int>,
    private val maximumExpansionBytes: Long,
) {
    private val declarations = mutableMapOf<String, XmlEntityDeclaration>()
    private data class MemoizedEntity(
        val value: String,
        val byteCount: Long,
    )

    private val resolvedEntities = mutableMapOf<String, MemoizedEntity>()
    private var resolvedEntityBytes = 0L

    fun prepare(source: String): PreparedXml {
        val withoutDeclarations = removeDeclarations(source)
        val expanded = replaceReferences(withoutDeclarations)
        return PreparedXml(
            markup = expanded.markup,
            changed = expanded.markup != source,
        )
    }

    private fun removeDeclarations(source: String): String {
        val output = StringBuilder(source.length)
        var cursor = 0
        while (cursor < source.length) {
            val specialEnd = specialMarkupEnd(source, cursor)
            if (specialEnd != null) {
                output.append(source, cursor, specialEnd)
                cursor = specialEnd
                continue
            }
            if (startsWithIgnoreCase(source, cursor, "<!DOCTYPE") &&
                isNameBoundary(source, cursor + "<!DOCTYPE".length)
            ) {
                val end = declarationEnd(source, cursor)
                if (end < 0) {
                    // A malformed dependency cannot be handed to the parser. The parser will
                    // still decide readability for the remaining body, when one exists.
                    cursor = source.length
                } else {
                    collectEntityDeclarations(source.substring(cursor, end))
                    cursor = end
                }
                continue
            }
            if (startsWithIgnoreCase(source, cursor, "<!ENTITY") &&
                isNameBoundary(source, cursor + "<!ENTITY".length)
            ) {
                val end = declarationEnd(source, cursor)
                cursor = if (end < 0) source.length else end
                continue
            }
            output.append(source[cursor])
            cursor += 1
        }
        return output.toString()
    }

    private fun collectEntityDeclarations(doctype: String) {
        val subsetStart = doctype.indexOf('[')
        val subsetEnd = doctype.lastIndexOf(']')
        if (subsetStart < 0 || subsetEnd <= subsetStart) return
        val subset = doctype.substring(subsetStart + 1, subsetEnd)
        var cursor = 0
        while (cursor < subset.length) {
            val specialEnd = specialMarkupEnd(subset, cursor)
            if (specialEnd != null) {
                cursor = specialEnd
                continue
            }
            if (!startsWithIgnoreCase(subset, cursor, "<!ENTITY") ||
                !isNameBoundary(subset, cursor + "<!ENTITY".length)
            ) {
                cursor += 1
                continue
            }
            val end = declarationEnd(subset, cursor)
            if (end < 0) break
            parseEntityDeclaration(subset.substring(cursor, end))
            cursor = end
        }
    }

    private fun parseEntityDeclaration(declaration: String) {
        var cursor = "<!ENTITY".length
        cursor = skipWhitespace(declaration, cursor)
        var parameter = false
        if (declaration.getOrNull(cursor) == '%') {
            parameter = true
            cursor = skipWhitespace(declaration, cursor + 1)
        }
        val nameStart = cursor
        while (declaration.getOrNull(cursor)?.isXmlNameCharacter() == true) cursor += 1
        if (cursor == nameStart) return
        val name = declaration.substring(nameStart, cursor)
        val remainder = declaration.substring(cursor).trim()
        val external = remainder.startsWith("SYSTEM", ignoreCase = true) ||
            remainder.startsWith("PUBLIC", ignoreCase = true)
        val value = if (!external) quotedValue(remainder) else null
        declarations[name] = XmlEntityDeclaration(value, external, parameter)
    }

    private data class ReferenceReplacement(
        val markup: String,
    )

    private fun replaceReferences(source: String): ReferenceReplacement {
        val output = StringBuilder(source.length)
        var outputBytes = 0L
        var sourceBytesRemaining = source.encodeToByteArray().size.toLong()

        fun appendOriginal(value: String) {
            output.append(value)
            val bytes = value.encodeToByteArray().size.toLong()
            outputBytes += bytes
            sourceBytesRemaining -= bytes
        }

        fun appendReference(rawReference: String, replacement: String, fallback: String) {
            val rawBytes = rawReference.encodeToByteArray().size.toLong()
            sourceBytesRemaining -= rawBytes
            val replacementBytes = replacement.encodeToByteArray().size.toLong()
            // Keep the unprocessed original text inside the role's existing budget. If an
            // expansion cannot fit, preserve the whole authored reference as escaped text.
            if (outputBytes + replacementBytes + sourceBytesRemaining <= maximumExpansionBytes) {
                output.append(replacement)
                outputBytes += replacementBytes
                return
            }
            output.append(fallback)
            outputBytes += fallback.encodeToByteArray().size.toLong()
        }

        var cursor = 0
        while (cursor < source.length) {
            val specialEnd = specialMarkupEnd(source, cursor)
            if (specialEnd != null) {
                appendOriginal(source.substring(cursor, specialEnd))
                cursor = specialEnd
                continue
            }
            if (source[cursor] != '&') {
                appendOriginal(source[cursor].toString())
                cursor += 1
                continue
            }
            val semicolon = source.indexOf(';', cursor + 1)
            val reference = semicolon.takeIf { it > cursor + 1 }
            if (reference == null) {
                appendReference("&", "&amp;", "&amp;")
                cursor += 1
                continue
            }
            val name = source.substring(cursor + 1, reference)
            val rawReference = source.substring(cursor, reference + 1)
            if (name.startsWith('#') || name in namedEntityCodepoints) {
                appendReference(rawReference, rawReference, rawReference)
            } else {
                val declaration = declarations[name]
                if (declaration == null || declaration.external || declaration.parameter) {
                    val literal = literalReference(name)
                    appendReference(rawReference, literal, literal)
                } else {
                    val expanded = expandInternalEntity(name)
                    val literal = literalReference(name)
                    appendReference(rawReference, expanded ?: literal, literal)
                }
            }
            cursor = reference + 1
        }
        return ReferenceReplacement(output.toString())
    }

    /**
     * Expands a plain internal text entity without recursive calls. The explicit frame stack
     * keeps a hostile declaration chain from consuming the platform call stack. A replacement
     * which would exceed the role's existing byte budget is literalized by the caller.
     */
    private fun expandInternalEntity(rootName: String): String? {
        val root = declarations[rootName] ?: return null
        if (root.external || root.parameter || root.value == null) return null
        resolvedEntities[rootName]?.let { return it.value }

        data class Frame(
            val entityName: String,
            val text: String,
            var cursor: Int,
            val outputStart: Int,
            val outputStartBytes: Long,
            var memoizable: Boolean,
        )

        val frames = ArrayDeque<Frame>()
        val activeNames = mutableSetOf(rootName)
        val output = StringBuilder(root.value.length)
        var outputBytes = 0L
        frames.addLast(
            Frame(
                entityName = rootName,
                text = root.value,
                cursor = 0,
                outputStart = 0,
                outputStartBytes = 0L,
                memoizable = true,
            ),
        )
        while (frames.isNotEmpty()) {
            val frame = frames.last()
            if (frame.cursor >= frame.text.length) {
                frames.removeLast()
                activeNames.remove(frame.entityName)
                val parent = frames.lastOrNull()
                if (parent != null && !frame.memoizable) parent.memoizable = false
                if (frame.memoizable) {
                    val valueBytes = outputBytes - frame.outputStartBytes
                    if (valueBytes > 0 && valueBytes <= maximumExpansionBytes - resolvedEntityBytes) {
                        val value = output.substring(frame.outputStart)
                        resolvedEntities[frame.entityName] = MemoizedEntity(value, valueBytes)
                        resolvedEntityBytes += valueBytes
                    }
                }
                continue
            }
            val character = frame.text[frame.cursor]
            if (character != '&') {
                outputBytes += appendEscapedLiteral(output, character)
                frame.cursor += 1
                if (outputBytes > maximumExpansionBytes) return null
                continue
            }
            val semicolon = frame.text.indexOf(';', frame.cursor + 1)
            val reference = semicolon.takeIf { it > frame.cursor + 1 }
            if (reference == null) {
                outputBytes += appendEscapedLiteral(output, '&')
                frame.cursor += 1
                if (outputBytes > maximumExpansionBytes) return null
                continue
            }
            val nestedName = frame.text.substring(frame.cursor + 1, reference)
            val literalReferenceText = frame.text.substring(frame.cursor, reference + 1)
            frame.cursor = reference + 1
            when {
                nestedName.startsWith('#') || nestedName in namedEntityCodepoints -> {
                    output.append(literalReferenceText)
                    outputBytes += literalReferenceText.encodeToByteArray().size.toLong()
                }
                nestedName in activeNames -> {
                    frame.memoizable = false
                    val literal = literalReference(nestedName)
                    output.append(literal)
                    outputBytes += literal.encodeToByteArray().size.toLong()
                }
                else -> {
                    val memoized = resolvedEntities[nestedName]
                    if (memoized != null) {
                        output.append(memoized.value)
                        outputBytes += memoized.byteCount
                    } else {
                        val declaration = declarations[nestedName]
                        if (declaration == null || declaration.external || declaration.parameter || declaration.value == null) {
                            val literal = literalReference(nestedName)
                            output.append(literal)
                            outputBytes += literal.encodeToByteArray().size.toLong()
                        } else {
                            activeNames.add(nestedName)
                            frames.addLast(
                                Frame(
                                    entityName = nestedName,
                                    text = declaration.value,
                                    cursor = 0,
                                    outputStart = output.length,
                                    outputStartBytes = outputBytes,
                                    memoizable = true,
                                ),
                            )
                        }
                    }
                }
            }
            if (outputBytes > maximumExpansionBytes) return null
        }
        return output.toString()
    }

    private fun appendEscapedLiteral(output: StringBuilder, character: Char): Long {
        val escaped = when (character) {
            '&' -> "&amp;"
            '<' -> "&lt;"
            '>' -> "&gt;"
            '"' -> "&quot;"
            '\'' -> "&apos;"
            else -> character.toString()
        }
        output.append(escaped)
        return escaped.encodeToByteArray().size.toLong()
    }

    private fun declarationEnd(source: String, start: Int): Int {
        var quote: Char? = null
        var subsetDepth = 0
        var cursor = start
        while (cursor < source.length) {
            val specialEnd = specialMarkupEnd(source, cursor)
            if (specialEnd != null && cursor != start) {
                cursor = specialEnd
                continue
            }
            val character = source[cursor]
            if (quote != null) {
                if (character == quote) quote = null
            } else when (character) {
                '\'', '"' -> quote = character
                '[' -> subsetDepth += 1
                ']' -> if (subsetDepth > 0) subsetDepth -= 1
                '>' -> if (subsetDepth == 0) return cursor + 1
            }
            cursor += 1
        }
        return -1
    }

    private fun quotedValue(value: String): String? {
        val quote = value.firstOrNull { it == '\'' || it == '"' } ?: return null
        val start = value.indexOf(quote)
        val end = value.indexOf(quote, start + 1)
        return end.takeIf { it > start }?.let { value.substring(start + 1, it) }
    }

    private fun specialMarkupEnd(source: String, start: Int): Int? {
        val endMarker = when {
            source.startsWith("<!--", start) -> "-->"
            source.startsWith("<![CDATA[", start) -> "]]" + ">"
            source.startsWith("<?", start) -> "?>"
            else -> return null
        }
        val end = source.indexOf(endMarker, start + endMarker.length)
        return if (end < 0) source.length else end + endMarker.length
    }

    private fun literalReference(name: String): String = "&amp;$name;"

    private fun skipWhitespace(source: String, start: Int): Int {
        var cursor = start
        while (source.getOrNull(cursor)?.isWhitespace() == true) cursor += 1
        return cursor
    }

    private fun startsWithIgnoreCase(source: String, start: Int, prefix: String): Boolean =
        source.regionMatches(start, prefix, 0, prefix.length, ignoreCase = true)

    private fun isNameBoundary(source: String, index: Int): Boolean =
        source.getOrNull(index)?.isXmlNameCharacter() != true

    private fun Char.isXmlNameCharacter(): Boolean = isLetterOrDigit() || this == '_' || this == ':' || this == '-' || this == '.'

}

class ReaderSafetyException(
    val failure: ReaderSafetyFailure,
) : IllegalArgumentException(failure.errorCode)

class ReaderSafetyImplementationException(
    val failure: ReaderSafetyImplementationFailure,
) : IllegalStateException(failure.errorCode)
