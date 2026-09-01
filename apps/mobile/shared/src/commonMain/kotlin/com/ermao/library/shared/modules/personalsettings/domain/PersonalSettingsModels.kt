package com.ermao.library.shared.modules.personalsettings.domain

@ConsistentCopyVisibility
data class PersonalSettingsContext internal constructor(
    val profileId: String,
    val profileDisplayName: String,
    val baseUrl: String,
    val serverIdentity: String,
    val tlsMode: PersonalSettingsTlsMode,
)

enum class PersonalSettingsTlsMode {
    SystemTrust,
    InsecureSkipAllValidation,
}

enum class PersonalSettingsLocale(
    val wireValue: String,
) {
    ZhCn("zh-CN"),
    EnUs("en-US"),
    ;

    companion object {
        fun fromWireValue(value: String): PersonalSettingsLocale? =
            entries.firstOrNull { locale -> locale.wireValue == value }
    }
}

data class PersonalAccount(
    val id: String,
    val email: String,
    val displayName: String,
    val avatarUrl: String?,
)

data class PersonalPreferences(
    val locale: PersonalSettingsLocale,
    val audioPlaybackRate: Double? = null,
) {
    init {
        require(audioPlaybackRate == null || audioPlaybackRate.isFinite() && audioPlaybackRate in 0.5..3.0)
    }
}

data class PersonalSettingsSnapshot(
    val account: PersonalAccount,
    val preferences: PersonalPreferences,
)

enum class PersonalAvatarMimeType(
    val wireValue: String,
    val fileExtension: String,
) {
    Jpeg("image/jpeg", "jpg"),
    Png("image/png", "png"),
    Webp("image/webp", "webp"),
}

data class PersonalAvatarUpload(
    val bytes: ByteArray,
    val mimeType: PersonalAvatarMimeType,
) {
    override fun equals(other: Any?): Boolean =
        this === other ||
            (
                other is PersonalAvatarUpload &&
                    bytes.contentEquals(other.bytes) &&
                    mimeType == other.mimeType
            )

    override fun hashCode(): Int = 31 * bytes.contentHashCode() + mimeType.hashCode()
}

data class PersonalAvatar(
    val bytes: ByteArray,
    val contentType: String?,
    val etag: String?,
    val notModified: Boolean,
) {
    override fun equals(other: Any?): Boolean =
        this === other ||
            (
                other is PersonalAvatar &&
                    bytes.contentEquals(other.bytes) &&
                    contentType == other.contentType &&
                    etag == other.etag &&
                    notModified == other.notModified
            )

    override fun hashCode(): Int {
        var result = bytes.contentHashCode()
        result = 31 * result + contentType.hashCode()
        result = 31 * result + (etag?.hashCode() ?: 0)
        result = 31 * result + notModified.hashCode()
        return result
    }
}

data class PersonalPasswordChange(
    val requiresLogin: Boolean,
)

data class PersonalServerAbout(
    val serverIdentity: String,
    val serverVersion: String,
)

enum class PersonalSettingsErrorKind {
    Validation,
    Unauthorized,
    Forbidden,
    NotFound,
    Conflict,
    RateLimited,
    Server,
    Transport,
    Protocol,
}

data class PersonalSettingsFieldViolation(
    val field: String,
    val code: String,
)

data class PersonalSettingsError(
    val kind: PersonalSettingsErrorKind,
    val code: String,
    val fieldViolations: List<PersonalSettingsFieldViolation> = emptyList(),
)

sealed interface PersonalSettingsResult<out T> {
    data class Content<T>(
        val value: T,
    ) : PersonalSettingsResult<T>

    data class Failure(
        val error: PersonalSettingsError,
    ) : PersonalSettingsResult<Nothing>
}
