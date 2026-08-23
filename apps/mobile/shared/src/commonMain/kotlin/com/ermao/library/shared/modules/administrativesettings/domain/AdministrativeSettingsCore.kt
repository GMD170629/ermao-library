package com.ermao.library.shared.modules.administrativesettings.domain

@ConsistentCopyVisibility
data class AdministrativeSettingsContext internal constructor(
    val profileId: String,
    val profileDisplayName: String,
    val baseUrl: String,
    val serverIdentity: String,
    val tlsMode: AdministrativeSettingsTlsMode,
)

enum class AdministrativeSettingsTlsMode {
    SystemTrust,
    InsecureSkipAllValidation,
}

enum class AdministrativeSettingsErrorKind {
    Validation,
    Unauthorized,
    Forbidden,
    NotFound,
    Conflict,
    Unavailable,
    RateLimited,
    Server,
    Transport,
    Protocol,
    Stale,
}

data class AdministrativeSettingsFieldViolation(
    val field: String,
    val code: String,
)

data class AdministrativeSettingsError(
    val kind: AdministrativeSettingsErrorKind,
    val code: String,
    val fieldViolations: List<AdministrativeSettingsFieldViolation> = emptyList(),
)

sealed interface AdministrativeSettingsResult<out T> {
    data class Content<T>(
        val value: T,
    ) : AdministrativeSettingsResult<T>

    data class Failure(
        val error: AdministrativeSettingsError,
    ) : AdministrativeSettingsResult<Nothing>
}

data class PageRequest(
    val page: Int = 1,
    val pageSize: Int = 20,
)

data class PageInfo(
    val page: Int,
    val pageSize: Int,
    val total: Int,
    val totalPages: Int,
)

sealed interface SettingValue {
    data class Text(val value: String) : SettingValue

    data class Integer(val value: Long) : SettingValue

    data class Decimal(val value: Double) : SettingValue

    data class Toggle(val value: Boolean) : SettingValue

    data class TextList(val value: List<String>) : SettingValue

    data object Empty : SettingValue
}

enum class ManagedLocale(val wireValue: String) {
    ZhCn("zh-CN"),
    EnUs("en-US"),
}

enum class MediaKind(val wireValue: String) {
    Ebook("EBOOK"),
    Comic("COMIC"),
    Audiobook("AUDIOBOOK"),
}

enum class MediaKindPolicy(val wireValue: String) {
    Mixed("MIXED"),
    Ebook("EBOOK"),
    Comic("COMIC"),
    Audiobook("AUDIOBOOK"),
}
