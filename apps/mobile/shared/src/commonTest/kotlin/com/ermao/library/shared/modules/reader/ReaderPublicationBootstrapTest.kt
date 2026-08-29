package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.application.ReaderBootstrapResult
import com.ermao.library.shared.modules.reader.application.ReaderPublicationBootstrapResult
import com.ermao.library.shared.modules.reader.application.ReaderBootstrapGateway
import com.ermao.library.shared.modules.reader.application.ReaderComicAccess
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import kotlinx.coroutines.runBlocking
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs

class ReaderPublicationBootstrapTest {
    @Test
    fun streamingFormatsResolveWithoutAnOriginalFileOrTransfer() = runBlocking {
        val formats = listOf(ReaderSourceFormat.Pdf, ReaderSourceFormat.Cbz, ReaderSourceFormat.Zip, ReaderSourceFormat.Cbr,
            ReaderSourceFormat.Rar, ReaderSourceFormat.ImageDir)
        for (format in formats) {
            var metadataRequests = 0
            val bootstrap = ReaderBootstrap(
                target = ReaderProgressSyncTarget(namespace(), "book-1", "resource-1", format.readerFormat),
                resource = ReaderBootstrapResource("resource-1", "Book", "book-1", format,
                    "asset-1".takeUnless { format == ReaderSourceFormat.ImageDir }),
                remoteSnapshot = null,
                pdfAccess = if (format == ReaderSourceFormat.Pdf) ReaderPdfAccess("/api/assets/asset-1", 25L * 1024 * 1024) else null,
                comicPages = if (format.isComic) listOf(ReaderComicPage(0, "pages/0", "image/png")) else emptyList(),
                comicAccess = if (format.isComic) ReaderComicAccess(
                    "/api/reader/v4/resources/resource-1/comic/manifest",
                    "/api/reader/v4/resources/resource-1/comic/pages/{pageIndex}", setOf("original", "data-saver")) else null,
            )
            val result = BootstrapReaderPublication(ReaderBootstrapGateway {
                metadataRequests += 1
                ReaderBootstrapResult.Content(bootstrap)
            }).execute(request())
            val source = assertIs<ReaderPublicationBootstrapResult.Content>(result).source
            assertEquals(1, metadataRequests)
            assertEquals(format, source.sourceFormat)
            when {
                format.isComic -> assertIs<RemoteComicReaderSource>(source)
                format == ReaderSourceFormat.Pdf -> assertEquals("/api/assets/asset-1", assertIs<RemoteByteRangeReaderSource>(source).apiPath)
            }
        }
    }

    @Test
    fun reflowableBootstrapCannotCreateAnOnlineSource() = runBlocking {
        for (format in listOf(ReaderSourceFormat.Epub, ReaderSourceFormat.Txt, ReaderSourceFormat.Fb2,
            ReaderSourceFormat.Mobi, ReaderSourceFormat.Azw, ReaderSourceFormat.Azw3, ReaderSourceFormat.Prc)) {
            val bootstrap = ReaderBootstrap(
                target = ReaderProgressSyncTarget(namespace(), "book-1", "resource-1", format.readerFormat),
                resource = ReaderBootstrapResource("resource-1", "Book", "book-1", format, "asset-1"),
                remoteSnapshot = null,
            )

            val result = BootstrapReaderPublication(ReaderBootstrapGateway {
                ReaderBootstrapResult.Content(bootstrap)
            }).execute(request())

            assertEquals(
                "READER_PUBLICATION_LOCAL_REQUIRED",
                assertIs<ReaderPublicationBootstrapResult.Failure>(result).failureCode,
            )
        }
    }

    @Test
    fun everyReflowableBootstrapRejectsServerNavigationUnits() {
        val unit = ReaderNavigationUnit("server-unit", 0, "Server chapter", "chapter.xhtml")
        for (format in listOf(
            ReaderSourceFormat.Epub,
            ReaderSourceFormat.Fb2,
            ReaderSourceFormat.Txt,
            ReaderSourceFormat.Mobi,
            ReaderSourceFormat.Azw,
            ReaderSourceFormat.Azw3,
            ReaderSourceFormat.Prc,
        )) {
            val create = { units: List<ReaderNavigationUnit> ->
                ReaderBootstrap(
                    target = ReaderProgressSyncTarget(namespace(), "book-1", "resource-1", format.readerFormat),
                    resource = ReaderBootstrapResource("resource-1", "Book", "book-1", format, "asset-1"),
                    remoteSnapshot = null,
                    units = units,
                )
            }
            assertEquals(emptyList(), create(emptyList()).units, format.wireValue)
            assertFailsWith<IllegalArgumentException>(format.wireValue) { create(listOf(unit)) }
        }
    }

    @Test
    fun bootstrapFailureCannotStartAnotherAcquisitionPath() = runBlocking {
        val failure = BootstrapReaderPublication(ReaderBootstrapGateway {
            ReaderBootstrapResult.Failure("NETWORK_UNAVAILABLE", true)
        }).execute(request())
        assertEquals("NETWORK_UNAVAILABLE", assertIs<ReaderPublicationBootstrapResult.Failure>(failure).failureCode)
    }

    private fun request() = ReaderBootstrapRequest(profile(), namespace(), "resource-1")
    private fun namespace() = ReaderSyncNamespace("server-1", "user-1", 3)

    private fun profile(): ServerProfile {
        val url = assertIs<ServerBaseUrlParseResult.Valid>(ServerBaseUrl.parse("https://books.example")).baseUrl
        return ServerProfile("profile-1", "Books", url, "server-1", true, TlsMode.SystemTrust)
    }

}
