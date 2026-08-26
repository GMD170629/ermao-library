package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ReaderEngineCapability
import com.ermao.library.shared.modules.reader.ReaderEngineCapabilityRegistry
import com.ermao.library.shared.modules.reader.ReaderSourceFormat

/** Platform truth: local validation alone does not make a format reader-ready. */
internal object AndroidReaderCapabilities {
    val registry = ReaderEngineCapabilityRegistry(
        ReaderSourceFormat.entries.map { sourceFormat ->
            val nativeReaderReady = sourceFormat in setOf(
                ReaderSourceFormat.Epub,
                ReaderSourceFormat.Mobi,
                ReaderSourceFormat.Azw,
                ReaderSourceFormat.Azw3,
                ReaderSourceFormat.Prc,
                ReaderSourceFormat.Txt,
                ReaderSourceFormat.Fb2,
                ReaderSourceFormat.Cbz,
                ReaderSourceFormat.Zip,
                ReaderSourceFormat.Cbr,
                ReaderSourceFormat.Rar,
                ReaderSourceFormat.ImageDir,
                ReaderSourceFormat.Pdf,
            )
            ReaderEngineCapability(
                sourceFormat = sourceFormat,
                parserAvailable = nativeReaderReady,
                navigatorAvailable = nativeReaderReady,
                exactLocationAvailable = nativeReaderReady,
            )
        },
    )
}
