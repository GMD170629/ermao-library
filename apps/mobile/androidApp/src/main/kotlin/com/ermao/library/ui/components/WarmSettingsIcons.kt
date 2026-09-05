package com.ermao.library.ui.components

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ListAlt
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.AccountCircle
import androidx.compose.material.icons.outlined.AdminPanelSettings
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.Email
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Language
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.ManageAccounts
import androidx.compose.ui.graphics.vector.ImageVector

/**
 * The single semantic icon registry for Android settings navigation.
 *
 * Feature screens choose a meaning from this registry instead of mixing filled and outlined
 * icon families or reusing a storage glyph for unrelated destinations.
 */
object WarmSettingsIcons {
    val Account: ImageVector = Icons.Outlined.AccountCircle
    val Security: ImageVector = Icons.Outlined.Lock
    val Downloads: ImageVector = Icons.Outlined.Download
    val EmailAndKindle: ImageVector = Icons.Outlined.Email
    val KindleQueue: ImageVector = Icons.AutoMirrored.Outlined.Send
    val Administration: ImageVector = Icons.Outlined.AdminPanelSettings
    val Server: ImageVector = Icons.Outlined.Dns
    val Language: ImageVector = Icons.Outlined.Language
    val About: ImageVector = Icons.Outlined.Info
    val Users: ImageVector = Icons.Outlined.ManageAccounts
    val Opds: ImageVector = Icons.Outlined.Dns
    val Logs: ImageVector = Icons.AutoMirrored.Outlined.ListAlt
}
