package com.ermao.library.features.me.model

import com.ermao.library.shared.modules.personalsettings.PersonalSettingsLocale
import kotlinx.serialization.Serializable

@Serializable
sealed interface MeRoute : androidx.navigation3.runtime.NavKey {
    @Serializable
    data object Root : MeRoute

    @Serializable
    data object Profile : MeRoute

    @Serializable
    data object Security : MeRoute

    @Serializable
    data object Language : MeRoute

    @Serializable
    data object About : MeRoute
}

data class MeAccountViewState(
    val id: String,
    val displayName: String,
    val email: String,
    val avatarUrl: String?,
)

enum class MeOperation {
    Load,
    SaveName,
    SaveEmail,
    SavePassword,
    UploadAvatar,
    DeleteAvatar,
    SaveLocale,
    LoadAbout,
}

enum class MeField {
    DisplayName,
    Email,
    CurrentPassword,
    NewPassword,
    ConfirmPassword,
    Avatar,
}

data class MeFailure(
    val operation: MeOperation,
    val code: String,
    val fieldCodes: Map<MeField, String> = emptyMap(),
)

data class MeRootViewState(
    val isLoading: Boolean = true,
    val account: MeAccountViewState? = null,
    val avatarBytes: ByteArray? = null,
    val locale: PersonalSettingsLocale = PersonalSettingsLocale.EnUs,
    val serverName: String,
    val serverBaseUrl: String,
    val failure: MeFailure? = null,
) {
    override fun equals(other: Any?): Boolean =
        this === other || other is MeRootViewState && isLoading == other.isLoading && account == other.account &&
            avatarBytes.contentEqualsNullable(other.avatarBytes) && locale == other.locale && serverName == other.serverName &&
            serverBaseUrl == other.serverBaseUrl && failure == other.failure

    override fun hashCode(): Int {
        var result = isLoading.hashCode()
        result = 31 * result + (account?.hashCode() ?: 0)
        result = 31 * result + (avatarBytes?.contentHashCode() ?: 0)
        result = 31 * result + locale.hashCode()
        result = 31 * result + serverName.hashCode()
        result = 31 * result + serverBaseUrl.hashCode()
        result = 31 * result + (failure?.hashCode() ?: 0)
        return result
    }
}

data class ProfileEditorState(
    val displayName: String = "",
    val pendingAvatar: SanitizedAvatar? = null,
    val avatarRevision: Long = 0L,
    val isSaving: Boolean = false,
    val failure: MeFailure? = null,
)

data class SecurityEditorState(
    val email: String = "",
    val emailCurrentPassword: String = "",
    val currentPassword: String = "",
    val newPassword: String = "",
    val confirmPassword: String = "",
    val isSaving: Boolean = false,
    val failure: MeFailure? = null,
)

data class AboutViewState(
    val isLoading: Boolean = false,
    val appVersion: String,
    val serverVersion: String? = null,
    val failure: MeFailure? = null,
)

data class SanitizedAvatar(
    val bytes: ByteArray,
    val mimeType: SanitizedAvatarMimeType,
) {
    override fun equals(other: Any?): Boolean =
        this === other || other is SanitizedAvatar && bytes.contentEquals(other.bytes) && mimeType == other.mimeType

    override fun hashCode(): Int = 31 * bytes.contentHashCode() + mimeType.hashCode()
}

enum class SanitizedAvatarMimeType {
    Jpeg,
    Png,
    Webp,
}

private fun ByteArray?.contentEqualsNullable(other: ByteArray?): Boolean =
    when {
        this == null -> other == null
        other == null -> false
        else -> contentEquals(other)
    }
