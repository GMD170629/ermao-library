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
        if (markup.isEmpty() || markup.isBlank()) {
            return rejected(
                ReaderSafetyRuleId.REFLOWABLE_REQUIRED_READING_ORDER_MARKUP,
            )
        }
        val measuredBytes = if (sourceByteCount >= 0) {
            maxOf(sourceByteCount, markup.encodeToByteArray().size.toLong())
        } else {
            markup.encodeToByteArray().size.toLong()
        }
        if (measuredBytes > budget("reflowableMarkupMaxBytes")) {
            return rejected(
                ReaderSafetyRuleId.REFLOWABLE_MARKUP_MAX_BYTES,
            )
        }

        val lexicalMarkup = maskNonMarkup(markup)
        if (ENTITY_OPEN.containsMatchIn(lexicalMarkup)) {
            return rejected(
                ReaderSafetyRuleId.REFLOWABLE_REJECT_XML_ENTITY,
            )
        }
        if (NAMED_ENTITY_REFERENCE.findAll(lexicalMarkup).any { match ->
                match.groups["name"]?.value !in ReaderSafetyPolicy.reflowableProfile.namedEntityCodepoints
            }
        ) {
            return rejected(
                ReaderSafetyRuleId.REFLOWABLE_REJECT_XML_ENTITY,
            )
        }
        if (!validateDoctype(lexicalMarkup)) {
            return rejected(
                ReaderSafetyRuleId.REFLOWABLE_REJECT_XML_ENTITY,
            )
        }

        var sanitized = markup
        sanitized = sanitizeElements(sanitized, ReaderSafetyPolicy.reflowableProfile.sanitizedElements)
        sanitized = sanitizeElements(sanitized, ReaderSafetyPolicy.reflowableProfile.svgSanitizedElements)
        sanitized = sanitizeMetaElements(sanitized)
        sanitized = sanitizeAttributes(sanitized)
        sanitized = sanitizeStyleElements(sanitized)
        return ReaderSafetyMarkupResult.Accepted(
            ReaderSanitizedMarkup(
                markup = sanitized,
                parserMarkup = replaceGeneratedEntitiesForParsing(sanitized),
                changed = sanitized != markup,
            ),
        )
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

    private fun validateDoctype(lexicalMarkup: String): Boolean {
        val matches = DOCTYPE_DECLARATION.findAll(lexicalMarkup).toList()
        val opens = DOCTYPE_OPEN.findAll(lexicalMarkup).toList()
        if (opens.isEmpty()) return true
        if (opens.size != 1 || matches.size != 1 || opens.single().range.first != matches.single().range.first) {
            return false
        }
        val declaration = matches.single().value
        if ('[' in declaration || ']' in declaration) return false
        val prefix = lexicalMarkup.substring(0, matches.single().range.first)
            .replace(XML_DECLARATION, "")
            .trim()
        if (prefix.isNotEmpty()) return false
        val parsed = SAFE_DOCTYPE.matchEntire(declaration.trim()) ?: return false
        val publicId = parsed.groups["public"]?.value
        val systemId = parsed.groups["system"]?.value
        if (publicId == null || systemId == null) return false
        return ReaderSafetyPolicy.reflowableProfile.safeDoctypes.any {
            it.publicId.equals(publicId, ignoreCase = false) &&
                it.systemId.equals(systemId, ignoreCase = false)
        }
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
        return authoredScheme(candidate) != null
    }

    private fun isUnsafeUserNavigation(value: String): Boolean {
        val candidate = value.trim()
        if (candidate.isEmpty() || candidate.startsWith('#')) return false
        if (candidate.startsWith("//")) return true
        val scheme = authoredScheme(candidate) ?: return false
        return scheme !in ReaderSafetyPolicy.reflowableProfile.userNavigationSchemes
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
        val DOCTYPE_OPEN = Regex("<!DOCTYPE\\b", RegexOption.IGNORE_CASE)
        val DOCTYPE_DECLARATION = Regex(
            "(?is)<!DOCTYPE\\b[^>]*>",
            RegexOption.IGNORE_CASE,
        )
        val ENTITY_OPEN = Regex("<!ENTITY\\b", RegexOption.IGNORE_CASE)
        val SAFE_DOCTYPE = Regex(
            """(?is)<!DOCTYPE\s+html\s*(?:PUBLIC\s+[\"'](?<public>[^\"']+)[\"']\s+[\"'](?<system>[^\"']+)[\"'])?\s*>""",
        )
        val XML_DECLARATION = Regex("<\\?xml\\b[^?]*\\?>", RegexOption.IGNORE_CASE)
    }
}

class ReaderSafetyException(
    val failure: ReaderSafetyFailure,
) : IllegalArgumentException(failure.errorCode)

class ReaderSafetyImplementationException(
    val failure: ReaderSafetyImplementationFailure,
) : IllegalStateException(failure.errorCode)
