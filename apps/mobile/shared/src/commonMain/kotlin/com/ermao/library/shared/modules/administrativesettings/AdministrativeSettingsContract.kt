package com.ermao.library.shared.modules.administrativesettings

import com.ermao.library.shared.modules.administrativesettings.domain.AdministrativeSettingsContext
import com.ermao.library.shared.modules.administrativesettings.domain.AdministrativeSettingsTlsMode
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult

fun createAdministrativeSettingsContext(
    profileId: String,
    displayName: String,
    baseUrl: String,
    serverIdentity: String,
    acceptsInsecureTls: Boolean,
): AdministrativeSettingsContext {
    val parsed = ServerBaseUrl.parse(baseUrl)
    require(parsed is ServerBaseUrlParseResult.Valid) { "Invalid server base URL" }
    return AdministrativeSettingsContext(
        profileId = profileId,
        profileDisplayName = displayName,
        baseUrl = parsed.baseUrl.value,
        serverIdentity = serverIdentity,
        tlsMode = if (acceptsInsecureTls) {
            AdministrativeSettingsTlsMode.InsecureSkipAllValidation
        } else {
            AdministrativeSettingsTlsMode.SystemTrust
        },
    )
}
