package com.ermao.library.shared.modules.library.domain

/** Tag-entry semantics shared with the Web tag-values contract. Stored tags use newlines only. */
object TagInput {
    private val separators = setOf(',', '，', ';', '；', '\r', '\n')
    private const val ignored = "_-.[]()（）【】《》:：,，!！?？\"'“”‘’·・、/\\"

    fun key(value: String): String = normalizeTagCompatibility(value).lowercase()
        .filterNot { it.isWhitespace() || it in ignored }

    fun hasSeparator(value: String): Boolean = value.any { it in separators }

    fun parse(value: String): List<String> = unique(value.split(*separators.toCharArray()))

    fun stored(value: String): List<String> = value.lines().filter { it.isNotBlank() }

    fun append(current: List<String>, input: String): List<String> {
        val keys = current.map(::key).toMutableSet()
        return current + parse(input).filter { keys.add(key(it)) }
    }

    private fun unique(values: List<String>): List<String> {
        val keys = mutableSetOf<String>()
        return values.map { raw -> raw.map { if (it.isWhitespace()) ' ' else it }.joinToString("")
            .splitToSequence(' ').filter(String::isNotBlank).joinToString(" ") }
            .filter { it.isNotEmpty() && key(it).isNotEmpty() && keys.add(key(it)) }
    }
}

internal expect fun normalizeTagCompatibility(value: String): String
