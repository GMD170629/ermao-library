package com.ermao.library.shared.modules.reader.domain

import java.text.Normalizer

internal actual fun String.normalizeUnicodeNfc(): String =
    Normalizer.normalize(this, Normalizer.Form.NFC)
