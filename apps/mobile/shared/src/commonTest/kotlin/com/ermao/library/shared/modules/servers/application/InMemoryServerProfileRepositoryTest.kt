package com.ermao.library.shared.modules.servers.application

import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlinx.coroutines.runBlocking

class InMemoryServerProfileRepositoryTest {
    @Test
    fun enforcesTheSameSingleActiveAndIdentityRulesAsPersistentStorage() = runBlocking {
        val repository = InMemoryServerProfileRepository()
        repository.upsert(profile("profile-a", "server-a", active = true))
        repository.upsert(profile("profile-b", "server-b", active = false))

        assertFailsWith<DuplicateServerIdentityException> {
            repository.upsert(profile("profile-c", "server-a", active = false))
        }
        assertEquals("profile-a", repository.activeProfile()?.id)

        repository.activate("profile-b")
        assertEquals("profile-b", repository.activeProfile()?.id)
        assertEquals(1, repository.profiles().count(ServerProfile::isActive))

        repository.remove("profile-b")
        assertNull(repository.activeProfile())
        assertEquals(listOf("profile-a"), repository.profiles().map(ServerProfile::id))
    }

    private fun profile(id: String, serverIdentity: String, active: Boolean): ServerProfile {
        val baseUrl = (ServerBaseUrl.parse("https://$id.example") as ServerBaseUrlParseResult.Valid).baseUrl
        return ServerProfile(id, id, baseUrl, serverIdentity, active, TlsMode.SystemTrust)
    }
}
