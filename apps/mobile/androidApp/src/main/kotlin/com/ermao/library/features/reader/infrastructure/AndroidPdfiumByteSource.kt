package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.PdfRangeLoader
import com.ermao.library.pdfium.ShukuPdfiumNative
import java.nio.ByteBuffer

internal class AndroidPdfiumByteSource(private val loader: PdfRangeLoader) :
    ShukuPdfiumNative.ByteSource {
    override fun isRangeCached(offset: Long, size: Long): Boolean =
        size in 1..Int.MAX_VALUE && loader.isCached(offset, size.toInt())

    override fun readCachedBlock(offset: Long, destination: ByteBuffer): Boolean {
        val bytes = loader.readCached(offset, destination.remaining()) ?: return false
        destination.put(bytes)
        return true
    }

    override fun requestRange(offset: Long, size: Long) {
        loader.request(offset, size)
    }
}
