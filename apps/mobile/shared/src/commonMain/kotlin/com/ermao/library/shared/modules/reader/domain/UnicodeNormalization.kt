package com.ermao.library.shared.modules.reader.domain

/** Comparison-only NFC normalization; publication content is never rewritten. */
internal expect fun String.normalizeUnicodeNfc(): String
