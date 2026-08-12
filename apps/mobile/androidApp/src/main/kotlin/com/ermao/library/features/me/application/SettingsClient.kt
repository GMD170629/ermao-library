package com.ermao.library.features.me.application

import com.ermao.library.shared.modules.personalsettings.PersonalSettingsRepository
import com.ermao.library.shared.modules.personalsettings.PersonalAccount
import com.ermao.library.shared.modules.personalsettings.PersonalAvatarMimeType
import com.ermao.library.shared.modules.personalsettings.PersonalAvatar
import com.ermao.library.shared.modules.personalsettings.PersonalAvatarUpload
import com.ermao.library.shared.modules.personalsettings.PersonalPasswordChange
import com.ermao.library.shared.modules.personalsettings.PersonalPreferences
import com.ermao.library.shared.modules.personalsettings.PersonalServerAbout
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsContext
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsLocale
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsResult
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsSnapshot
import com.ermao.library.features.me.model.SanitizedAvatar
import com.ermao.library.features.me.model.SanitizedAvatarMimeType

interface SettingsClient {
    suspend fun load(): PersonalSettingsResult<PersonalSettingsSnapshot>
    suspend fun loadAvatar(etag: String? = null): PersonalSettingsResult<PersonalAvatar>
    suspend fun updateName(name: String): PersonalSettingsResult<PersonalAccount>
    suspend fun updateEmail(email: String, currentPassword: String): PersonalSettingsResult<PersonalAccount>
    suspend fun updatePassword(currentPassword: String, newPassword: String): PersonalSettingsResult<PersonalPasswordChange>
    suspend fun uploadAvatar(avatar: SanitizedAvatar): PersonalSettingsResult<PersonalAccount>
    suspend fun deleteAvatar(): PersonalSettingsResult<PersonalAccount>
    suspend fun updateLocale(locale: PersonalSettingsLocale): PersonalSettingsResult<PersonalPreferences>
    suspend fun loadServerAbout(): PersonalSettingsResult<PersonalServerAbout>
}

class RepositorySettingsClient(
    private val repository: PersonalSettingsRepository,
    private val context: PersonalSettingsContext,
) : SettingsClient {
    override suspend fun load() = repository.loadSettings(context)
    override suspend fun loadAvatar(etag: String?) = repository.loadAvatar(context, etag)
    override suspend fun updateName(name: String) = repository.updateName(context, name)
    override suspend fun updateEmail(email: String, currentPassword: String) =
        repository.updateEmail(context, email, currentPassword)
    override suspend fun updatePassword(currentPassword: String, newPassword: String) =
        repository.updatePassword(context, currentPassword, newPassword)
    override suspend fun uploadAvatar(avatar: SanitizedAvatar) = repository.uploadAvatar(
        context,
        PersonalAvatarUpload(
            bytes = avatar.bytes,
            mimeType = when (avatar.mimeType) {
                SanitizedAvatarMimeType.Jpeg -> PersonalAvatarMimeType.Jpeg
                SanitizedAvatarMimeType.Png -> PersonalAvatarMimeType.Png
                SanitizedAvatarMimeType.Webp -> PersonalAvatarMimeType.Webp
            },
        ),
    )
    override suspend fun deleteAvatar() = repository.deleteAvatar(context)
    override suspend fun updateLocale(locale: PersonalSettingsLocale) = repository.updateLocale(context, locale)
    override suspend fun loadServerAbout() = repository.loadServerAbout(context)
}

interface SettingsSideEffects {
    suspend fun refreshSession()
    suspend fun purgeCurrentNamespace()
    suspend fun logoutAfterPasswordChange()
    suspend fun logout()
    fun requireReauthentication()
}
