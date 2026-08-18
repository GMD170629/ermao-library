package com.ermao.library.shared.modules.personalsettings.infrastructure

import com.ermao.library.shared.modules.personalsettings.domain.PersonalAccount
import com.ermao.library.shared.modules.personalsettings.domain.PersonalPreferences
import com.ermao.library.shared.modules.personalsettings.domain.PersonalServerAbout
import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsLocale
import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsSnapshot
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
internal data class UpdateNameWire(
    val name: String,
)

@Serializable
internal data class UpdateEmailWire(
    val email: String,
    val currentPassword: String,
)

@Serializable
internal data class UpdatePasswordWire(
    val currentPassword: String,
    val newPassword: String,
)

@Serializable
internal data class UpdateLocaleWire(
    val preferences: LocalePreferenceWire,
)

@Serializable
internal data class LocalePreferenceWire(
    val locale: String,
)

@Serializable
internal data class SettingsSessionWire(
    val user: SettingsUserWire,
    val authorization: SettingsAuthorizationWire,
    val preferences: SettingsPreferencesWire,
)

@Serializable
internal data class SettingsUserPayloadWire(
    val user: SettingsUserWire,
)

@Serializable
internal data class SettingsPreferencesPayloadWire(
    val preferences: SettingsPreferencesWire,
)

@Serializable
internal data class SettingsPasswordChangedWire(
    val passwordChanged: Boolean,
    val requiresLogin: Boolean,
)

@Serializable
internal data class SettingsUserWire(
    val id: String,
    val email: String,
    val name: String,
    val role: String,
    val status: String,
    val canManageSystem: Boolean,
    val canViewManualImports: Boolean,
    val authzVersion: Long,
    val avatarUrl: String? = null,
    val locale: String? = null,
)

@Serializable
internal data class SettingsAuthorizationWire(
    val isAdmin: Boolean,
    val canManageSystem: Boolean,
    val allLibraryScopes: Boolean,
    val libraryIds: List<String>,
    val canViewManualImports: Boolean,
    val authzVersion: Long,
)

@Serializable
internal data class SettingsPreferencesWire(
    val locale: String,
    @SerialName("library.view") val libraryView: String? = null,
    @SerialName("library.sort") val librarySort: String? = null,
    @SerialName("library.sortDirection") val librarySortDirection: String? = null,
    @SerialName("audio.playbackRate") val audioPlaybackRate: Double? = null,
    @SerialName("kindle.email") val kindleEmail: String? = null,
)

@Serializable
internal data class PersonalCompatibilityWire(
    val service: String,
    val serverIdentity: String,
    val serverVersion: String,
    val protocol: PersonalProtocolWire,
    val readerSchemaVersion: Int,
    val capabilities: PersonalCapabilitiesWire,
)

@Serializable
internal data class PersonalProtocolWire(
    val version: Int,
    val minimumSupportedClientVersion: Int,
)

@Serializable
internal data class PersonalCapabilitiesWire(
    val setup: Boolean,
    val cookieSession: Boolean,
    val readerV4: Boolean,
    val mediaRange: Boolean,
    val managedOfflineDownloads: Boolean,
)

internal fun SettingsUserWire.toDomain(): PersonalAccount =
    PersonalAccount(
        id = id,
        email = email,
        displayName = name,
        avatarUrl = avatarUrl,
    )

internal fun SettingsSessionWire.toDomain(): PersonalSettingsSnapshot? {
    val locale = PersonalSettingsLocale.fromWireValue(preferences.locale) ?: return null
    return PersonalSettingsSnapshot(
        account = user.toDomain(),
        preferences = PersonalPreferences(locale),
    )
}

internal fun SettingsPreferencesWire.toDomain(): PersonalPreferences? =
    PersonalSettingsLocale.fromWireValue(locale)?.let(::PersonalPreferences)

internal fun PersonalCompatibilityWire.toDomain(): PersonalServerAbout =
    PersonalServerAbout(
        serverIdentity = serverIdentity,
        serverVersion = serverVersion,
    )
