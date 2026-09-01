package com.ermao.library.shared.core.network

import io.ktor.utils.io.ByteChannel
import io.ktor.utils.io.writeFully
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class AuthenticatedMediaStreamTest {
    @Test
    fun firstChunkIsConsumedWhileTheResponseTailRemainsOpen() = runBlocking {
        val body = ByteChannel(autoFlush = true)
        val allowTail = CompletableDeferred<Unit>()
        val writer = launch {
            body.writeFully(byteArrayOf(1, 2, 3))
            allowTail.await()
            body.writeFully(byteArrayOf(4, 5, 6))
            body.flushAndClose()
        }
        val stream = AuthenticatedMediaStream(206, emptyMap(), body)
        try {
            assertEquals(listOf<Byte>(1, 2, 3), withTimeout(1_000) { stream.read(3) }.toList())
            assertFalse(allowTail.isCompleted)
            allowTail.complete(Unit)
            assertEquals(listOf<Byte>(4, 5, 6), withTimeout(1_000) { stream.read(3) }.toList())
            writer.join()
        } finally {
            stream.close()
            allowTail.complete(Unit)
            writer.cancel()
        }
    }
}
