package com.ermao.library.features.reader.infrastructure

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import java.io.File
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AndroidReaderPublicationStoreInstrumentedTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun removingAutomaticReplicaPreservesLegacyPdfRangeCache() = runBlocking {
        val legacyCache = File(context.cacheDir, "reader/pdf-range-v3")
        val cacheExistedBefore = legacyCache.exists()
        if (!cacheExistedBefore) check(legacyCache.mkdirs() || legacyCache.isDirectory)
        val marker = legacyCache.resolve(".contract-test-${UUID.randomUUID()}")
        marker.writeText("legacy-pdf-range")
        val namespace = ReaderSyncNamespace(
            serverIdentity = "contract-test-${UUID.randomUUID()}",
            userId = "contract-test-user",
            authorizationVersion = 0,
        )

        try {
            AndroidReaderPublicationStore(context, namespace)
                .removeAutomaticReplica("resource-${UUID.randomUUID()}", "asset-${UUID.randomUUID()}")

            assertTrue("Legacy PDF range cache was removed", marker.exists())
        } finally {
            marker.delete()
            if (!cacheExistedBefore && legacyCache.isDirectory && legacyCache.list()?.isEmpty() == true) {
                legacyCache.delete()
            }
        }
    }

    @Test
    fun openingPublicationStorePreservesLegacyHashedArtifacts() {
        val namespace = ReaderSyncNamespace(
            serverIdentity = "contract-test-${UUID.randomUUID()}",
            userId = "contract-test-user",
            authorizationVersion = 0,
        )
        val accountRoot = context.filesDir
            .resolve("reader-publications-v3")
            .resolve(sha256(readerAccountStorageKey(namespace)))
        val publicationRoot = accountRoot.resolve(sha256(namespace.stableKey))
        val rootExistedBefore = publicationRoot.exists()
        check(publicationRoot.mkdirs() || publicationRoot.isDirectory)
        val artifact = publicationRoot.resolve("legacy.epub")
        val sidecar = publicationRoot.resolve("legacy.epub.sha256")
        artifact.writeText("legacy-reader-publication")
        sidecar.writeText("legacy-hash")

        try {
            AndroidReaderPublicationStore(context, namespace)

            assertTrue("Legacy publication was removed", artifact.exists())
            assertTrue("Legacy publication sidecar was removed", sidecar.exists())
        } finally {
            artifact.delete()
            sidecar.delete()
            if (!rootExistedBefore && publicationRoot.isDirectory && publicationRoot.list()?.isEmpty() == true) {
                publicationRoot.delete()
            }
            if (!rootExistedBefore && accountRoot.isDirectory && accountRoot.list()?.isEmpty() == true) {
                accountRoot.delete()
            }
        }
    }
}
