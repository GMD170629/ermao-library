package com.ermao.library.features.reader.infrastructure

import android.graphics.BitmapFactory
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

/** Builds an image Publication only after the downloaded archive matches the server canonical index. */
internal class CbzReadiumPublicationFactory(
    private val assetRetriever: AssetRetriever,
) {
    suspend fun open(file: File, title: String, canonicalPages: List<ReaderComicPage>): Publication {
        validateCanonicalIndex(file, canonicalPages)
        val asset = assetRetriever.retrieve(file).getOrElse { error ->
            throw IllegalArgumentException("CBZ asset could not be opened: $error")
        }
        val containerAsset = asset as? ContainerAsset
        if (containerAsset == null) {
            asset.close()
            throw IllegalArgumentException("CBZ did not open as an archive")
        }
        val readingOrder = canonicalPages.mapIndexed { index, page ->
            Link(
                href = requireNotNull(Url(page.resourceHref)),
                mediaType = requireNotNull(MediaType(page.mediaType)),
                title = page.resourceHref.substringAfterLast('/'),
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

    private fun validateCanonicalIndex(file: File, canonicalPages: List<ReaderComicPage>) {
        require(canonicalPages.isNotEmpty()) { "CBZ canonical page index is empty" }
        require(canonicalPages.map(ReaderComicPage::pageIndex) == canonicalPages.indices.toList()) {
            "CBZ canonical page indexes are not contiguous"
        }
        require(canonicalPages.map { it.resourceHref.lowercase(Locale.ROOT) }.distinct().size == canonicalPages.size) {
            "CBZ canonical page hrefs are duplicated"
        }
        ZipFile(file).use { archive ->
            val localImageEntries = archive.entries().asSequence()
                .filterNot { it.isDirectory }
                .filter { it.name.substringAfterLast('.', "").lowercase(Locale.ROOT) in IMAGE_EXTENSIONS }
                .toList()
            require(localImageEntries.size == canonicalPages.size) {
                "CBZ canonical page count does not match the archive"
            }
            val localNames = localImageEntries.map { it.name }.toSet()
            require(localNames == canonicalPages.map(ReaderComicPage::resourceHref).toSet()) {
                "CBZ canonical hrefs do not match the archive"
            }
            canonicalPages.forEach { page ->
                val entry = requireNotNull(archive.getEntry(page.resourceHref)) {
                    "CBZ canonical page is missing"
                }
                archive.getInputStream(entry).buffered().use { input ->
                    val bytes = input.readBytes()
                    require(detectMediaType(bytes) == page.mediaType) {
                        "CBZ canonical media type does not match page content"
                    }
                    if (page.width != null || page.height != null) {
                        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
                        require(bounds.outWidth > 0 && bounds.outHeight > 0) {
                            "CBZ page dimensions could not be read"
                        }
                        require(page.width == null || page.width == bounds.outWidth) {
                            "CBZ canonical width does not match page content"
                        }
                        require(page.height == null || page.height == bounds.outHeight) {
                            "CBZ canonical height does not match page content"
                        }
                    }
                }
            }
        }
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
        val PNG_SIGNATURE = byteArrayOf(
            0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
        )
    }
}
