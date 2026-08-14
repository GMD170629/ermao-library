package com.ermao.library.features.library.application

import com.ermao.library.features.content.model.ChapterReadingState
import com.ermao.library.features.content.model.ReadingUnitContent
import com.ermao.library.features.content.model.WorkCard
import com.ermao.library.features.content.model.WorkDetailContent
import com.ermao.library.shared.modules.reader.PublicationFingerprint
import com.ermao.library.shared.modules.reader.ReaderEngine
import com.ermao.library.shared.modules.reader.ReaderEnginePlatform
import com.ermao.library.shared.modules.reader.ReaderProgressPresentationUpdate
import com.ermao.library.shared.modules.reader.ReflowablePublicationLocation
import com.ermao.library.shared.modules.reader.createEngineLocator
import kotlin.test.assertEquals
import org.junit.Test

class DetailViewModelsTest {
    @Test
    fun liveReaderLocationUsesReadingOrderPositionWhenRuntimeHrefDiffers() {
        val content = contentWithChapters(
            ReadingUnitContent(
                id = "chapter-1",
                title = "Chapter 1",
                href = "text/part0003.html",
                sortOrder = 1,
                readingOrderPosition = 3,
            ),
            ReadingUnitContent(
                id = "chapter-2",
                title = "Chapter 2",
                href = "text/part0008_split_000.html",
                sortOrder = 4,
                readingOrderPosition = 10,
            ),
            ReadingUnitContent(
                id = "chapter-3",
                title = "Chapter 3",
                href = "text/part0009.html",
                sortOrder = 5,
                readingOrderPosition = 13,
            ),
        )

        val update = ReaderProgressPresentationUpdate(
            namespaceKey = "server:user",
            workId = "work-1",
            volumeId = "volume-1",
            percent = 42.0,
            location = ReflowablePublicationLocation(
                publication = PublicationFingerprint(
                    originalFileHash = "sha256:${"a".repeat(64)}",
                    parser = "readium:test",
                    normalization = "readium:test",
                ),
                engineLocator = createEngineLocator(
                    engine = ReaderEngine.Readium,
                    platform = ReaderEnginePlatform.Android,
                    version = "readium-kotlin:test",
                    payloadJson = """{"href":"text/part0008_split_001.html","type":"application/xhtml+xml","locations":{"cssSelector":"body","fragments":["visible"],"position":11}}""",
                ),
            ),
            chapterTitle = "Chapter 2",
            capturedAtEpochMillis = 123,
        )
        val updated = content.applying(update, selectedVolumeId = "volume-1")

        assertEquals(
            listOf(ChapterReadingState.Read, ChapterReadingState.Current, ChapterReadingState.Unread),
            updated.readingUnits.map(ReadingUnitContent::readingState),
        )
        assertEquals(listOf(null, 42, null), updated.readingUnits.map(ReadingUnitContent::progressPercent))
        assertEquals(content, content.applying(update, selectedVolumeId = "volume-2"))
    }

    private fun contentWithChapters(vararg chapters: ReadingUnitContent): WorkDetailContent = WorkDetailContent(
        work = WorkCard(
            id = "work-1",
            title = "Book",
            author = "Author",
            coverUrl = "",
            mediaKinds = listOf("EBOOK"),
            progressPercent = null,
        ),
        seriesId = null,
        seriesName = null,
        authorFacetId = null,
        description = null,
        tags = emptyList(),
        media = emptyList(),
        selectedMediaKind = "EBOOK",
        readingUnits = chapters.toList(),
    )
}
