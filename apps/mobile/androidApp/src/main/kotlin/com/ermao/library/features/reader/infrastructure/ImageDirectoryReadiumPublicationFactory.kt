package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ReaderComicPage
import com.ermao.library.shared.modules.reader.readerSafetyAllowedComicPageMimeTypes
import com.ermao.library.shared.modules.reader.readerSafetyComicExpandedMaxBytes
import com.ermao.library.shared.modules.reader.readerSafetyComicManifestMaxBytes
import com.ermao.library.shared.modules.reader.readerSafetyComicPageMaxBytes
import com.ermao.library.shared.modules.reader.readerSafetyComicPageMaxCount
import com.ermao.library.shared.modules.reader.readerSafetyComicPageMimeType
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
        require(manifestFile.length() in 1..readerSafetyComicManifestMaxBytes()) {
            "IMAGE_DIR manifest is too large"
        }
        val manifest = JSON.decodeFromString<BundleManifest>(manifestFile.readText())
        require(manifest.contractVersion == BUNDLE_CONTRACT_VERSION)
        require(manifest.artifactKind == "OriginalPageSet")
        require(manifest.resourceId == expectedResourceId)
        require(manifest.members.isNotEmpty() &&
            manifest.members.size.toLong() <= readerSafetyComicPageMaxCount())
        require(manifest.members.map(BundleMember::sequenceIndex) == manifest.members.indices.toList())
        require(manifest.members.map(BundleMember::assetId).distinct().size == manifest.members.size)
        require(manifest.members.sumOf(BundleMember::sizeBytes) == manifest.totalBytes)
        require(manifest.totalBytes in 1..readerSafetyComicExpandedMaxBytes())
        val rootPath = directory.canonicalFile.toPath()
        val readableMembers = manifest.members.mapNotNull { member ->
            require(member.assetId.isNotBlank())
            require(member.fileName.isSafeFileName())
            val file = File(directory, member.fileName)
            val filePath = file.canonicalFile.toPath()
            require(filePath.parent == rootPath && !Files.isSymbolicLink(filePath))
            if (member.mimeType !in readerSafetyAllowedComicPageMimeTypes() ||
                member.sizeBytes !in 1..readerSafetyComicPageMaxBytes() ||
                !file.isFile || file.length() != member.sizeBytes ||
                detectImageMime(file) != member.mimeType
            ) {
                return@mapNotNull null
            }
            member
        }
        require(readableMembers.isNotEmpty()) { "IMAGE_DIR contains no readable pages" }
        return manifest.copy(members = readableMembers)
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
            header.size >= 3 && header[0] == 0xFF.toByte() && header[1] == 0xD8.toByte() && header[2] == 0xFF.toByte() ->
                readerSafetyComicPageMimeType(".jpg")
            header.size >= PNG_SIGNATURE.size && PNG_SIGNATURE.indices.all { header[it] == PNG_SIGNATURE[it] } ->
                readerSafetyComicPageMimeType(".png")
            header.size >= 6 && header.copyOfRange(0, 6).decodeToString() in setOf("GIF87a", "GIF89a") ->
                readerSafetyComicPageMimeType(".gif")
            header.size >= 12 && header.copyOfRange(0, 4).decodeToString() == "RIFF" &&
                header.copyOfRange(8, 12).decodeToString() == "WEBP" ->
                readerSafetyComicPageMimeType(".webp")
            else -> null
        }
    }

    private companion object {
        const val BUNDLE_CONTRACT_VERSION = 4
        const val MANIFEST_NAME = "bundle.json"
        val PNG_SIGNATURE = byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)
        val JSON = Json { ignoreUnknownKeys = false }
    }
}
