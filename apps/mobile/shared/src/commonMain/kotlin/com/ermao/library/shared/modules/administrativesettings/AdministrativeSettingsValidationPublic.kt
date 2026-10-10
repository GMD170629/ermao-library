package com.ermao.library.shared.modules.administrativesettings

import com.ermao.library.shared.modules.administrativesettings.domain.AdministrativeSettingsValidation

fun isValidAdministrativeDisplayName(value: String): Boolean =
    AdministrativeSettingsValidation.isValidDisplayName(value)

fun isValidAdministrativeEmail(value: String): Boolean =
    AdministrativeSettingsValidation.isValidEmail(value)

fun isValidOptionalAdministrativeEmail(value: String): Boolean =
    AdministrativeSettingsValidation.isValidOptionalEmail(value)

fun isValidAdministrativePassword(value: String): Boolean =
    AdministrativeSettingsValidation.isValidPassword(value)

fun isValidAdministrativeSmtpHost(value: String): Boolean =
    AdministrativeSettingsValidation.isValidSmtpHost(value)

fun isValidAdministrativeSmtpPort(value: Int): Boolean =
    AdministrativeSettingsValidation.isValidSmtpPort(value)

fun isValidAdministrativeAttachmentMegabytes(value: Double): Boolean =
    AdministrativeSettingsValidation.isValidAttachmentMegabytes(value)

fun isValidAdministrativeLogRetentionDays(value: Int): Boolean =
    AdministrativeSettingsValidation.isValidLogRetentionDays(value)

fun administrativeMinimumPasswordLength(): Int =
    AdministrativeSettingsValidation.MINIMUM_PASSWORD_LENGTH

fun administrativeMaximumPasswordLength(): Int =
    AdministrativeSettingsValidation.MAXIMUM_PASSWORD_LENGTH

fun administrativeMinimumLogRetentionDays(): Int =
    AdministrativeSettingsValidation.MINIMUM_LOG_RETENTION_DAYS

fun administrativeMaximumLogRetentionDays(): Int =
    AdministrativeSettingsValidation.MAXIMUM_LOG_RETENTION_DAYS

fun isValidManagedUserDeletionConfirmation(email: String, confirmation: String): Boolean =
    confirmation.length <= 191 && confirmation.trim().equals(email, ignoreCase = true)
