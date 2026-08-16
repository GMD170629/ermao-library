package com.ermao.library.shared.modules.auth.domain

import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerConnectionDraft
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import kotlin.test.Test
import kotlin.test.assertEquals

class AppSessionSnapshotTest {
    @Test
    fun everyFrozenSessionStateHasAStableSwiftSnapshotKind() {
        val profile = profile()
        val draft = ServerConnectionDraft("Books", "https://books.example/base")
        val identity = identity()
        val authorization = authorization()
        val sessions = listOf(
            AppSession.NoServer to AppSessionKind.NoServer,
            AppSession.CheckingServer(draft) to AppSessionKind.CheckingServer,
            AppSession.ServerConnectionFailed(draft, ServerConnectionFailureCode.Unavailable) to
                AppSessionKind.ServerConnectionFailed,
            AppSession.TlsRisk(draft, "TLS_SYSTEM_TRUST_FAILED") to AppSessionKind.TlsRisk,
            AppSession.SetupRequired(profile) to AppSessionKind.SetupRequired,
            AppSession.SettingUp(profile) to AppSessionKind.SettingUp,
            AppSession.SetupFailed(profile, "VALIDATION") to AppSessionKind.SetupFailed,
            AppSession.SignedOut(profile) to AppSessionKind.SignedOut,
            AppSession.Authenticating(profile) to AppSessionKind.Authenticating,
            AppSession.LoginFailed(profile, "reader@example.com", "INVALID_CREDENTIALS") to
                AppSessionKind.LoginFailed,
            AppSession.AccountDisabled(profile, "reader@example.com") to AppSessionKind.AccountDisabled,
            AppSession.Authenticated(profile, identity, authorization) to AppSessionKind.Authenticated,
            AppSession.SessionExpired(profile, identity) to AppSessionKind.SessionExpired,
            AppSession.IncompatibleServer(draft, "UNSUPPORTED_SERVER_PROTOCOL") to
                AppSessionKind.IncompatibleServer,
        )

        assertEquals(AppSessionKind.entries.toSet(), sessions.map { it.second }.toSet())
        sessions.forEach { (session, kind) -> assertEquals(kind, session.toSnapshot().kind) }
    }

    @Test
    fun authenticatedSnapshotUsesAuthorizationAndPrivateNamespaceTruth() {
        val snapshot = AppSession.Authenticated(profile(), identity(), authorization()).toSnapshot()

        assertEquals("server-fixture", snapshot.profileServerIdentity)
        assertEquals("user-1", snapshot.userId)
        assertEquals("https://books.example/api/auth/avatar", snapshot.userAvatarUrl)
        assertEquals("en-US", snapshot.userLocale)
        assertEquals(true, snapshot.isAdmin)
        assertEquals(true, snapshot.canManageSystem)
        assertEquals(false, snapshot.allLibraryScopes)
        assertEquals(true, snapshot.canViewManualImports)
        assertEquals(7, snapshot.authorizationVersion)
        assertEquals(listOf("folder-a", "folder-b"), snapshot.monitorFolderIds)
    }

    private fun profile(): ServerProfile {
        val baseUrl = (ServerBaseUrl.parse("https://books.example/base") as ServerBaseUrlParseResult.Valid).baseUrl
        return ServerProfile(
            id = "server-fixture",
            displayName = "Books",
            baseUrl = baseUrl,
            serverIdentity = "server-fixture",
            isActive = true,
            tlsMode = TlsMode.SystemTrust,
        )
    }

    private fun identity() = SessionIdentity(
        userId = "user-1",
        email = "reader@example.com",
        displayName = "Reader",
        avatarUrl = "https://books.example/api/auth/avatar",
        locale = "en-US",
        namespace = PrivateDataNamespace(
            serverIdentity = "server-fixture",
            userId = "user-1",
            authorizationVersion = 7,
        ),
    )

    private fun authorization() = Authorization(
        isAdmin = true,
        canManageSystem = true,
        allLibraryScopes = false,
        monitorFolderIds = setOf("folder-b", "folder-a"),
        canViewManualImports = true,
        authorizationVersion = 7,
    )
}
