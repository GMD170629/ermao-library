package com.ermao.library.shared.modules.library.domain

import java.text.Normalizer

internal actual fun normalizeTagCompatibility(value: String): String = Normalizer.normalize(value, Normalizer.Form.NFKC)
