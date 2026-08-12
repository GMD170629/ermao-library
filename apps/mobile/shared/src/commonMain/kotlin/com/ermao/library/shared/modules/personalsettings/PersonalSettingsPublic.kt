@file:Suppress("LongParameterList")

package com.ermao.library.shared.modules.personalsettings

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
