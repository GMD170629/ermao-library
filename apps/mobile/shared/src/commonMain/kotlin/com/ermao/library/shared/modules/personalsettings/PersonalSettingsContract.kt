package com.ermao.library.shared.modules.personalsettings

/** Root capability aliases for Kotlin platform consumers; infrastructure remains private. */
typealias PersonalSettingsRepository =
    com.ermao.library.shared.modules.personalsettings.application.PersonalSettingsRepository
typealias PersonalSettingsContext =
    com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsContext
typealias PersonalSettingsTlsMode =
    com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsTlsMode
typealias PersonalSettingsLocale =
    com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsLocale
typealias PersonalAccount =
    com.ermao.library.shared.modules.personalsettings.domain.PersonalAccount
typealias PersonalPreferences =
    com.ermao.library.shared.modules.personalsettings.domain.PersonalPreferences
typealias PersonalSettingsSnapshot =
    com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsSnapshot
typealias PersonalAvatarMimeType =
    com.ermao.library.shared.modules.personalsettings.domain.PersonalAvatarMimeType
typealias PersonalAvatarUpload =
    com.ermao.library.shared.modules.personalsettings.domain.PersonalAvatarUpload
typealias PersonalAvatar =
    com.ermao.library.shared.modules.personalsettings.domain.PersonalAvatar
typealias PersonalPasswordChange =
    com.ermao.library.shared.modules.personalsettings.domain.PersonalPasswordChange
typealias PersonalServerAbout =
    com.ermao.library.shared.modules.personalsettings.domain.PersonalServerAbout
typealias PersonalSettingsErrorKind =
    com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsErrorKind
typealias PersonalSettingsFieldViolation =
    com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsFieldViolation
typealias PersonalSettingsError =
    com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsError
typealias PersonalSettingsResult<T> =
    com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsResult<T>
typealias PersonalSettingsContent<T> =
    com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsResult.Content<T>
typealias PersonalSettingsFailure =
    com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsResult.Failure
