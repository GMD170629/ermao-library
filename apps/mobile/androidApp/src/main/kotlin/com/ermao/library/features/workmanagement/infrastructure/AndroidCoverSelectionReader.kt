package com.ermao.library.features.workmanagement.infrastructure

import android.content.ContentResolver
import android.database.Cursor
import android.net.Uri
import android.provider.OpenableColumns
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
