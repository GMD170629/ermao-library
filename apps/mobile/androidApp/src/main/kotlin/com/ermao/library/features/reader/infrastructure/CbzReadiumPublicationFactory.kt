package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ReaderComicPage
import java.io.File
import java.util.Locale
import java.util.zip.ZipFile
import org.readium.r2.shared.publication.Layout
import org.readium.r2.shared.publication.Link
import org.readium.r2.shared.publication.LocalizedString
import org.readium.r2.shared.publication.Manifest
import org.readium.r2.shared.publication.Metadata
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.publication.ReadingProgression
import org.readium.r2.shared.publication.services.PerResourcePositionsService
import org.readium.r2.shared.util.Url
import org.readium.r2.shared.util.asset.AssetRetriever
import org.readium.r2.shared.util.asset.ContainerAsset
import org.readium.r2.shared.util.getOrElse
import org.readium.r2.shared.util.mediatype.MediaType

/** Builds a local image Publication from the downloaded archive itself. */
internal class CbzReadiumPublicationFactory(
    private val assetRetriever: AssetRetriever,
) {
    suspend fun open(file: File, title: String, pageHints: List<ReaderComicPage>): Publication {
        val localPages = indexPages(file, pageHints)
        val asset = assetRetriever.retrieve(file).getOrElse { error ->
            throw IllegalArgumentException("CBZ asset could not be opened: $error")
        }
        val containerAsset = asset as? ContainerAsset
        if (containerAsset == null) {
            asset.close()
            throw IllegalArgumentException("CBZ did not open as an archive")
        }
        val readingOrder = localPages.mapIndexed { index, page ->
            Link(
                href = requireNotNull(Url(page.resourceHref)),
                mediaType = requireNotNull(MediaType(page.mediaType)),
                title = page.title,
                rels = if (index == 0) setOf("cover") else emptySet(),
            )
        }
        return Publication(
            manifest = Manifest(
                metadata = Metadata(
                    identifier = "urn:shuku:cbz:${file.nameWithoutExtension}",
                    type = "https://schema.org/ComicStory",
                    conformsTo = setOf(Publication.Profile.DIVINA),
                    localizedTitle = LocalizedString(title),
                    readingProgression = ReadingProgression.LTR,
                    layout = Layout.FIXED,
                ),
                readingOrder = readingOrder,
                tableOfContents = readingOrder,
            ),
            container = containerAsset.container,
            servicesBuilder = Publication.ServicesBuilder(
                positions = PerResourcePositionsService.createFactory(
                    fallbackMediaType = requireNotNull(MediaType("image/*")),
                ),
            ),
        )
    }

    fun indexPages(file: File, pageHints: List<ReaderComicPage> = emptyList()): List<ReaderComicPage> =
        ZipFile(file).use { archive ->
            val localImageEntries = archive.entries().asSequence()
                .filterNot { it.isDirectory }
                .filter { it.name.substringAfterLast('.', "").lowercase(Locale.ROOT) in IMAGE_EXTENSIONS }
                .onEach { entry ->
                    require(entry.name.isNotBlank() && !entry.name.startsWith('/') && '\\' !in entry.name)
                    require(entry.name.split('/').none { it.isBlank() || it == "." || it == ".." })
                }
                .sortedBy { naturalSortKey(it.name) }
                .toList()
            require(localImageEntries.isNotEmpty()) { "CBZ has no supported image pages" }
            require(localImageEntries.map { it.name.lowercase(Locale.ROOT) }.distinct().size == localImageEntries.size) {
                "CBZ page names are duplicated"
            }
            localImageEntries.mapIndexed { index, entry ->
                val header = ByteArray(16)
                archive.getInputStream(entry).buffered().use { input ->
                    val count = input.read(header)
                    val mediaType = detectMediaType(header.copyOf(count.coerceAtLeast(0)))
                        ?: throw IllegalArgumentException("CBZ page content is unsupported")
                    val hint = pageHints.getOrNull(index)
                    ReaderComicPage(
                        pageIndex = index,
                        resourceHref = encodeComicArchiveEntryHref(entry.name),
                        mediaType = mediaType,
                        title = hint?.title ?: entry.name.substringAfterLast('/'),
                    )
                }
            }
        }

    private fun naturalSortKey(value: String): String = DIGITS.replace(value.lowercase(Locale.ROOT)) { match ->
        match.value.padStart(20, '0')
    }

    private fun detectMediaType(bytes: ByteArray): String? = when {
        bytes.size >= 3 && bytes[0] == 0xFF.toByte() && bytes[1] == 0xD8.toByte() && bytes[2] == 0xFF.toByte() ->
            "image/jpeg"
        bytes.size >= PNG_SIGNATURE.size && PNG_SIGNATURE.indices.all { bytes[it] == PNG_SIGNATURE[it] } ->
            "image/png"
        bytes.size >= 6 && (bytes.copyOfRange(0, 6).decodeToString() == "GIF87a" ||
            bytes.copyOfRange(0, 6).decodeToString() == "GIF89a") -> "image/gif"
        bytes.size >= 12 && bytes.copyOfRange(0, 4).decodeToString() == "RIFF" &&
            bytes.copyOfRange(8, 12).decodeToString() == "WEBP" -> "image/webp"
        else -> null
    }

    private companion object {
        val IMAGE_EXTENSIONS = setOf("jpg", "jpeg", "png", "gif", "webp")
        val DIGITS = Regex("\\d+")
        val PNG_SIGNATURE = byteArrayOf(
            0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
        )
    }
}

internal fun encodeComicArchiveEntryHref(name: String): String = buildString {
    name.encodeToByteArray().forEach { byte ->
        val value = byte.toInt() and 0xFF
        val character = value.toChar()
        if ((character.isLetterOrDigit() && value < 128) || character in "-._~/") {
            append(character)
        } else {
            append('%')
            append(value.toString(16).uppercase(Locale.ROOT).padStart(2, '0'))
        }
    }
}
