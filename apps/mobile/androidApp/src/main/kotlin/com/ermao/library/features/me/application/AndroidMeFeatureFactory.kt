package com.ermao.library.features.me.application

import androidx.lifecycle.ViewModelProvider
import com.ermao.library.features.me.model.MeAccountViewState
import com.ermao.library.shared.modules.auth.domain.AppSession
import com.ermao.library.shared.modules.personalsettings.createPersonalSettingsContext
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsRepository
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsLocale
import com.ermao.library.shared.modules.servers.domain.TlsMode

object AndroidMeFeatureFactory {
    fun viewModelFactory(
        repository: PersonalSettingsRepository,
        session: AppSession.Authenticated,
        sideEffects: SettingsSideEffects,
        appVersion: String,
    ): ViewModelProvider.Factory {
        val context = createPersonalSettingsContext(
            profileId = session.profile.id,
            displayName = session.profile.displayName,
            baseUrl = session.profile.baseUrl.value,
            serverIdentity = session.profile.serverIdentity,
            acceptsInsecureTls = session.profile.tlsMode == TlsMode.InsecureSkipAllValidation,
        )
        return MeViewModel.factory(
            client = RepositorySettingsClient(repository, context),
            sideEffects = sideEffects,
            serverName = session.profile.displayName,
            serverBaseUrl = session.profile.baseUrl.value,
            appVersion = appVersion,
            initialAccount = MeAccountViewState(
                id = session.identity.userId,
                displayName = session.identity.displayName,
                email = session.identity.email,
                avatarUrl = session.identity.avatarUrl,
            ),
            initialLocale = PersonalSettingsLocale.fromWireValue(session.identity.locale.orEmpty())
                ?: PersonalSettingsLocale.EnUs,
        )
    }
}
