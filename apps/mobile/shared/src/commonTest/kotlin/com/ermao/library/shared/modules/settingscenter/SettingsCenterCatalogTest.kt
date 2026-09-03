package com.ermao.library.shared.modules.settingscenter

import kotlin.test.Test
import kotlin.test.assertEquals

class SettingsCenterCatalogTest {
    @Test
    fun catalogUsesTheProductGroupOrderAndContainsEveryRootItem() {
        assertEquals(
            listOf(
                SettingsGroupId.ACCOUNT,
                SettingsGroupId.READING_AND_STORAGE,
                SettingsGroupId.CONNECTED_SERVICES,
                SettingsGroupId.SYSTEM_MANAGEMENT,
                SettingsGroupId.PREFERENCES,
                SettingsGroupId.PRODUCT,
            ),
            SettingsCenterCatalog.groups.map(SettingsCatalogGroup::id),
        )
        assertEquals(
            listOf(
                SettingsItemId.PROFILE,
                SettingsItemId.SECURITY,
                SettingsItemId.DOWNLOADS,
                SettingsItemId.EMAIL_KINDLE,
                SettingsItemId.KINDLE_QUEUE,
                SettingsItemId.USERS,
                SettingsItemId.OPDS,
                SettingsItemId.LOGS,
                SettingsItemId.LANGUAGE,
                SettingsItemId.ABOUT,
            ),
            SettingsCenterCatalog.entries.map(SettingsCatalogEntry::itemId),
        )
    }

    @Test
    fun regularMemberSeesOnlyPersonalAndProductItems() {
        assertEquals(
            listOf(
                SettingsItemId.PROFILE,
                SettingsItemId.SECURITY,
                SettingsItemId.DOWNLOADS,
                SettingsItemId.EMAIL_KINDLE,
                SettingsItemId.KINDLE_QUEUE,
                SettingsItemId.LANGUAGE,
                SettingsItemId.ABOUT,
            ),
            visibleSettingsItems(isAdmin = false, canManageSystem = false),
        )
    }

    @Test
    fun adminSeesUserManagementButNotSystemManagementWithoutCapability() {
        assertEquals(
            listOf(
                SettingsItemId.PROFILE,
                SettingsItemId.SECURITY,
                SettingsItemId.DOWNLOADS,
                SettingsItemId.EMAIL_KINDLE,
                SettingsItemId.KINDLE_QUEUE,
                SettingsItemId.USERS,
                SettingsItemId.LANGUAGE,
                SettingsItemId.ABOUT,
            ),
            visibleSettingsItems(isAdmin = true, canManageSystem = false),
        )
    }

    @Test
    fun systemManagerSeesSystemManagementButNotUserManagementWithoutAdminRole() {
        assertEquals(
            listOf(
                SettingsItemId.PROFILE,
                SettingsItemId.SECURITY,
                SettingsItemId.DOWNLOADS,
                SettingsItemId.EMAIL_KINDLE,
                SettingsItemId.KINDLE_QUEUE,
                SettingsItemId.OPDS,
                SettingsItemId.LOGS,
                SettingsItemId.LANGUAGE,
                SettingsItemId.ABOUT,
            ),
            visibleSettingsItems(isAdmin = false, canManageSystem = true),
        )
    }

    @Test
    fun administratorWithSystemCapabilitySeesTheCompleteCatalog() {
        assertEquals(SettingsCenterCatalog.entries, visibleSettingsCatalog(isAdmin = true, canManageSystem = true))
    }

    @Test
    fun managementRequirementsAreLimitedToTheirIntendedItems() {
        assertEquals(
            SettingsAccessRequirement.ADMIN,
            SettingsCenterCatalog.entries.first { it.itemId == SettingsItemId.USERS }.accessRequirement,
        )
        assertEquals(
            listOf(
                SettingsItemId.OPDS,
                SettingsItemId.LOGS,
            ),
            SettingsCenterCatalog.entries
                .filter { it.accessRequirement == SettingsAccessRequirement.SYSTEM_MANAGER }
                .map(SettingsCatalogEntry::itemId),
        )
    }
}
