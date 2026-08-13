package com.ermao.library.shared.modules.downloads.domain

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class ReaderAccessPolicyTest {
    private val namespace = DownloadNamespace("server", "user", 1)
    private val policy = ReaderAccessPolicy()

    @Test
    fun reflowableRequiresMatchingCompletedFingerprint() {
        val old = artifact(DownloadReaderType.Reflowable, "old")
        val request = request(DownloadReaderType.Reflowable, "current", isOnline = true)
        assertEquals(ReaderAccessDecision.NeedsDownload, policy.decide(request, listOf(old)))
        assertIs<ReaderAccessDecision.LocalArtifact>(
            policy.decide(request, listOf(artifact(DownloadReaderType.Reflowable, "current"))),
        )
    }

    @Test
    fun pdfAndComicStreamOnlineUseLocalCompletionOfflineAndOtherwiseFail() {
        for (type in listOf(DownloadReaderType.Pdf, DownloadReaderType.Comic)) {
            assertEquals(
                ReaderAccessDecision.RemoteStream,
                policy.decide(request(type, "fp", isOnline = true), emptyList()),
            )
            assertEquals(
                ReaderAccessDecision.Unavailable("OFFLINE_ARTIFACT_MISSING"),
                policy.decide(request(type, "fp", isOnline = false), emptyList()),
            )
            assertIs<ReaderAccessDecision.LocalArtifact>(
                policy.decide(request(type, "fp", isOnline = false), listOf(artifact(type, "fp"))),
            )
        }
    }

    private fun request(type: DownloadReaderType, fingerprint: String, isOnline: Boolean) =
        ReaderAccessRequest(namespace, "volume", type, fingerprint, isOnline)

    private fun artifact(type: DownloadReaderType, fingerprint: String): CompletedDownloadArtifact {
        val mime = when (type) {
            DownloadReaderType.Pdf -> "application/pdf"
            DownloadReaderType.Comic -> "application/zip"
            else -> "application/epub+zip"
        }
        val descriptor = DownloadDescriptor(
            DownloadIdentity(namespace, "work", "volume", fingerprint),
            "Book",
            null,
            null,
            "Volume",
            type.name,
            type,
            DownloadSource("/api/volumes/volume/file", mime, 10),
        )
        return CompletedDownloadArtifact(descriptor, "local://volume", 10, 1)
    }
}
