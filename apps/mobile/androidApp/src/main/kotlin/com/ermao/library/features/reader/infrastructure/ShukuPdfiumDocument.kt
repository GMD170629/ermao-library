package com.ermao.library.features.reader.infrastructure

import android.content.Context
import android.graphics.Bitmap
import androidx.core.graphics.createBitmap
import com.ermao.library.pdfium.ShukuPdfiumNative
import com.ermao.library.shared.modules.reader.domain.PdfReaderErrorCode
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import kotlin.reflect.KClass
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.readium.r2.shared.util.Try
import org.readium.r2.shared.util.data.ReadError
import org.readium.r2.shared.util.data.ReadTry
import org.readium.r2.shared.util.pdf.PdfDocument
import org.readium.r2.shared.util.pdf.PdfDocumentFactory
import org.readium.r2.shared.util.resource.Resource

internal class ShukuPdfiumFailure(val code: PdfReaderErrorCode) : Exception(code.wireValue)

internal interface AndroidPdfiumDataSource : ShukuPdfiumNative.ByteSource {
    val length: Long
    suspend fun prepare()
    suspend fun acquireRequested(): Boolean
    fun close()
}

internal class AndroidRemotePdfiumDataSource(
    override val length: Long,
    private val loader: AndroidPdfRangeLoader,
) : AndroidPdfiumDataSource {
    private val byteSource = AndroidPdfiumByteSource(loader)

    override suspend fun prepare() = loader.probe()
    override suspend fun acquireRequested(): Boolean = loader.drainRequested()
    override fun isRangeCached(offset: Long, size: Long): Boolean = byteSource.isRangeCached(offset, size)
    override fun readCachedBlock(offset: Long, destination: ByteBuffer): Boolean =
        byteSource.readCachedBlock(offset, destination)
    override fun requestRange(offset: Long, size: Long) = byteSource.requestRange(offset, size)
    override fun close() = Unit
}

internal class AndroidLocalPdfiumDataSource(file: File) : AndroidPdfiumDataSource {
    private val randomAccessFile = RandomAccessFile(file, "r")
    private val lock = Any()
    override val length: Long = randomAccessFile.length()

    init {
        require(file.isFile && length > 0)
    }

    override suspend fun prepare() = Unit
    override suspend fun acquireRequested(): Boolean = false

    override fun isRangeCached(offset: Long, size: Long): Boolean =
        size > 0 && offset >= 0 && offset <= length - size

    override fun readCachedBlock(offset: Long, destination: ByteBuffer): Boolean = synchronized(lock) {
        val count = destination.remaining()
        if (!isRangeCached(offset, count.toLong())) return false
        val bytes = ByteArray(count)
        randomAccessFile.seek(offset)
        if (randomAccessFile.read(bytes) != count) return false
        destination.put(bytes)
        true
    }

    override fun requestRange(offset: Long, size: Long) = Unit
    override fun close() = synchronized(lock) { randomAccessFile.close() }
}

internal class ShukuPdfiumDocument private constructor(
    private val nativeDocument: ShukuPdfiumNative.Document,
    private val dataSource: AndroidPdfiumDataSource,
    override val identifier: String,
    override val pageCount: Int,
) : PdfDocument {
    private val mutex = Mutex()
    private var closed = false

    override suspend fun cover(context: Context): Bitmap? = try {
        val size = pageSize(0)
        val scale = minOf(1f, 1024f / maxOf(size.widthPoints, size.heightPoints))
        renderPage(
            pageIndex = 0,
            width = maxOf(1, (size.widthPoints * scale).toInt()),
            height = maxOf(1, (size.heightPoints * scale).toInt()),
        )
    } catch (cancelled: CancellationException) {
        throw cancelled
    } catch (_: Exception) {
        null
    } catch (_: OutOfMemoryError) {
        null
    }

    suspend fun pageSize(pageIndex: Int): ShukuPdfiumNative.PageSize = withContext(Dispatchers.IO) {
        mutex.withLock {
            requireOpen()
            ensurePageAvailable(pageIndex)
            nativeDocument.pageSize(pageIndex) ?: throw ShukuPdfiumFailure(PdfReaderErrorCode.PageLoadFailed)
        }
    }

    suspend fun renderPage(pageIndex: Int, width: Int, height: Int): Bitmap = withContext(Dispatchers.IO) {
        mutex.withLock {
            requireOpen()
            require(width > 0 && height > 0 && width <= Int.MAX_VALUE / 4)
            ensurePageAvailable(pageIndex)
            val stride = width * 4
            val byteCount = stride.toLong() * height
            if (byteCount > MAX_RENDER_BYTES || byteCount > Int.MAX_VALUE) {
                throw ShukuPdfiumFailure(PdfReaderErrorCode.OutOfMemoryRisk)
            }
            val pixels = ByteBuffer.allocateDirect(byteCount.toInt())
            nativeDocument.renderPage(pageIndex, width, height, stride, MAX_RENDER_PIXELS, pixels)
                .throwOnFailure()
            pixels.rewind()
            createBitmap(width, height).also {
                it.copyPixelsFromBuffer(pixels)
            }
        }
    }

    suspend fun prefetchPage(pageIndex: Int) = withContext(Dispatchers.IO) {
        if (pageIndex !in 0 until pageCount) return@withContext
        mutex.withLock {
            requireOpen()
            when (nativeDocument.stepPage(pageIndex)) {
                ShukuPdfiumNative.Status.OK -> Unit
                ShukuPdfiumNative.Status.NEED_DATA -> dataSource.acquireRequested()
                else -> Unit
            }
        }
    }

    override fun close() {
        if (closed) return
        closed = true
        nativeDocument.close()
        dataSource.close()
    }

    private suspend fun ensurePageAvailable(pageIndex: Int) {
        require(pageIndex in 0 until pageCount)
        repeat(MAX_AVAILABILITY_STEPS) {
            when (val status = nativeDocument.stepPage(pageIndex)) {
                ShukuPdfiumNative.Status.OK -> return
                ShukuPdfiumNative.Status.NEED_DATA -> if (!dataSource.acquireRequested()) {
                    throw ShukuPdfiumFailure(PdfReaderErrorCode.RangeInvalid)
                }
                else -> status.throwOnFailure()
            }
        }
        throw ShukuPdfiumFailure(PdfReaderErrorCode.RangeInvalid)
    }

    private fun requireOpen() = check(!closed) { "PDFium document is closed" }

    companion object {
        private const val MAX_AVAILABILITY_STEPS = 256
        private const val MAX_RENDER_PIXELS = 12_000_000L
        private const val MAX_RENDER_BYTES = MAX_RENDER_PIXELS * 4

        suspend fun open(dataSource: AndroidPdfiumDataSource, identifier: String): ShukuPdfiumDocument =
            withContext(Dispatchers.IO) {
                dataSource.prepare()
                val native = ShukuPdfiumNative.Document(dataSource.length, dataSource)
                try {
                    repeat(MAX_AVAILABILITY_STEPS) {
                        when (val status = native.stepDocument()) {
                            ShukuPdfiumNative.Status.OK -> {
                                val pageCount = native.pageCount()
                                if (pageCount <= 0) throw ShukuPdfiumFailure(PdfReaderErrorCode.Invalid)
                                return@withContext ShukuPdfiumDocument(native, dataSource, identifier, pageCount)
                            }
                            ShukuPdfiumNative.Status.NEED_DATA -> if (!dataSource.acquireRequested()) {
                                throw ShukuPdfiumFailure(PdfReaderErrorCode.RangeInvalid)
                            }
                            else -> status.throwOnFailure()
                        }
                    }
                    throw ShukuPdfiumFailure(PdfReaderErrorCode.RangeInvalid)
                } catch (error: Throwable) {
                    native.close()
                    dataSource.close()
                    throw error
                }
            }
    }
}

internal class ShukuPdfiumDocumentFactory(
    private val dataSourceFactory: () -> AndroidPdfiumDataSource,
    private val identifier: String,
) : PdfDocumentFactory<ShukuPdfiumDocument> {
    override val documentType: KClass<ShukuPdfiumDocument> = ShukuPdfiumDocument::class

    override suspend fun open(resource: Resource, password: String?): ReadTry<ShukuPdfiumDocument> {
        if (password != null) {
            return Try.failure(ReadError.Decoding(ShukuPdfiumFailure(PdfReaderErrorCode.Encrypted)))
        }
        return try {
            Try.success(ShukuPdfiumDocument.open(dataSourceFactory(), identifier))
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: Exception) {
            Try.failure(ReadError.Decoding(error))
        } catch (error: OutOfMemoryError) {
            Try.failure(ReadError.Decoding(Exception(PdfReaderErrorCode.OutOfMemoryRisk.wireValue, error)))
        }
    }
}

private fun ShukuPdfiumNative.Status.throwOnFailure() {
    val code = when (this) {
        ShukuPdfiumNative.Status.OK -> return
        ShukuPdfiumNative.Status.NEED_DATA -> PdfReaderErrorCode.RangeInvalid
        ShukuPdfiumNative.Status.INVALID_ARGUMENT,
        ShukuPdfiumNative.Status.INVALID_DOCUMENT,
        -> PdfReaderErrorCode.Invalid
        ShukuPdfiumNative.Status.ENCRYPTED -> PdfReaderErrorCode.Encrypted
        ShukuPdfiumNative.Status.PAGE_LOAD_FAILED -> PdfReaderErrorCode.PageLoadFailed
        ShukuPdfiumNative.Status.RENDER_FAILED -> PdfReaderErrorCode.RenderFailed
        ShukuPdfiumNative.Status.OUT_OF_MEMORY_RISK -> PdfReaderErrorCode.OutOfMemoryRisk
    }
    throw ShukuPdfiumFailure(code)
}
