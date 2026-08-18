package com.ermao.library.shared.modules.downloads.domain

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class ReaderAccessPolicyTest {
    private val namespace = DownloadNamespace("server", "user", 1)
    private val policy = ReaderAccessPolicy()

    @Test
    fun completedArtifactForTheVolumeWins() {
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

    private fun request(type: DownloadReaderType, isOnline: Boolean) =
        ReaderAccessRequest(namespace, "volume", type, isOnline)

    private fun artifact(type: DownloadReaderType): CompletedDownloadArtifact {
        val mime = when (type) {
            DownloadReaderType.Pdf -> "application/pdf"
            DownloadReaderType.Comic -> "application/zip"
            else -> "application/epub+zip"
        }
        val descriptor = DownloadDescriptor(
            DownloadIdentity(namespace, "work", "volume"),
            "Book",
            null,
            null,
            "Volume",
            type.name,
            type,
            DownloadSource("/api/volumes/volume/file", mime, 10),
            "version",
            IMPLICIT_DOWNLOAD_VERSION_SOURCE_KEY,
            null,
            false,
        )
        return CompletedDownloadArtifact(descriptor, "local://volume", 10, 1)
    }
}
