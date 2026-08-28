package com.ermao.library.features.workmanagement.infrastructure

import android.content.ContentResolver
import android.database.Cursor
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageDecoder
import android.graphics.Matrix
import androidx.exifinterface.media.ExifInterface
import android.net.Uri
import android.os.Build
import android.provider.OpenableColumns
import androidx.core.graphics.scale
import com.ermao.library.shared.modules.workmanagement.domain.CoverUpload
import java.io.ByteArrayOutputStream
import java.io.InputStream
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

sealed interface CoverSelectionResult {
    data class Ready(val upload: CoverUpload) : CoverSelectionResult
    data object UnsupportedType : CoverSelectionResult
    data object TooLarge : CoverSelectionResult
    data object Empty : CoverSelectionResult
    data object Unreadable : CoverSelectionResult
}

class AndroidCoverSelectionReader(
    private val contentResolver: ContentResolver,
) {
    suspend fun read(uri: Uri): CoverSelectionResult = withContext(Dispatchers.IO) {
        val mimeType = contentResolver.getType(uri)
            ?.lowercase()
            ?.takeIf { it in CoverUpload.SUPPORTED_COVER_MIME_TYPES }
            ?: return@withContext CoverSelectionResult.UnsupportedType
        val metadata = contentResolver.queryMetadata(uri)
        if (metadata.size != null && metadata.size > MAX_COVER_BYTES) {
            return@withContext CoverSelectionResult.TooLarge
        }
        val stream = runCatching { contentResolver.openInputStream(uri) }.getOrNull()
            ?: return@withContext CoverSelectionResult.Unreadable
        val bytes = runCatching { stream.use { it.readAtMost(MAX_COVER_BYTES) } }
            .getOrElse { return@withContext CoverSelectionResult.Unreadable }
            ?: return@withContext CoverSelectionResult.TooLarge
        if (bytes.isEmpty()) return@withContext CoverSelectionResult.Empty
        val extension = when (mimeType) {
            "image/png" -> "png"
            "image/webp" -> "webp"
            else -> "jpg"
        }
        val safeName = metadata.displayName
            ?.substringAfterLast('/')
            ?.takeIf(String::isNotBlank)
            ?: "cover.$extension"
        CoverSelectionResult.Ready(CoverUpload(safeName, mimeType, bytes))
    }

    suspend fun readPhoto(uri: Uri): CoverSelectionResult = withContext(Dispatchers.IO) {
        val mimeType = contentResolver.getType(uri)?.lowercase()
        if (mimeType?.startsWith("image/") != true) {
            return@withContext CoverSelectionResult.UnsupportedType
        }
        val bitmap = decodePhoto(uri) ?: return@withContext CoverSelectionResult.Unreadable
        val bytes = bitmap.useAndCompress() ?: return@withContext CoverSelectionResult.TooLarge
        CoverSelectionResult.Ready(CoverUpload("cover.jpg", "image/jpeg", bytes))
    }

    private fun decodePhoto(uri: Uri): Bitmap? = runCatching {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            ImageDecoder.decodeBitmap(ImageDecoder.createSource(contentResolver, uri)) { decoder, info, _ ->
                val width = info.size.width
                val height = info.size.height
                val scale = minOf(1f, MAX_PHOTO_DIMENSION.toFloat() / maxOf(width, height).toFloat())
                decoder.setTargetSize(maxOf(1, (width * scale).toInt()), maxOf(1, (height * scale).toInt()))
                decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
            }
        } else {
            val decoded = contentResolver.openInputStream(uri)?.use(BitmapFactory::decodeStream)
                ?: return@runCatching null
            val orientation = runCatching {
                contentResolver.openInputStream(uri)?.use { input ->
                    ExifInterface(input).getAttributeInt(
                        ExifInterface.TAG_ORIENTATION,
                        ExifInterface.ORIENTATION_NORMAL,
                    )
                }
            }.getOrNull() ?: ExifInterface.ORIENTATION_NORMAL
            decoded.normalizedForExifOrientation(orientation)
        }
    }.getOrNull()
}

private fun Bitmap.normalizedForExifOrientation(orientation: Int): Bitmap {
    val matrix = Matrix()
    when (orientation) {
        ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.setScale(-1f, 1f)
        ExifInterface.ORIENTATION_ROTATE_180 -> matrix.setRotate(180f)
        ExifInterface.ORIENTATION_FLIP_VERTICAL -> matrix.setScale(1f, -1f)
        ExifInterface.ORIENTATION_TRANSPOSE -> {
            matrix.setRotate(90f)
            matrix.postScale(-1f, 1f)
        }
        ExifInterface.ORIENTATION_ROTATE_90 -> matrix.setRotate(90f)
        ExifInterface.ORIENTATION_TRANSVERSE -> {
            matrix.setRotate(-90f)
            matrix.postScale(-1f, 1f)
        }
        ExifInterface.ORIENTATION_ROTATE_270 -> matrix.setRotate(-90f)
        else -> return this
    }
    val normalized = Bitmap.createBitmap(this, 0, 0, width, height, matrix, true)
    if (normalized !== this) recycle()
    return normalized
}

private fun Bitmap.useAndCompress(): ByteArray? {
    var current = this
    return try {
        for (maximumDimension in listOf(4096, 3200, 2400, 1800)) {
            val longest = maxOf(current.width, current.height)
            if (longest > maximumDimension) {
                val scale = maximumDimension.toFloat() / longest.toFloat()
                val scaled = current.scale(
                    width = maxOf(1, (current.width * scale).toInt()),
                    height = maxOf(1, (current.height * scale).toInt()),
                )
                if (current !== this) current.recycle()
                current = scaled
            }
            for (quality in listOf(92, 82, 72, 60, 48)) {
                val output = ByteArrayOutputStream()
                if (current.compress(Bitmap.CompressFormat.JPEG, quality, output)) {
                    output.toByteArray().takeIf { it.size <= MAX_COVER_BYTES }?.let { return it }
                }
            }
        }
        null
    } finally {
        if (!current.isRecycled) current.recycle()
        if (current !== this && !isRecycled) recycle()
    }
}

private data class SelectedFileMetadata(
    val displayName: String?,
    val size: Long?,
)

private fun ContentResolver.queryMetadata(uri: Uri): SelectedFileMetadata {
    val projection = arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE)
    return runCatching {
        query(uri, projection, null, null, null)?.use(Cursor::selectedFileMetadata)
    }.getOrNull() ?: SelectedFileMetadata(displayName = null, size = null)
}

private fun Cursor.selectedFileMetadata(): SelectedFileMetadata {
    if (!moveToFirst()) return SelectedFileMetadata(displayName = null, size = null)
    val nameIndex = getColumnIndex(OpenableColumns.DISPLAY_NAME)
    val sizeIndex = getColumnIndex(OpenableColumns.SIZE)
    return SelectedFileMetadata(
        displayName = nameIndex.takeIf { it >= 0 && !isNull(it) }?.let(::getString),
        size = sizeIndex.takeIf { it >= 0 && !isNull(it) }?.let(::getLong),
    )
}

internal fun InputStream.readAtMost(maxBytes: Int): ByteArray? {
    require(maxBytes > 0)
    val output = ByteArrayOutputStream(minOf(DEFAULT_BUFFER_SIZE, maxBytes))
    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
    var total = 0
    while (true) {
        val read = read(buffer)
        if (read < 0) break
        total += read
        if (total > maxBytes) return null
        output.write(buffer, 0, read)
    }
    return output.toByteArray()
}

internal const val MAX_COVER_BYTES = 10 * 1024 * 1024
private const val MAX_PHOTO_DIMENSION = 4096
