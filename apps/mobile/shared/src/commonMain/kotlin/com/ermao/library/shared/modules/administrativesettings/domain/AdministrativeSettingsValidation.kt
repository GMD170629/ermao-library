package com.ermao.library.shared.modules.administrativesettings.domain

internal object AdministrativeSettingsValidation {
    const val MAXIMUM_DISPLAY_NAME_LENGTH = 40
    const val MAXIMUM_EMAIL_LENGTH = 320
    const val MINIMUM_PASSWORD_LENGTH = 10
    const val MAXIMUM_PASSWORD_LENGTH = 128
    const val MINIMUM_SMTP_PORT = 1
    const val MAXIMUM_SMTP_PORT = 65_535
    const val MINIMUM_ATTACHMENT_MEGABYTES = 1.0
    const val MAXIMUM_ATTACHMENT_MEGABYTES = 50.0
    const val MINIMUM_LOG_RETENTION_DAYS = 1
    const val MAXIMUM_LOG_RETENTION_DAYS = 365

    fun isValidDisplayName(value: String): Boolean =
        value.trim().length in 1..MAXIMUM_DISPLAY_NAME_LENGTH

    fun isValidEmail(value: String): Boolean {
        val normalized = value.trim()
        val at = normalized.indexOf('@')
        return normalized.length <= MAXIMUM_EMAIL_LENGTH &&
            at > 0 &&
            at < normalized.lastIndex &&
            normalized.substring(at + 1).contains('.')
    }

    fun isValidOptionalEmail(value: String): Boolean =
        value.trim().isEmpty() || isValidEmail(value)

    fun isValidPassword(value: String): Boolean =
        value.length in MINIMUM_PASSWORD_LENGTH..MAXIMUM_PASSWORD_LENGTH

    fun isValidSmtpHost(value: String): Boolean = value.isNotBlank()

    fun isValidSmtpPort(value: Int): Boolean =
        value in MINIMUM_SMTP_PORT..MAXIMUM_SMTP_PORT

    fun isValidAttachmentMegabytes(value: Double): Boolean =
        value.isFinite() && value in MINIMUM_ATTACHMENT_MEGABYTES..MAXIMUM_ATTACHMENT_MEGABYTES

    fun isValidLogRetentionDays(value: Int): Boolean =
        value in MINIMUM_LOG_RETENTION_DAYS..MAXIMUM_LOG_RETENTION_DAYS

}
