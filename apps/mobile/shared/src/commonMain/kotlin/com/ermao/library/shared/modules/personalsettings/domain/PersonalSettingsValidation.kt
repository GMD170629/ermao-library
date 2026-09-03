package com.ermao.library.shared.modules.personalsettings.domain

/** Canonical input rules shared by personal-settings transports and platform UI. */
internal object PersonalSettingsValidation {
    const val MAX_NAME_LENGTH = 40
    const val MIN_PASSWORD_LENGTH = 10
    const val MAX_PASSWORD_LENGTH = 128

    fun isValidDisplayName(value: String): Boolean = value.trim().length in 1..MAX_NAME_LENGTH

    fun isValidEmail(value: String): Boolean {
        val normalized = value.trim()
        val atIndex = normalized.indexOf('@')
        return atIndex > 0 &&
            atIndex == normalized.lastIndexOf('@') &&
            atIndex < normalized.lastIndex &&
            normalized.none(Char::isWhitespace)
    }

    fun isValidCurrentPassword(value: String): Boolean = value.length in 1..MAX_PASSWORD_LENGTH

    fun isValidNewPassword(value: String): Boolean = value.length in MIN_PASSWORD_LENGTH..MAX_PASSWORD_LENGTH
}
