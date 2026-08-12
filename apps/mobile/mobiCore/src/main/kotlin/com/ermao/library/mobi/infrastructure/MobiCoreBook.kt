package com.ermao.library.mobi.infrastructure

import java.io.Closeable
import java.io.File

internal const val MOBI_CORE_ABI_VERSION: Int = 1
internal const val MOBI_CORE_MAX_READ_BYTES: Int = 256 * 1024
private const val MOBI_CORE_INDEX_NONE: Long = 4_294_967_295L

internal enum class MobiCoreStatus(
    val code: Int,
) {
    InvalidArgument(1),
    FileNotFound(2),
    Io(3),
    Unsupported(4),
    DrmProtected(5),
    Corrupt(6),
    ParseFailed(7),
    NoContent(8),
    LimitExceeded(9),
    OutOfMemory(10),
    NotFound(11),
    OutOfRange(12),
    BufferTooSmall(13),
    Internal(14),
    ;

    companion object {
        fun fromCode(code: Int): MobiCoreStatus = entries.firstOrNull { it.code == code } ?: Internal
    }
}

internal class MobiCoreException(
    val statusCode: Int,
) : Exception("MOBI core failed: ${MobiCoreStatus.fromCode(statusCode).name}") {
    val status: MobiCoreStatus = MobiCoreStatus.fromCode(statusCode)
}

internal enum class MobiCoreFormat {
    Mobi6,
    Kf8,
    HybridKf8,
    HybridMobi6Fallback,
}

internal enum class MobiCoreReadingDirection {
    Unknown,
    LeftToRight,
    RightToLeft,
}

internal enum class MobiCoreResourceCategory {
    Markup,
    Flow,
    Asset,
}

internal enum class MobiCoreMetadataField(
    val code: Int,
) {
    Title(1),
    Author(2),
    Publisher(3),
    Language(4),
    Asin(5),
    Isbn(6),
    Description(7),
}

internal data class MobiCoreBookInfo(
    val format: MobiCoreFormat,
    val readingDirection: MobiCoreReadingDirection,
    val resourceCount: Int,
    val readingOrderCount: Int,
    val tocCount: Int,
    val warningCount: Int,
    val coverResourceIndex: Int?,
)

internal data class MobiCoreResourceInfo(
    val category: MobiCoreResourceCategory,
    val sourceUid: Long,
    val decodedLength: Long,
    val sourceName: String,
    val mediaType: String,
)

internal data class MobiCoreTocInfo(
    val parentIndex: Int?,
    val targetResourceIndex: Int?,
    val title: String?,
    val fragment: String?,
)

internal data class MobiCoreWarning(
    val code: Int,
    val relatedIndex: Int?,
)

internal class MobiCoreBook private constructor(
    private var handle: Long,
) : Closeable {
    @Synchronized
    fun info(): MobiCoreBookInfo {
        val values = MobiCoreNative.bookInfo(requireOpen())
        checkNativeShape(values, 8)
        if (values[7].toInt() != MOBI_CORE_ABI_VERSION) {
            throw MobiCoreException(MobiCoreStatus.Internal.code)
        }
        return MobiCoreBookInfo(
            format = formatFromCode(values[0].toInt()),
            readingDirection = readingDirectionFromCode(values[1].toInt()),
            resourceCount = values[2].toCount(),
            readingOrderCount = values[3].toCount(),
            tocCount = values[4].toCount(),
            warningCount = values[5].toCount(),
            coverResourceIndex = values[6].toOptionalIndex(),
        )
    }

    @Synchronized
    fun metadata(field: MobiCoreMetadataField): String? =
        MobiCoreNative.metadata(requireOpen(), field.code)

    @Synchronized
    fun resource(index: Int): MobiCoreResourceInfo {
        require(index >= 0) { "resource index must be non-negative" }
        val currentHandle = requireOpen()
        val values = MobiCoreNative.resourceInfo(currentHandle, index)
        checkNativeShape(values, 3)
        return MobiCoreResourceInfo(
            category = categoryFromCode(values[0].toInt()),
            sourceUid = values[1],
            decodedLength = values[2],
            sourceName = MobiCoreNative.resourceSourceName(currentHandle, index),
            mediaType = MobiCoreNative.resourceMediaType(currentHandle, index),
        )
    }

    @Synchronized
    fun readResource(
        resourceIndex: Int,
        offset: Long,
        length: Int,
    ): ByteArray {
        require(resourceIndex >= 0) { "resource index must be non-negative" }
        require(offset >= 0L) { "resource offset must be non-negative" }
        require(length in 0..MOBI_CORE_MAX_READ_BYTES) {
            "resource read must not exceed $MOBI_CORE_MAX_READ_BYTES bytes"
        }
        return MobiCoreNative.readResource(requireOpen(), resourceIndex, offset, length)
    }

    @Synchronized
    fun readingOrderResourceIndex(position: Int): Int {
        require(position >= 0) { "reading-order position must be non-negative" }
        return MobiCoreNative.readingOrderResourceIndex(requireOpen(), position)
    }

    @Synchronized
    fun toc(index: Int): MobiCoreTocInfo {
        require(index >= 0) { "TOC index must be non-negative" }
        val currentHandle = requireOpen()
        val values = MobiCoreNative.tocInfo(currentHandle, index)
        checkNativeShape(values, 2)
        return MobiCoreTocInfo(
            parentIndex = values[0].toOptionalIndex(),
            targetResourceIndex = values[1].toOptionalIndex(),
            title = MobiCoreNative.tocTitle(currentHandle, index),
            fragment = MobiCoreNative.tocFragment(currentHandle, index),
        )
    }

    @Synchronized
    fun warning(index: Int): MobiCoreWarning {
        require(index >= 0) { "warning index must be non-negative" }
        val values = MobiCoreNative.warningInfo(requireOpen(), index)
        checkNativeShape(values, 2)
        return MobiCoreWarning(
            code = values[0].toInt(),
            relatedIndex = values[1].toOptionalIndex(),
        )
    }

    @Synchronized
    override fun close() {
        val currentHandle = handle
        if (currentHandle == 0L) return
        handle = 0L
        MobiCoreNative.close(currentHandle)
    }

    private fun requireOpen(): Long = handle.takeIf { it != 0L }
        ?: throw IllegalStateException("MOBI core handle is closed")

    companion object {
        val abiVersion: Int
            get() = MobiCoreNative.abiVersion()

        val parserIdentifier: String
            get() = MobiCoreNative.parserIdentifier()

        val normalizationIdentifier: String
            get() = MobiCoreNative.normalizationIdentifier()

        fun open(file: File): MobiCoreBook {
            val canonicalFile = file.canonicalFile
            return MobiCoreBook(MobiCoreNative.open(canonicalFile.path.encodeToByteArray()))
        }

        private fun checkNativeShape(values: LongArray, expectedSize: Int) {
            if (values.size != expectedSize) {
                throw MobiCoreException(MobiCoreStatus.Internal.code)
            }
        }

        private fun Long.toCount(): Int = takeIf { it in 0L..Int.MAX_VALUE.toLong() }
            ?.toInt()
            ?: throw MobiCoreException(MobiCoreStatus.LimitExceeded.code)

        private fun Long.toOptionalIndex(): Int? = when (this) {
            MOBI_CORE_INDEX_NONE -> null
            in 0L..Int.MAX_VALUE.toLong() -> toInt()
            else -> throw MobiCoreException(MobiCoreStatus.LimitExceeded.code)
        }

        private fun formatFromCode(code: Int): MobiCoreFormat = when (code) {
            1 -> MobiCoreFormat.Mobi6
            2 -> MobiCoreFormat.Kf8
            3 -> MobiCoreFormat.HybridKf8
            4 -> MobiCoreFormat.HybridMobi6Fallback
            else -> throw MobiCoreException(MobiCoreStatus.Internal.code)
        }

        private fun readingDirectionFromCode(code: Int): MobiCoreReadingDirection = when (code) {
            0 -> MobiCoreReadingDirection.Unknown
            1 -> MobiCoreReadingDirection.LeftToRight
            2 -> MobiCoreReadingDirection.RightToLeft
            else -> throw MobiCoreException(MobiCoreStatus.Internal.code)
        }

        private fun categoryFromCode(code: Int): MobiCoreResourceCategory = when (code) {
            1 -> MobiCoreResourceCategory.Markup
            2 -> MobiCoreResourceCategory.Flow
            3 -> MobiCoreResourceCategory.Asset
            else -> throw MobiCoreException(MobiCoreStatus.Internal.code)
        }
    }
}

private object MobiCoreNative {
    init {
        System.loadLibrary("ermao_mobi_jni")
    }

    external fun abiVersion(): Int
    external fun parserIdentifier(): String
    external fun normalizationIdentifier(): String
    external fun open(pathUtf8: ByteArray): Long
    external fun close(handle: Long)
    external fun bookInfo(handle: Long): LongArray
    external fun metadata(handle: Long, field: Int): String?
    external fun resourceInfo(handle: Long, index: Int): LongArray
    external fun resourceSourceName(handle: Long, index: Int): String
    external fun resourceMediaType(handle: Long, index: Int): String
    external fun readResource(handle: Long, index: Int, offset: Long, length: Int): ByteArray
    external fun readingOrderResourceIndex(handle: Long, position: Int): Int
    external fun tocInfo(handle: Long, index: Int): LongArray
    external fun tocTitle(handle: Long, index: Int): String?
    external fun tocFragment(handle: Long, index: Int): String?
    external fun warningInfo(handle: Long, index: Int): LongArray
}
