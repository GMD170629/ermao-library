package com.ermao.library.shared.modules.reader.application

import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json

/** Uses server navigation fields only; a display index or percentage is never a locator. */
fun readingUnitLaunchTarget(readerType: String, href: String?, pageNumber: Int?): ReaderNavigationTarget {
    val validHref = href?.takeIf { it.isNotBlank() && it.length <= 8192 }
    val pageIndex = pageNumber?.takeIf { it > 0 }?.minus(1)
    return when (readerType.lowercase()) {
        "reflowable" -> validHref?.let(ReaderNavigationTarget::Reflowable)
        "pdf" -> pageIndex?.let(ReaderNavigationTarget::Pdf)
        "comic" -> if (pageIndex != null && validHref != null) ReaderNavigationTarget.Comic(pageIndex, validHref) else null
        else -> null
    } ?: ReaderNavigationTarget.Invalid()
}

fun encodeReaderLaunchTarget(target: ReaderNavigationTarget): String =
    Json.encodeToString(ReaderNavigationTarget.serializer(), target)

/** Null means resume; malformed explicit requests must fail instead of resuming another location. */
fun decodeReaderLaunchTarget(payload: String?): ReaderNavigationTarget? {
    if (payload == null) return null
    if (payload.length > 16384) return ReaderNavigationTarget.Invalid()
    return try {
        val target = Json.decodeFromString(ReaderNavigationTarget.serializer(), payload)
        when (target) {
            is ReaderNavigationTarget.Reflowable -> target.takeIf { it.href.isNotBlank() && it.href.length <= 8192 }
            is ReaderNavigationTarget.Pdf -> target.takeIf { it.pageIndex >= 0 }
            is ReaderNavigationTarget.Comic -> target.takeIf {
                it.pageIndex >= 0 && it.resourceHref.isNotBlank() && it.resourceHref.length <= 8192
            }
            is ReaderNavigationTarget.Invalid -> target
        } ?: ReaderNavigationTarget.Invalid()
    } catch (_: SerializationException) {
        ReaderNavigationTarget.Invalid()
    } catch (_: IllegalArgumentException) {
        ReaderNavigationTarget.Invalid()
    }
}
