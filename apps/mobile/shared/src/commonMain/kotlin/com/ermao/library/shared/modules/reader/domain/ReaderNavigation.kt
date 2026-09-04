package com.ermao.library.shared.modules.reader.domain

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
