package com.ermao.library.shared.modules.library.infrastructure

import com.ermao.library.shared.core.network.ApiEnvelopeDecoder
import com.ermao.library.shared.core.network.ApiResult
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlinx.serialization.json.Json

class WorkDetailWireTest {
    private val decoder = ApiEnvelopeDecoder(Json { ignoreUnknownKeys = false })

    @Test
    fun decodesBookWithResourcesAndAssetsWithoutVersionLayer() {
        val decoded = decoder.decode(
            statusCode = 200,
            body = BOOK_DETAIL_FIXTURE,
            dataDeserializer = BookPayloadWire.serializer(),
        )
        val book = assertIs<ApiResult.Success<BookPayloadWire>>(decoded).value.toDomain()
        val resource = book.resources.single()
        val asset = resource.assets.single()

        assertEquals("book-1", book.id)
        assertEquals("source-node-1", book.sourceNodeId)
        assertEquals("resource-1", resource.id)
        assertEquals("book-1", resource.bookId)
        assertEquals("EPUB", resource.format)
        assertEquals("asset-1", asset.id)
        assertEquals("Library/Book 1.epub", asset.path)
        assertEquals("resource-1", asset.resourceId)
        assertEquals("/api/assets/asset-1/content", asset.url)
    }

    @Test
    fun mixedResourceFormatsRemainResourcesOfTheSameBook() {
        val decoded = decoder.decode(
            statusCode = 200,
            body = MIXED_RESOURCE_BOOK_FIXTURE,
            dataDeserializer = BookPayloadWire.serializer(),
        )
        val book = assertIs<ApiResult.Success<BookPayloadWire>>(decoded).value.toDomain()

        assertEquals("book-mixed", book.id)
        assertEquals(3, book.resources.size)
        assertEquals(listOf("EPUB", "CBZ", "M4B"), book.resources.map { it.format })
        assertEquals(setOf("book-mixed"), book.resources.map { it.bookId }.toSet())
    }
}

private const val BOOK_DETAIL_FIXTURE = """{"ok":true,"data":{"book":{"id":"book-1","libraryId":"library-1","sourceNodeId":"source-node-1","title":"Book 1","author":null,"description":"Description","seriesName":"Series","seriesIndex":1.0,"visibilityState":"ACTIVE","curationState":"NONE","publicationStatus":"ONGOING","trackingStatus":"TRACKING","metadataQuality":90,"coverStatus":"READY","coverPath":null,"coverUrl":"/api/books/book-1/cover","tags":["tag"],"ignored":false,"organized":true,"addedAt":"2026-08-01T00:00:00Z","createdAt":"2026-08-01T00:00:00Z","updatedAt":"2026-08-02T00:00:00Z","gradient":"#112233","resourceImportSummary":{"ready":1,"pending":0,"failed":0},"completed":false,"continueResourceId":"resource-1","continueResourceTitle":"Resource 1","continueResourceProgress":12.5,"resources":[{"id":"resource-1","bookId":"book-1","sourceNodeId":"source-node-1","title":"Resource 1","description":null,"resourceIndex":1.0,"sortOrder":0,"format":"EPUB","readerType":"reflowable","kindleSendAvailable":true,"publisher":"Publisher","publishedAt":"2026-08-01","language":"zh-CN","isbn":null,"identifier":"id-1","narrator":null,"abridged":false,"importStatus":"READY","importError":null,"sizeBytes":1024,"pageCount":12,"chapterCount":3,"durationMs":null,"trackCount":null,"coverStatus":"READY","coverPath":null,"coverUrl":"/api/books/book-1/resources/resource-1/cover","progress":12.5,"lastReadAt":null,"hidden":false,"readable":true,"resourceCompleted":false,"assets":[{"id":"asset-1","title":"Book 1.epub","path":"Library/Book 1.epub","resourceId":"resource-1","sourceNodeId":"source-node-1","role":"PUBLICATION","mimeType":"application/epub+zip","sizeBytes":1024,"size":"1 KB","mtimeMs":1722470400000,"durationMs":null,"codec":null,"bitrate":null,"sampleRate":null,"channels":null,"discNumber":null,"trackNumber":null,"sortOrder":0,"url":"/api/assets/asset-1/content","downloadUrl":"/api/assets/asset-1/download"}]}]}}}"""

private val MIXED_RESOURCE_BOOK_FIXTURE = """{"ok":true,"data":{"book":{"id":"book-mixed","libraryId":"library-1","sourceNodeId":"source-node-1","title":"Mixed book","author":"Author","description":null,"seriesName":null,"seriesIndex":null,"visibilityState":"ACTIVE","curationState":"NONE","publicationStatus":"UNKNOWN","trackingStatus":"UNTRACKED","metadataQuality":0,"coverStatus":"UNKNOWN","coverUrl":"/api/books/book-mixed/cover","resourceImportSummary":{"ready":3,"pending":0,"failed":0},"completed":false,"resources":[${resourceFixture("resource-epub", "EPUB", "reflowable")},${resourceFixture("resource-cbz", "CBZ", "comic")},${resourceFixture("resource-audio", "M4B", "audio")}]}}}"""

private fun resourceFixture(id: String, format: String, readerType: String) =
    """{"id":"$id","bookId":"book-mixed","sourceNodeId":"source-node-1","title":"$id","format":"$format","readerType":"$readerType","assets":[]}"""
