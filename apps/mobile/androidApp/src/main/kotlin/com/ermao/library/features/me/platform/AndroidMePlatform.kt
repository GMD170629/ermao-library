package com.ermao.library.features.me.platform

import android.content.ContentResolver
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.net.Uri
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.graphics.createBitmap
import androidx.core.graphics.scale
import androidx.core.os.LocaleListCompat
import com.ermao.library.features.me.model.SanitizedAvatar
import com.ermao.library.features.me.model.SanitizedAvatarMimeType
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsLocale
import java.io.ByteArrayOutputStream
import java.io.InputStream
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

interface AppLocaleController {
    fun apply(locale: PersonalSettingsLocale)
    fun restoreSystemLanguage()
}

class AndroidXAppLocaleController : AppLocaleController {
    override fun apply(locale: PersonalSettingsLocale) {
        AppCompatDelegate.setApplicationLocales(LocaleListCompat.forLanguageTags(locale.wireValue))
    }

    override fun restoreSystemLanguage() {
        AppCompatDelegate.setApplicationLocales(LocaleListCompat.getEmptyLocaleList())
    }
}

enum class AvatarSanitizationFailure {
    UnsupportedType,
    Unreadable,
    TooLarge,
}

sealed interface AvatarSanitizationResult {
    data class Success(val avatar: SanitizedAvatar) : AvatarSanitizationResult
    data class Failure(val reason: AvatarSanitizationFailure) : AvatarSanitizationResult
}

class AndroidAvatarSanitizer(
    private val resolver: ContentResolver,
) {
    suspend fun sanitize(uri: Uri): AvatarSanitizationResult = withContext(Dispatchers.IO) {
        val sourceMimeType = resolver.getType(uri)?.lowercase()
        if (sourceMimeType != null && sourceMimeType !in ALLOWED_SOURCE_TYPES) {
            return@withContext AvatarSanitizationResult.Failure(AvatarSanitizationFailure.UnsupportedType)
        }
        val source = runCatching {
            resolver.openInputStream(uri)?.use { input -> input.readLimited(MAX_SOURCE_BYTES + 1) }
        }.getOrNull() ?: return@withContext AvatarSanitizationResult.Failure(AvatarSanitizationFailure.Unreadable)
        if (source.size > MAX_SOURCE_BYTES) {
            return@withContext AvatarSanitizationResult.Failure(AvatarSanitizationFailure.TooLarge)
        }
        if (!isSupportedImage(source)) {
            return@withContext AvatarSanitizationResult.Failure(AvatarSanitizationFailure.UnsupportedType)
        }
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(source, 0, source.size, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0 || bounds.outWidth > HARD_MAX_DIMENSION ||
            bounds.outHeight > HARD_MAX_DIMENSION || bounds.outWidth.toLong() * bounds.outHeight > MAX_PIXELS
        ) {
            return@withContext AvatarSanitizationResult.Failure(AvatarSanitizationFailure.TooLarge)
        }
        var sampleSize = 1
        while (bounds.outWidth / sampleSize > MAX_DIMENSION * 2 || bounds.outHeight / sampleSize > MAX_DIMENSION * 2) {
            sampleSize *= 2
        }
        val decoded = try {
            BitmapFactory.decodeByteArray(source, 0, source.size, BitmapFactory.Options().apply { inSampleSize = sampleSize })
        } catch (_: OutOfMemoryError) {
            null
        } ?: return@withContext AvatarSanitizationResult.Failure(AvatarSanitizationFailure.Unreadable)
        try {
            val bounded = decoded.scaledToFit(MAX_DIMENSION)
            if (bounded !== decoded) decoded.recycle()
            val opaque = createBitmap(bounded.width, bounded.height).also { bitmap ->
                Canvas(bitmap).apply {
                    drawColor(Color.WHITE)
                    drawBitmap(bounded, 0f, 0f, null)
                }
            }
            if (bounded !== opaque) bounded.recycle()
            var candidate = opaque
            var quality = 92
            while (candidate.width >= MIN_DIMENSION && candidate.height >= MIN_DIMENSION) {
                while (quality >= 60) {
                    val bytes = ByteArrayOutputStream().use { output ->
                        candidate.compress(Bitmap.CompressFormat.JPEG, quality, output)
                        output.toByteArray()
                    }
                    if (bytes.size <= MAX_OUTPUT_BYTES) {
                        candidate.recycle()
                        return@withContext AvatarSanitizationResult.Success(
                            SanitizedAvatar(bytes, SanitizedAvatarMimeType.Jpeg),
                        )
                    }
                    quality -= 8
                }
                val next = candidate.scale(
                    (candidate.width * 0.8f).toInt().coerceAtLeast(1),
                    (candidate.height * 0.8f).toInt().coerceAtLeast(1),
                )
                candidate.recycle()
                candidate = next
                quality = 88
            }
            candidate.recycle()
        } catch (_: OutOfMemoryError) {
            if (!decoded.isRecycled) decoded.recycle()
            return@withContext AvatarSanitizationResult.Failure(AvatarSanitizationFailure.TooLarge)
        }
        AvatarSanitizationResult.Failure(AvatarSanitizationFailure.TooLarge)
    }

    private fun Bitmap.scaledToFit(maxDimension: Int): Bitmap {
        val largest = maxOf(width, height)
        if (largest <= maxDimension) return this
        val scale = maxDimension.toFloat() / largest
        return scale(
            (width * scale).toInt().coerceAtLeast(1),
            (height * scale).toInt().coerceAtLeast(1),
        )
    }

    private fun isSupportedImage(bytes: ByteArray): Boolean =
        isJpeg(bytes) || isPng(bytes) || isWebp(bytes) || isHeif(bytes)

    private fun isJpeg(bytes: ByteArray): Boolean =
        bytes.size >= 3 && bytes[0] == 0xFF.toByte() && bytes[1] == 0xD8.toByte() && bytes[2] == 0xFF.toByte()

    private fun isPng(bytes: ByteArray): Boolean =
        bytes.size >= 8 && bytes.copyOfRange(0, 8).contentEquals(PNG_SIGNATURE)

    private fun isWebp(bytes: ByteArray): Boolean =
        bytes.size >= 12 && bytes.copyOfRange(0, 4).decodeToString() == "RIFF" &&
            bytes.copyOfRange(8, 12).decodeToString() == "WEBP"

    private fun isHeif(bytes: ByteArray): Boolean {
        if (bytes.size < 12 || bytes.copyOfRange(4, 8).decodeToString() != "ftyp") return false
        val brand = bytes.copyOfRange(8, 12).decodeToString()
        return brand in HEIF_BRANDS
    }

    private fun InputStream.readLimited(limit: Int): ByteArray {
        val output = ByteArrayOutputStream(minOf(limit, 64 * 1024))
        val buffer = ByteArray(16 * 1024)
        while (output.size() < limit) {
            val read = read(buffer, 0, minOf(buffer.size, limit - output.size()))
            if (read < 0) break
            output.write(buffer, 0, read)
        }
        return output.toByteArray()
    }

    private companion object {
        val ALLOWED_SOURCE_TYPES = setOf("image/jpeg", "image/png", "image/webp", "image/heic", "image/heif")
        val HEIF_BRANDS = setOf("heic", "heix", "hevc", "hevx", "heim", "heis", "mif1", "msf1")
        val PNG_SIGNATURE = byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)
        const val MAX_SOURCE_BYTES = 24 * 1024 * 1024
        const val MAX_OUTPUT_BYTES = 5 * 1024 * 1024
        const val MAX_DIMENSION = 2048
        const val HARD_MAX_DIMENSION = 32768
        const val MAX_PIXELS = 40_000_000L
        const val MIN_DIMENSION = 128
    }
}

fun decodeBoundedAvatarPreview(bytes: ByteArray, maxDimension: Int = 512): Bitmap? {
    if (bytes.isEmpty() || maxDimension <= 0) return null
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
    if (bounds.outWidth <= 0 || bounds.outHeight <= 0 || bounds.outWidth > 32768 || bounds.outHeight > 32768 ||
        bounds.outWidth.toLong() * bounds.outHeight > 40_000_000L
    ) return null
    var sample = 1
    while (bounds.outWidth / sample > maxDimension * 2 || bounds.outHeight / sample > maxDimension * 2) sample *= 2
    return try {
        val decoded = BitmapFactory.decodeByteArray(
            bytes,
            0,
            bytes.size,
            BitmapFactory.Options().apply { inSampleSize = sample },
        ) ?: return null
        if (maxOf(decoded.width, decoded.height) <= maxDimension) decoded else decoded.let { source ->
            val scale = maxDimension.toFloat() / maxOf(source.width, source.height)
            source.scale(
                (source.width * scale).toInt().coerceAtLeast(1),
                (source.height * scale).toInt().coerceAtLeast(1),
            ).also { source.recycle() }
        }
    } catch (_: OutOfMemoryError) {
        null
    }
}
