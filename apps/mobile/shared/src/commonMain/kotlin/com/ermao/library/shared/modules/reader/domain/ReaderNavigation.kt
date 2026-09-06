package com.ermao.library.shared.modules.reader.domain

/** Transient TOC projection; the native renderer remains the owner of its locator. */
data class ReaderNavigationEntry(val id: String, val href: String, val depth: Int)

/** Resolve only evidenced targets. Duplicate peer targets cannot identify a unique chapter. */
fun resolveCurrentReaderNavigationEntryId(
    entries: List<ReaderNavigationEntry>,
    currentHref: String?,
    fragments: Set<String> = emptySet(),
    cssSelector: String? = null,
): String? {
    if (currentHref.isNullOrBlank()) return null
    val candidates = entries.filter { entry ->
        entry.href.substringBefore('#').isNotBlank() &&
            entry.href.substringBefore('#').removePrefix("./") == currentHref.substringBefore('#').removePrefix("./")
    }
    val evidenced = candidates.filter { entry ->
        entry.href.substringAfter('#', "").isNotEmpty() &&
            matchesReaderNavigationHref(currentHref, entry.href, fragments, cssSelector)
    }
    return evidenced.singleOrNull()?.id ?: candidates.singleOrNull()?.id
}

/**
 * Matches a renderer-neutral navigation href against the current UI location.
 * The opaque v5 Locator is not decoded here; fragment/selector arguments are
 * supplied only by a native navigation projection when available.
 */
fun matchesReaderNavigationHref(
    currentHref: String,
    expectedHref: String,
    fragments: Set<String> = emptySet(),
    cssSelector: String? = null,
): Boolean {
    if (currentHref.substringBefore('#').removePrefix("./") !=
        expectedHref.substringBefore('#').removePrefix("./")
    ) return false
    val fragment = expectedHref.substringAfter('#', "")
    if (fragment.isEmpty()) return true
    return currentHref.substringAfter('#', "") == fragment || fragment in fragments ||
        cssSelector == "#$fragment" || cssSelector?.startsWith("#$fragment > ") == true
}
