package com.ermao.library.shared.modules.settingscenter.domain

/** Stable groups used to render the settings center on every mobile platform. */
enum class SettingsGroupId(val wireValue: String) {
    ACCOUNT("account"),
    READING_AND_STORAGE("readingAndStorage"),
    CONNECTED_SERVICES("connectedServices"),
    SYSTEM_MANAGEMENT("systemManagement"),
    PREFERENCES("preferences"),
    PRODUCT("product"),
}

/** Stable identifiers for settings-center destinations. Platforms map these IDs to native UI. */
enum class SettingsItemId(val wireValue: String) {
    PROFILE("profile"),
    SECURITY("security"),
    DOWNLOADS("downloads"),
    EMAIL_KINDLE("emailKindle"),
    KINDLE_QUEUE("kindleQueue"),
    USERS("users"),
    OPDS("opds"),
    LOGS("logs"),
    LANGUAGE("language"),
    ABOUT("about"),
}

/** Authorization boundary for a settings-center item. */
enum class SettingsAccessRequirement {
    AUTHENTICATED,
    ADMIN,
    SYSTEM_MANAGER,
}

data class SettingsCatalogEntry(
    val itemId: SettingsItemId,
    val groupId: SettingsGroupId,
    val accessRequirement: SettingsAccessRequirement,
)

data class SettingsCatalogGroup(
    val id: SettingsGroupId,
    val itemIds: List<SettingsItemId>,
)

/**
 * The single source of truth for settings-center group and item ordering.
 *
 * This catalog intentionally contains no presentation concerns such as labels, icons, or routes.
 * Native platforms map the stable IDs to their own resources and navigation destinations.
 */
object SettingsCenterCatalog {
    val groups: List<SettingsCatalogGroup> = listOf(
        SettingsCatalogGroup(
            id = SettingsGroupId.ACCOUNT,
            itemIds = listOf(SettingsItemId.PROFILE, SettingsItemId.SECURITY),
        ),
        SettingsCatalogGroup(
            id = SettingsGroupId.READING_AND_STORAGE,
            itemIds = listOf(SettingsItemId.DOWNLOADS),
        ),
        SettingsCatalogGroup(
            id = SettingsGroupId.CONNECTED_SERVICES,
            itemIds = listOf(SettingsItemId.EMAIL_KINDLE, SettingsItemId.KINDLE_QUEUE),
        ),
        SettingsCatalogGroup(
            id = SettingsGroupId.SYSTEM_MANAGEMENT,
            itemIds = listOf(
                SettingsItemId.USERS,
                SettingsItemId.OPDS,
                SettingsItemId.LOGS,
            ),
        ),
        SettingsCatalogGroup(
            id = SettingsGroupId.PREFERENCES,
            itemIds = listOf(SettingsItemId.LANGUAGE),
        ),
        SettingsCatalogGroup(
            id = SettingsGroupId.PRODUCT,
            itemIds = listOf(SettingsItemId.ABOUT),
        ),
    )

    val entries: List<SettingsCatalogEntry> = groups.flatMap { group ->
        group.itemIds.map { itemId ->
            SettingsCatalogEntry(
                itemId = itemId,
                groupId = group.id,
                accessRequirement = accessRequirementFor(itemId),
            )
        }
    }

    private fun accessRequirementFor(itemId: SettingsItemId): SettingsAccessRequirement = when (itemId) {
        SettingsItemId.USERS -> SettingsAccessRequirement.ADMIN
        SettingsItemId.OPDS,
        SettingsItemId.LOGS,
        -> SettingsAccessRequirement.SYSTEM_MANAGER
        else -> SettingsAccessRequirement.AUTHENTICATED
    }
}

/** Returns the catalog entries available to the current actor, preserving canonical order. */
fun visibleSettingsCatalog(
    isAdmin: Boolean,
    canManageSystem: Boolean,
): List<SettingsCatalogEntry> = SettingsCenterCatalog.entries.filter { entry ->
    when (entry.accessRequirement) {
        SettingsAccessRequirement.AUTHENTICATED -> true
        SettingsAccessRequirement.ADMIN -> isAdmin
        SettingsAccessRequirement.SYSTEM_MANAGER -> canManageSystem
    }
}

/** Returns only stable item IDs for platforms that maintain their own presentation model. */
fun visibleSettingsItems(
    isAdmin: Boolean,
    canManageSystem: Boolean,
): List<SettingsItemId> = visibleSettingsCatalog(isAdmin, canManageSystem).map(SettingsCatalogEntry::itemId)
