package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ReaderComicPage
import java.io.File
import java.nio.file.Files
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import org.readium.r2.shared.publication.Layout
import org.readium.r2.shared.publication.Link
import org.readium.r2.shared.publication.LocalizedString
import org.readium.r2.shared.publication.Manifest
import org.readium.r2.shared.publication.Metadata
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.publication.ReadingProgression
import org.readium.r2.shared.publication.services.PerResourcePositionsService
import org.readium.r2.shared.util.Url
import org.readium.r2.shared.util.data.Container
import org.readium.r2.shared.util.data.ReadError
import org.readium.r2.shared.util.mediatype.MediaType
import org.readium.r2.shared.util.resource.FailureResource
import org.readium.r2.shared.util.resource.InMemoryResource
import org.readium.r2.shared.util.resource.LazyResource
import org.readium.r2.shared.util.resource.Resource

/** Opens a verified Download Center IMAGE_DIR bundle without deriving an archive. */
internal class ImageDirectoryReadiumPublicationFactory {
    fun indexPages(directory: File, expectedResourceId: String): List<ReaderComicPage> =
        loadBundle(directory, expectedResourceId).members.map { member ->
            ReaderComicPage(
                pageIndex = member.sequenceIndex,
                resourceHref = "pages/${member.sequenceIndex}",
                mediaType = member.mimeType,
                title = (member.sequenceIndex + 1).toString(),
            )
        }

    fun open(directory: File, resourceId: String, title: String): Publication {
        val bundle = loadBundle(directory, resourceId)
        val membersByHref = bundle.members.associateBy { "pages/${it.sequenceIndex}" }
        val entries = membersByHref.keys.map { requireNotNull(Url(it)) }.toSet()
        val container = object : Container<Resource> {
            override val entries: Set<Url> = entries

            override fun get(url: Url): Resource {
                val member = membersByHref[url.toString()]
                    ?: return FailureResource(ReadError.Decoding(IllegalArgumentException("IMAGE_DIR_PAGE_OUT_OF_RANGE")))
                return LazyResource {
                    val file = File(directory, member.fileName)
                    try {
                        InMemoryResource(file.readBytes())
                    } catch (error: Exception) {
                        FailureResource(ReadError.Decoding(error))
                    }
                }
            }

            override fun close() = Unit
        }
        val readingOrder = bundle.members.mapIndexed { index, member ->
            Link(
                href = requireNotNull(Url("pages/${member.sequenceIndex}")),
                mediaType = requireNotNull(MediaType(member.mimeType)),
                title = (member.sequenceIndex + 1).toString(),
                rels = if (index == 0) setOf("cover") else emptySet(),
            )
        }
        return Publication(
            manifest = Manifest(
                metadata = Metadata(
                    identifier = "urn:shuku:image-dir:$resourceId",
                    type = "https://schema.org/ComicStory",
                    conformsTo = setOf(Publication.Profile.DIVINA),
                    localizedTitle = LocalizedString(title),
                    readingProgression = ReadingProgression.LTR,
                    layout = Layout.FIXED,
                ),
                readingOrder = readingOrder,
                tableOfContents = readingOrder,
            ),
            container = container,
            servicesBuilder = Publication.ServicesBuilder(
                positions = PerResourcePositionsService.createFactory(
                    fallbackMediaType = requireNotNull(MediaType("image/*")),
                ),
            ),
        )
    }

    private fun loadBundle(directory: File, expectedResourceId: String): BundleManifest {
        require(directory.isDirectory && !Files.isSymbolicLink(directory.toPath())) { "IMAGE_DIR bundle is missing" }
        val manifestFile = File(directory, MANIFEST_NAME)
        require(manifestFile.isFile && !Files.isSymbolicLink(manifestFile.toPath())) { "IMAGE_DIR manifest is missing" }
        require(manifestFile.length() in 1..MAX_MANIFEST_BYTES) { "IMAGE_DIR manifest is too large" }
        val manifest = JSON.decodeFromString<BundleManifest>(manifestFile.readText())
        require(manifest.contractVersion == BUNDLE_CONTRACT_VERSION)
        require(manifest.artifactKind == "OriginalPageSet")
        require(manifest.resourceId == expectedResourceId)
        require(manifest.members.size in 1..MAX_PAGE_COUNT)
        require(manifest.members.map(BundleMember::sequenceIndex) == manifest.members.indices.toList())
        require(manifest.members.map(BundleMember::assetId).distinct().size == manifest.members.size)
        require(manifest.members.sumOf(BundleMember::sizeBytes) == manifest.totalBytes)
        require(manifest.totalBytes in 1..MAX_EXPANDED_BYTES)
        val rootPath = directory.canonicalFile.toPath()
        manifest.members.forEach { member ->
            require(member.assetId.isNotBlank())
            require(member.mimeType in IMAGE_MIME_TYPES)
            require(member.sizeBytes in 1..MAX_PAGE_BYTES)
            require(member.fileName.isSafeFileName())
            val file = File(directory, member.fileName)
            val filePath = file.canonicalFile.toPath()
            require(filePath.parent == rootPath && file.isFile && !Files.isSymbolicLink(filePath))
            require(file.length() == member.sizeBytes)
            require(detectImageMime(file) == member.mimeType) { "IMAGE_DIR page content does not match MIME" }
        }
        return manifest
    }

    @Serializable
    private data class BundleManifest(
        val contractVersion: Int,
        val artifactKind: String,
        val resourceId: String,
        val artifactId: String,
        val totalBytes: Long,
        val members: List<BundleMember>,
    )

    @Serializable
    private data class BundleMember(
        val assetId: String,
        val sequenceIndex: Int,
        val mimeType: String,
        val sizeBytes: Long,
        val fileName: String,
    )

    private fun String.isSafeFileName(): Boolean =
        isNotBlank() && this !in setOf(".", "..") && '/' !in this && '\\' !in this && !startsWith('.')

    private fun detectImageMime(file: File): String? {
        val bytes = ByteArray(16)
        val count = file.inputStream().buffered().use { it.read(bytes) }
        val header = bytes.copyOf(count.coerceAtLeast(0))
        return when {
            header.size >= 3 && header[0] == 0xFF.toByte() && header[1] == 0xD8.toByte() && header[2] == 0xFF.toByte() -> "image/jpeg"
            header.size >= PNG_SIGNATURE.size && PNG_SIGNATURE.indices.all { header[it] == PNG_SIGNATURE[it] } -> "image/png"
            header.size >= 6 && header.copyOfRange(0, 6).decodeToString() in setOf("GIF87a", "GIF89a") -> "image/gif"
            header.size >= 12 && header.copyOfRange(0, 4).decodeToString() == "RIFF" &&
                header.copyOfRange(8, 12).decodeToString() == "WEBP" -> "image/webp"
            else -> null
        }
    }

    private companion object {
        const val BUNDLE_CONTRACT_VERSION = 4
        const val MANIFEST_NAME = "bundle.json"
        const val MAX_MANIFEST_BYTES = 2L * 1024 * 1024
        const val MAX_PAGE_COUNT = 20_000
        const val MAX_PAGE_BYTES = 64L * 1024 * 1024
        const val MAX_EXPANDED_BYTES = 4L * 1024 * 1024 * 1024
        val IMAGE_MIME_TYPES = setOf("image/jpeg", "image/png", "image/gif", "image/webp")
        val PNG_SIGNATURE = byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)
        val JSON = Json { ignoreUnknownKeys = false }
    }
}
