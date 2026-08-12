package com.ermao.library.shared.modules.servers.infrastructure

import com.ermao.library.shared.core.storage.PlatformStoragePayload
import com.ermao.library.shared.modules.servers.application.DuplicateServerIdentityException
import com.ermao.library.shared.modules.servers.application.UnknownServerProfileException
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

class SerializedServerProfileRepositoryTest {
    @Test
    fun migratesStageZeroArrayToVersionTwoWithoutChangingProfileIds() = runBlocking {
        val store = MemoryPayloadStore(
            """[{"id":"legacy-id","displayName":"Home","baseUrl":"https://home.example/base","serverIdentity":"server-a","isActive":true,"tlsMode":"SystemTrust"}]""",
        )
        val repository = SerializedServerProfileRepository(store)

        assertEquals("legacy-id", repository.activeProfile()?.id)

        val migrated = Json.parseToJsonElement(requireNotNull(store.payload)).jsonObject
        assertEquals("2", migrated.getValue("schemaVersion").jsonPrimitive.content)
        assertEquals("legacy-id", migrated.getValue("activeProfileId").jsonPrimitive.content)
        assertTrue("isActive" !in requireNotNull(store.payload))
        assertEquals(1, store.saveCount)
    }

    @Test
    fun rejectsDuplicateServerIdentityWithoutChangingStoredProfiles() = runBlocking {
        val store = MemoryPayloadStore()
        val repository = SerializedServerProfileRepository(store)
        repository.upsert(profile("profile-a", "server-shared", active = true))
        val beforeRejectedWrite = store.payload
        val savesBeforeRejectedWrite = store.saveCount

        assertFailsWith<DuplicateServerIdentityException> {
            repository.upsert(profile("profile-b", "server-shared", active = false))
        }

        assertEquals(beforeRejectedWrite, store.payload)
        assertEquals(savesBeforeRejectedWrite, store.saveCount)
        assertEquals(listOf("profile-a"), repository.profiles().map(ServerProfile::id))
    }

    @Test
    fun activationAndRemovalEachPersistOneCompleteAggregate() = runBlocking {
        val store = MemoryPayloadStore()
        val repository = SerializedServerProfileRepository(store)
        repository.upsert(profile("profile-a", "server-a", active = true))
        repository.upsert(profile("profile-b", "server-b", active = false))

        val beforeActivate = store.saveCount
        repository.activate("profile-b")
        assertEquals(beforeActivate + 1, store.saveCount)
        assertEquals("profile-b", repository.activeProfile()?.id)

        val beforeInactiveRemoval = store.saveCount
        repository.remove("profile-a")
        assertEquals(beforeInactiveRemoval + 1, store.saveCount)
        assertEquals("profile-b", repository.activeProfile()?.id)

        val beforeActiveRemoval = store.saveCount
        repository.remove("profile-b")
        assertEquals(beforeActiveRemoval + 1, store.saveCount)
        assertNull(repository.activeProfile())
        assertEquals(emptyList(), repository.profiles())
    }

    @Test
    fun unknownActivationFailsWithoutPersistingPartialState() = runBlocking {
        val store = MemoryPayloadStore()
        val repository = SerializedServerProfileRepository(store)
        repository.upsert(profile("profile-a", "server-a", active = true))
        val beforeFailure = store.payload
        val savesBeforeFailure = store.saveCount

        assertFailsWith<UnknownServerProfileException> { repository.activate("missing") }

        assertEquals(beforeFailure, store.payload)
        assertEquals(savesBeforeFailure, store.saveCount)
        assertEquals("profile-a", repository.activeProfile()?.id)
    }

    @Test
    fun unknownSchemaVersionFailsClosedWithoutRewritingPayload() = runBlocking {
        val payload = """{"schemaVersion":99,"activeProfileId":null,"profiles":[]}"""
        val store = MemoryPayloadStore(payload)
        val repository = SerializedServerProfileRepository(store)

        val failure = assertFailsWith<ServerProfileStorageException> { repository.profiles() }

        assertEquals("UNSUPPORTED_SCHEMA_VERSION", failure.reasonCode)
        assertEquals(payload, store.payload)
        assertEquals(0, store.saveCount)
    }

    @Test
    fun malformedAndStructurallyInvalidPayloadsFailClosed() = runBlocking {
        val malformed = SerializedServerProfileRepository(MemoryPayloadStore("{"))
        assertEquals(
            "MALFORMED_JSON",
            assertFailsWith<ServerProfileStorageException> { malformed.profiles() }.reasonCode,
        )

        val missingActive = SerializedServerProfileRepository(
            MemoryPayloadStore(
                """{"schemaVersion":2,"activeProfileId":"missing","profiles":[]}""",
            ),
        )
        assertEquals(
            "ACTIVE_PROFILE_MISSING",
            assertFailsWith<ServerProfileStorageException> { missingActive.profiles() }.reasonCode,
        )
    }

    private fun profile(id: String, serverIdentity: String, active: Boolean): ServerProfile {
        val baseUrl = (ServerBaseUrl.parse("https://$id.example") as ServerBaseUrlParseResult.Valid).baseUrl
        return ServerProfile(id, id, baseUrl, serverIdentity, active, TlsMode.SystemTrust)
    }

    private class MemoryPayloadStore(
        initialPayload: String? = null,
    ) : ServerProfilePayloadStore {
        var payload: String? = initialPayload
            private set
        var saveCount: Int = 0
            private set

        override fun loadProfilesPayload() = PlatformStoragePayload(payload)

        override fun saveProfiles(payload: String) {
            this.payload = payload
            saveCount += 1
        }
    }
}
