@file:Suppress("LongParameterList")

package com.ermao.library.shared.modules.personalsettings

import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsValidation
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult

fun createPersonalSettingsContext(
    profileId: String,
    displayName: String,
    baseUrl: String,
    serverIdentity: String,
    acceptsInsecureTls: Boolean,
): PersonalSettingsContext {
    val parsed = ServerBaseUrl.parse(baseUrl)
    require(parsed is ServerBaseUrlParseResult.Valid) { "Invalid server base URL" }
    return PersonalSettingsContext(
        profileId = profileId,
        profileDisplayName = displayName,
        baseUrl = parsed.baseUrl.value,
        serverIdentity = serverIdentity,
        tlsMode =
            if (acceptsInsecureTls) {
                PersonalSettingsTlsMode.InsecureSkipAllValidation
            } else {
                PersonalSettingsTlsMode.SystemTrust
            },
    )
}

fun isValidPersonalSettingsDisplayName(value: String): Boolean =
    PersonalSettingsValidation.isValidDisplayName(value)

fun isValidPersonalSettingsEmail(value: String): Boolean =
    PersonalSettingsValidation.isValidEmail(value)

fun isValidPersonalSettingsCurrentPassword(value: String): Boolean =
    PersonalSettingsValidation.isValidCurrentPassword(value)

fun isValidPersonalSettingsNewPassword(value: String): Boolean =
    PersonalSettingsValidation.isValidNewPassword(value)

fun personalSettingsMinimumPasswordLength(): Int = PersonalSettingsValidation.MIN_PASSWORD_LENGTH

fun personalSettingsMaximumPasswordLength(): Int = PersonalSettingsValidation.MAX_PASSWORD_LENGTH
