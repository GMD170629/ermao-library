package com.ermao.library.shared.modules.downloads.domain

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class ReaderAccessPolicyTest {
    private val namespace = DownloadNamespace("server", "user", 1)
    private val policy = ReaderAccessPolicy()

    @Test
    fun completedArtifactForTheResourceWins() {
        val old = artifact(DownloadReaderType.Reflowable)
        val request = request(DownloadReaderType.Reflowable, isOnline = true)

        assertEquals(ReaderAccessDecision.LocalArtifact(old), policy.decide(request, listOf(old)))
    }

    @Test
    fun pdfAndComicStreamOnlineUseLocalCompletionOfflineAndOtherwiseFail() {
        for (type in listOf(DownloadReaderType.Pdf, DownloadReaderType.Comic)) {
            assertEquals(
                ReaderAccessDecision.RemoteStream,
                policy.decide(request(type, isOnline = true), emptyList()),
            )
            assertEquals(
                ReaderAccessDecision.Unavailable("OFFLINE_ARTIFACT_MISSING"),
                policy.decide(request(type, isOnline = false), emptyList()),
            )
            assertIs<ReaderAccessDecision.LocalArtifact>(
                policy.decide(request(type, isOnline = false), listOf(artifact(type))),
            )
        }
    }

    @Test
    fun audioRequiresTheExistingExplicitNativeSupportContract() {
        assertEquals(
            ReaderAccessDecision.Unavailable("READER_TYPE_NOT_SUPPORTED"),
            policy.decide(request(DownloadReaderType.Audio, isOnline = true), emptyList()),
        )
    }

    private fun request(type: DownloadReaderType, isOnline: Boolean) =
        ReaderAccessRequest(namespace, "resource", type, isOnline)

    private fun artifact(type: DownloadReaderType): CompletedDownloadArtifact {
        val mime = when (type) {
            DownloadReaderType.Pdf -> "application/pdf"
            DownloadReaderType.Comic -> "application/vnd.comicbook+zip"
            DownloadReaderType.Audio -> "audio/mpeg"
            else -> "application/epub+zip"
        }
        val descriptor = DownloadDescriptor(
            identity = DownloadIdentity(namespace, "book", "resource", "asset"),
            bookTitle = "Book",
            bookAuthor = null,
            coverApiPath = null,
            resourceTitle = "Resource",
            format = type.name,
            readerType = type,
            source = DownloadSource("/api/assets/asset", mime, 10),
        )
        return CompletedDownloadArtifact(descriptor, "local://asset", 10, 1)
    }
}
