package com.ermao.library.shared.modules.personalsettings.application

import com.ermao.library.shared.modules.personalsettings.domain.PersonalAccount
import com.ermao.library.shared.modules.personalsettings.domain.PersonalAvatar
import com.ermao.library.shared.modules.personalsettings.domain.PersonalAvatarUpload
import com.ermao.library.shared.modules.personalsettings.domain.PersonalPasswordChange
import com.ermao.library.shared.modules.personalsettings.domain.PersonalPreferences
import com.ermao.library.shared.modules.personalsettings.domain.PersonalServerAbout
import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsContext
import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsLocale
import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsResult
import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsSnapshot

interface PersonalSettingsRepository {
    suspend fun loadSettings(context: PersonalSettingsContext): PersonalSettingsResult<PersonalSettingsSnapshot>

    suspend fun updateName(
        context: PersonalSettingsContext,
        name: String,
    ): PersonalSettingsResult<PersonalAccount>

    suspend fun updateEmail(
        context: PersonalSettingsContext,
        email: String,
        currentPassword: String,
    ): PersonalSettingsResult<PersonalAccount>

    suspend fun updatePassword(
        context: PersonalSettingsContext,
        currentPassword: String,
        newPassword: String,
    ): PersonalSettingsResult<PersonalPasswordChange>

    suspend fun loadAvatar(
        context: PersonalSettingsContext,
        etag: String? = null,
    ): PersonalSettingsResult<PersonalAvatar>

    suspend fun uploadAvatar(
        context: PersonalSettingsContext,
        upload: PersonalAvatarUpload,
    ): PersonalSettingsResult<PersonalAccount>

    suspend fun deleteAvatar(context: PersonalSettingsContext): PersonalSettingsResult<PersonalAccount>

    suspend fun updateLocale(
        context: PersonalSettingsContext,
        locale: PersonalSettingsLocale,
    ): PersonalSettingsResult<PersonalPreferences>

    suspend fun updateAudioPlaybackRate(
        context: PersonalSettingsContext,
        playbackRate: Double,
    ): PersonalSettingsResult<PersonalPreferences>

    suspend fun loadServerAbout(context: PersonalSettingsContext): PersonalSettingsResult<PersonalServerAbout>
}
