package com.ermao.library.shared.modules.settingscenter

typealias SettingsAccessRequirement =
    com.ermao.library.shared.modules.settingscenter.domain.SettingsAccessRequirement
typealias SettingsCatalogEntry =
    com.ermao.library.shared.modules.settingscenter.domain.SettingsCatalogEntry
typealias SettingsCatalogGroup =
    com.ermao.library.shared.modules.settingscenter.domain.SettingsCatalogGroup
typealias SettingsCenterCatalog =
    com.ermao.library.shared.modules.settingscenter.domain.SettingsCenterCatalog
typealias SettingsGroupId = com.ermao.library.shared.modules.settingscenter.domain.SettingsGroupId
typealias SettingsItemId = com.ermao.library.shared.modules.settingscenter.domain.SettingsItemId

fun visibleSettingsCatalog(
    isAdmin: Boolean,
    canManageSystem: Boolean,
): List<SettingsCatalogEntry> =
    com.ermao.library.shared.modules.settingscenter.domain.visibleSettingsCatalog(
        isAdmin = isAdmin,
        canManageSystem = canManageSystem,
    )

fun visibleSettingsItems(
    isAdmin: Boolean,
    canManageSystem: Boolean,
): List<SettingsItemId> =
    com.ermao.library.shared.modules.settingscenter.domain.visibleSettingsItems(
        isAdmin = isAdmin,
        canManageSystem = canManageSystem,
    )
