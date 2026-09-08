package com.ermao.library.features.me.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.Logout
import androidx.compose.material.icons.outlined.Check
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.PhotoCamera
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.features.me.model.AboutViewState
import com.ermao.library.features.me.model.MeAccountViewState
import com.ermao.library.features.me.model.MeRootViewState
import com.ermao.library.features.me.model.ProfileEditorState
import com.ermao.library.features.me.model.SecurityEditorState
import com.ermao.library.features.me.platform.AndroidAvatarSanitizer
import com.ermao.library.features.me.platform.AvatarSanitizationFailure
import com.ermao.library.features.me.platform.AvatarSanitizationResult
import com.ermao.library.features.me.platform.decodeBoundedAvatarPreview
import com.ermao.library.shared.modules.personalsettings.PersonalSettingsLocale
import com.ermao.library.shared.modules.settingscenter.SettingsCenterCatalog
import com.ermao.library.shared.modules.settingscenter.SettingsGroupId
import com.ermao.library.shared.modules.settingscenter.SettingsItemId
import com.ermao.library.shared.modules.settingscenter.visibleSettingsItems
import com.ermao.library.ui.components.SettingsSaveAction
import com.ermao.library.ui.components.SettingsTabRow
import com.ermao.library.ui.components.SettingsTextField
import com.ermao.library.ui.components.WarmPageChoice
import com.ermao.library.ui.components.WarmPageIconAction
import com.ermao.library.ui.components.WarmPageSegmentedControl
import com.ermao.library.ui.components.WarmSettingsContentState
import com.ermao.library.ui.components.WarmSettingsContentStateKind
import com.ermao.library.ui.components.WarmSettingsDangerAction
import com.ermao.library.ui.components.WarmSettingsDivider
import com.ermao.library.ui.components.WarmSettingsIcons
import com.ermao.library.ui.components.WarmSettingsIdentityHeader
import com.ermao.library.ui.components.WarmSettingsInlineMessage
import com.ermao.library.ui.components.WarmSettingsNavigationRow
import com.ermao.library.ui.components.WarmSettingsScaffold
import com.ermao.library.ui.components.WarmSettingsScaffoldRole
import com.ermao.library.ui.components.WarmSettingsSection
import com.ermao.library.ui.components.WarmSettingsValueRow
import com.ermao.library.ui.theme.WarmPageThemeValues
import kotlinx.coroutines.launch

@Composable
fun MeRootScreen(
    state: MeRootViewState,
    onOpenProfile: () -> Unit,
    onOpenSecurity: () -> Unit,
    onOpenLanguage: () -> Unit,
    onOpenAbout: () -> Unit,
    onOpenDownloads: () -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
    downloadStatus: String? = null,
    appVersion: String? = null,
    emailAndKindleConfigured: Boolean = false,
    failedKindleTaskCount: Int = 0,
    isAdmin: Boolean = false,
    canManageSystem: Boolean = false,
    onOpenEmailAndKindle: () -> Unit = {},
    onOpenKindleQueue: () -> Unit = {},
    onOpenUsers: () -> Unit = {},
    onOpenOpds: () -> Unit = {},
    onOpenLogs: () -> Unit = {},
) {
    val theme = WarmPageThemeValues
    val visibleItems = visibleSettingsItems(isAdmin = isAdmin, canManageSystem = canManageSystem).toSet()
    WarmSettingsScaffold(
        role = WarmSettingsScaffoldRole.Root,
        title = stringResource(R.string.me_title),
        modifier = modifier.testTag("me-root"),
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .testTag("settings-page-scroll"),
        ) {
            state.failure?.let { InlineFailure(onRetry) }
            SettingsCenterCatalog.groups.forEach { group ->
                if (group.id == SettingsGroupId.PREFERENCES) {
                    WarmSettingsSection(stringResource(R.string.me_section_server)) {
                        WarmSettingsValueRow(
                            label = state.serverName,
                            supporting = state.serverBaseUrl,
                            value = stringResource(R.string.me_current_server),
                            icon = WarmSettingsIcons.Server,
                            modifier = Modifier.testTag("settings-row-value-server"),
                        )
                    }
                }
                val items = group.itemIds.filter(visibleItems::contains)
                if (items.isNotEmpty()) {
                    WarmSettingsSection(
                        title = meSettingsGroupTitle(group.id),
                        modifier = if (group.id == SettingsGroupId.PRODUCT) {
                            Modifier.padding(bottom = theme.components.page.contentBottomInset)
                        } else {
                            Modifier
                        },
                    ) {
                        items.forEachIndexed { index, item ->
                            MeSettingsNavigationRow(
                                item = item,
                                state = state,
                                downloadStatus = downloadStatus,
                                appVersion = appVersion,
                                emailAndKindleConfigured = emailAndKindleConfigured,
                                failedKindleTaskCount = failedKindleTaskCount,
                                onOpenProfile = onOpenProfile,
                                onOpenSecurity = onOpenSecurity,
                                onOpenDownloads = onOpenDownloads,
                                onOpenEmailAndKindle = onOpenEmailAndKindle,
                                onOpenKindleQueue = onOpenKindleQueue,
                                onOpenUsers = onOpenUsers,
                                onOpenOpds = onOpenOpds,
                                onOpenLogs = onOpenLogs,
                                onOpenLanguage = onOpenLanguage,
                                onOpenAbout = onOpenAbout,
                            )
                            if (index < items.lastIndex) WarmSettingsDivider(afterIcon = true)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun meSettingsGroupTitle(group: SettingsGroupId): String = stringResource(
    when (group) {
        SettingsGroupId.ACCOUNT -> R.string.me_section_account
        SettingsGroupId.READING_AND_STORAGE -> R.string.me_section_offline_storage
        SettingsGroupId.CONNECTED_SERVICES -> R.string.me_section_connected_services
        SettingsGroupId.SYSTEM_MANAGEMENT -> R.string.me_section_administration
        SettingsGroupId.PREFERENCES -> R.string.me_section_preferences
        SettingsGroupId.PRODUCT -> R.string.me_section_product
    },
)

@Composable
private fun MeSettingsNavigationRow(
    item: SettingsItemId,
    state: MeRootViewState,
    downloadStatus: String?,
    appVersion: String?,
    emailAndKindleConfigured: Boolean,
    failedKindleTaskCount: Int,
    onOpenProfile: () -> Unit,
    onOpenSecurity: () -> Unit,
    onOpenDownloads: () -> Unit,
    onOpenEmailAndKindle: () -> Unit,
    onOpenKindleQueue: () -> Unit,
    onOpenUsers: () -> Unit,
    onOpenOpds: () -> Unit,
    onOpenLogs: () -> Unit,
    onOpenLanguage: () -> Unit,
    onOpenAbout: () -> Unit,
) {
    val title: String
    val status: String?
    val icon: androidx.compose.ui.graphics.vector.ImageVector
    val tag: String
    val onClick: () -> Unit
    when (item) {
        SettingsItemId.PROFILE -> {
            title = stringResource(R.string.me_profile_title)
            status = state.account?.displayName
            icon = WarmSettingsIcons.Account
            tag = "settings-row-profile"
            onClick = onOpenProfile
        }
        SettingsItemId.SECURITY -> {
            title = stringResource(R.string.me_security_title)
            status = null
            icon = WarmSettingsIcons.Security
            tag = "settings-row-security"
            onClick = onOpenSecurity
        }
        SettingsItemId.DOWNLOADS -> {
            title = stringResource(R.string.me_downloads_title)
            status = downloadStatus
            icon = WarmSettingsIcons.Downloads
            tag = "settings-row-downloads"
            onClick = onOpenDownloads
        }
        SettingsItemId.EMAIL_KINDLE -> {
            title = stringResource(R.string.me_email_kindle_title)
            status = stringResource(R.string.me_status_configured).takeIf { emailAndKindleConfigured }
            icon = WarmSettingsIcons.EmailAndKindle
            tag = "settings-row-email-kindle"
            onClick = onOpenEmailAndKindle
        }
        SettingsItemId.KINDLE_QUEUE -> {
            title = stringResource(R.string.me_kindle_queue_title)
            status = failedKindleTaskCount.takeIf { it > 0 }?.toString()
            icon = WarmSettingsIcons.KindleQueue
            tag = "settings-row-kindle-queue"
            onClick = onOpenKindleQueue
        }
        SettingsItemId.USERS -> {
            title = stringResource(R.string.me_users_title)
            status = null
            icon = WarmSettingsIcons.Users
            tag = "settings-row-users"
            onClick = onOpenUsers
        }
        SettingsItemId.OPDS -> {
            title = stringResource(R.string.me_opds_title)
            status = null
            icon = WarmSettingsIcons.Opds
            tag = "settings-row-opds"
            onClick = onOpenOpds
        }
        SettingsItemId.LOGS -> {
            title = stringResource(R.string.me_system_logs_title)
            status = null
            icon = WarmSettingsIcons.Logs
            tag = "settings-row-logs"
            onClick = onOpenLogs
        }
        SettingsItemId.LANGUAGE -> {
            title = stringResource(R.string.me_language_title)
            status = stringResource(
                if (state.locale == PersonalSettingsLocale.ZhCn) R.string.me_language_zh_cn else R.string.me_language_en_us,
            )
            icon = WarmSettingsIcons.Language
            tag = "settings-row-language"
            onClick = onOpenLanguage
        }
        SettingsItemId.ABOUT -> {
            title = stringResource(R.string.me_about_title)
            status = appVersion?.takeIf(String::isNotBlank)?.let { "v$it" }
            icon = WarmSettingsIcons.About
            tag = "settings-row-about"
            onClick = onOpenAbout
        }
    }
    WarmSettingsNavigationRow(
        title = title,
        status = status,
        icon = icon,
        modifier = Modifier.testTag(tag),
        onClick = onClick,
    )
}

@Composable
fun ProfileScreen(
    state: ProfileEditorState,
    account: MeAccountViewState,
    avatarBytes: ByteArray?,
    onBack: () -> Unit,
    onDisplayNameChanged: (String) -> Unit,
    onAvatarReady: (com.ermao.library.features.me.model.SanitizedAvatar) -> Unit,
    onSaveName: () -> Unit,
    onUploadAvatar: () -> Unit,
    onDeleteAvatar: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val theme = WarmPageThemeValues
    val sanitizer = remember(context) { AndroidAvatarSanitizer(context.contentResolver) }
    val scope = rememberCoroutineScope()
    var avatarError by remember { mutableStateOf<AvatarSanitizationFailure?>(null) }
    var confirmDelete by rememberSaveable { mutableStateOf(false) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri != null) scope.launch {
            when (val result = sanitizer.sanitize(uri)) {
                is AvatarSanitizationResult.Success -> {
                    avatarError = null
                    onAvatarReady(result.avatar)
                }
                is AvatarSanitizationResult.Failure -> avatarError = result.reason
            }
        }
    }
    WarmSettingsScaffold(
        role = WarmSettingsScaffoldRole.Detail,
        title = stringResource(R.string.me_profile_title),
        onBack = onBack,
        navigationContentDescription = stringResource(R.string.navigate_back),
        modifier = modifier.testTag("me-profile"),
        actions = {
            SettingsSaveAction(
                contentDescription = stringResource(R.string.me_save_display_name),
                label = stringResource(R.string.me_save),
                enabled = !state.isSaving && state.displayName.isNotBlank() &&
                    state.displayName.trim() != state.savedDisplayName.trim(),
                working = state.isSaving,
                onClick = onSaveName,
                modifier = Modifier.testTag("settings-save"),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = theme.components.page.compactGutter)
                .testTag("settings-page-scroll"),
            verticalArrangement = Arrangement.spacedBy(theme.spacing.two),
        ) {
            WarmSettingsIdentityHeader(
                title = account.displayName,
                subtitle = account.email,
                modifier = Modifier.testTag("settings-identity"),
                avatar = { Avatar(avatarBytes) },
                actions = {
                    WarmPageIconAction(
                        icon = Icons.Outlined.PhotoCamera,
                        label = stringResource(R.string.me_avatar_choose),
                        onClick = { picker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) },
                        enabled = !state.isSaving,
                        modifier = Modifier.heightIn(min = theme.components.controls.minimumTouchTarget),
                    )
                    if (account.avatarUrl != null) {
                        WarmPageIconAction(
                            icon = Icons.Outlined.Delete,
                            label = stringResource(R.string.me_avatar_delete),
                            onClick = { confirmDelete = true },
                            enabled = !state.isSaving,
                            modifier = Modifier.heightIn(min = theme.components.controls.minimumTouchTarget),
                        )
                    }
                },
            )
            if (state.pendingAvatar != null) {
                WarmSettingsInlineMessage(stringResource(R.string.me_avatar_ready))
                Button(
                    onClick = onUploadAvatar,
                    enabled = !state.isSaving,
                    modifier = Modifier.fillMaxWidth().heightIn(min = theme.components.controls.minimumTouchTarget),
                ) { Text(stringResource(R.string.me_avatar_upload)) }
            }
            avatarError?.let {
                WarmSettingsInlineMessage(
                    message = avatarFailureText(it),
                    color = androidx.compose.material3.MaterialTheme.colorScheme.error,
                )
            }
            HorizontalDivider(color = theme.colors.divider)
            SettingsTextField(
                value = state.displayName,
                onValueChange = onDisplayNameChanged,
                label = stringResource(R.string.me_display_name_label),
                enabled = !state.isSaving,
                modifier = Modifier.testTag("settings-field-display-name"),
            )
            state.failure?.let { InlineFailure() }
        }
    }
    if (confirmDelete) {
        ConfirmationDialog(
            title = R.string.me_avatar_delete_confirm_title,
            message = R.string.me_avatar_delete_confirm_message,
            action = R.string.me_avatar_delete,
            onConfirm = { confirmDelete = false; onDeleteAvatar() },
            onDismiss = { confirmDelete = false },
        )
    }
}

private enum class SecurityTab { Email, Password }

@Composable
fun SecurityScreen(
    state: SecurityEditorState,
    serverName: String,
    onBack: () -> Unit,
    onEmailChanged: (String) -> Unit,
    onEmailCurrentPasswordChanged: (String) -> Unit,
    onCurrentPasswordChanged: (String) -> Unit,
    onNewPasswordChanged: (String) -> Unit,
    onPasswordConfirmationChanged: (String) -> Unit,
    onSaveEmail: () -> Unit,
    onSavePassword: () -> Unit,
    onLogout: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    var confirmEmail by rememberSaveable { mutableStateOf(false) }
    var confirmPassword by rememberSaveable { mutableStateOf(false) }
    var confirmLogout by rememberSaveable { mutableStateOf(false) }
    var selectedTabName by rememberSaveable { mutableStateOf(SecurityTab.Email.name) }
    val selectedTab = SecurityTab.entries.firstOrNull { it.name == selectedTabName } ?: SecurityTab.Email
    val isEmailTab = selectedTab == SecurityTab.Email
    val canSaveEmail = !state.isSaving && state.email.isNotBlank() && state.emailCurrentPassword.isNotBlank() &&
        state.email.trim() != state.savedEmail.trim()
    val canSavePassword = !state.isSaving && state.currentPassword.isNotBlank() && state.newPassword.isNotBlank() &&
        state.confirmPassword.isNotBlank() && state.newPassword == state.confirmPassword
    val tabLabels = listOf(stringResource(R.string.me_email_section), stringResource(R.string.me_password_section))
    WarmSettingsScaffold(
        role = WarmSettingsScaffoldRole.Detail,
        title = stringResource(R.string.me_security_title),
        onBack = onBack,
        navigationContentDescription = stringResource(R.string.navigate_back),
        modifier = modifier.testTag("me-security"),
        actions = {
            SettingsSaveAction(
                contentDescription = stringResource(if (isEmailTab) R.string.me_email_change else R.string.me_password_change),
                label = stringResource(R.string.me_save),
                enabled = if (isEmailTab) canSaveEmail else canSavePassword,
                working = state.isSaving,
                onClick = { if (isEmailTab) confirmEmail = true else confirmPassword = true },
                modifier = Modifier.testTag("settings-save"),
            )
        },
        tabs = {
            SettingsTabRow(
                selectedIndex = if (isEmailTab) 0 else 1,
                tabs = tabLabels,
                enabled = !state.isSaving,
                onSelect = { selectedTabName = SecurityTab.entries[it].name },
                modifier = Modifier.testTag("settings-tabs"),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(theme.components.page.compactGutter)
                .testTag("settings-page-scroll"),
            verticalArrangement = Arrangement.spacedBy(theme.spacing.two),
        ) {
            if (isEmailTab) {
                SettingsTextField(
                    value = state.email,
                    onValueChange = onEmailChanged,
                    label = stringResource(R.string.me_email_label),
                    enabled = !state.isSaving,
                    modifier = Modifier.testTag("settings-field-email"),
                )
                PasswordField(state.emailCurrentPassword, onEmailCurrentPasswordChanged, R.string.me_current_password_label, "settings-field-email-current-password", !state.isSaving)
            } else {
                PasswordField(state.currentPassword, onCurrentPasswordChanged, R.string.me_current_password_label, "settings-field-current-password", !state.isSaving)
                PasswordField(state.newPassword, onNewPasswordChanged, R.string.me_new_password_label, "settings-field-new-password", !state.isSaving)
                PasswordField(state.confirmPassword, onPasswordConfirmationChanged, R.string.me_confirm_password_label, "settings-field-confirm-password", !state.isSaving)
            }
            state.failure?.let { InlineFailure() }
            WarmSettingsDangerAction(
                label = stringResource(R.string.logout_action),
                onClick = { confirmLogout = true },
                enabled = !state.isSaving,
                modifier = Modifier.padding(top = theme.spacing.two).testTag("settings-danger-logout"),
            )
        }
    }
    if (confirmEmail) ConfirmationDialog(
        R.string.me_email_confirm_title,
        R.string.me_email_confirm_message,
        R.string.me_email_change,
        { confirmEmail = false; onSaveEmail() },
        { confirmEmail = false },
    )
    if (confirmPassword) ConfirmationDialog(
        R.string.me_password_confirm_title,
        R.string.me_password_confirm_message,
        R.string.me_password_change,
        { confirmPassword = false; onSavePassword() },
        { confirmPassword = false },
    )
    if (confirmLogout) AlertDialog(
        onDismissRequest = { confirmLogout = false },
        title = { Text(stringResource(R.string.logout_confirm_title)) },
        text = { Text(stringResource(R.string.logout_confirm_message, serverName)) },
        confirmButton = {
            OutlinedButton(onClick = { confirmLogout = false; onLogout() }) {
                Icon(Icons.AutoMirrored.Outlined.Logout, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
                Spacer(Modifier.size(ButtonDefaults.IconSpacing))
                Text(stringResource(R.string.logout_confirm_action), color = androidx.compose.material3.MaterialTheme.colorScheme.error)
            }
        },
        dismissButton = { OutlinedButton(onClick = { confirmLogout = false }) {
            Icon(Icons.Outlined.Close, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
            Spacer(Modifier.size(ButtonDefaults.IconSpacing))
            Text(stringResource(R.string.cancel)) } },
    )
}

@Composable
fun LanguageScreen(
    selected: PersonalSettingsLocale,
    onBack: () -> Unit,
    onSelect: (PersonalSettingsLocale) -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    WarmSettingsScaffold(
        role = WarmSettingsScaffoldRole.Detail,
        title = stringResource(R.string.me_language_title),
        onBack = onBack,
        navigationContentDescription = stringResource(R.string.navigate_back),
        modifier = modifier.testTag("me-language"),
    ) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(theme.components.page.compactGutter).testTag("settings-page-scroll"),
        ) {
            WarmSettingsSection(stringResource(R.string.me_language_title)) {
                WarmPageSegmentedControl(
                    options = listOf(
                        WarmPageChoice(PersonalSettingsLocale.ZhCn, stringResource(R.string.me_language_zh_cn)),
                        WarmPageChoice(PersonalSettingsLocale.EnUs, stringResource(R.string.me_language_en_us)),
                    ),
                    selected = selected,
                    onSelect = onSelect,
                    modifier = Modifier.testTag("settings-language-segmented"),
                )
            }
        }
    }
}

@Composable
fun AboutScreen(
    state: AboutViewState,
    onBack: () -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    LaunchedEffect(Unit) { onRetry() }
    WarmSettingsScaffold(
        role = WarmSettingsScaffoldRole.Detail,
        title = stringResource(R.string.me_about_title),
        onBack = onBack,
        navigationContentDescription = stringResource(R.string.navigate_back),
        modifier = modifier.testTag("me-about"),
    ) { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).testTag("settings-page-scroll"),
        ) {
            WarmSettingsSection(stringResource(R.string.me_about_versions)) {
                WarmSettingsValueRow(
                    label = stringResource(R.string.me_app_version),
                    value = state.appVersion,
                    modifier = Modifier.testTag("settings-row-value-app-version"),
                )
                WarmSettingsDivider()
                WarmSettingsValueRow(
                    label = stringResource(R.string.me_server_version),
                    value = state.serverVersion ?: stringResource(if (state.isLoading) R.string.me_loading else R.string.me_not_available),
                    modifier = Modifier.testTag("settings-row-value-server-version"),
                )
            }
            state.failure?.let {
                WarmSettingsContentState(
                    kind = WarmSettingsContentStateKind.Error,
                    title = stringResource(R.string.me_operation_failed),
                    actionLabel = stringResource(R.string.retry_action),
                    onAction = onRetry,
                )
            }
        }
    }
}

@Composable
private fun Avatar(bytes: ByteArray?) {
    val image = remember(bytes) { bytes?.let { decodeBoundedAvatarPreview(it) }?.asImageBitmap() }
    if (image != null) {
        Image(
            bitmap = image,
            contentDescription = stringResource(R.string.me_avatar_content_description),
            contentScale = ContentScale.Crop,
            modifier = Modifier.size(52.dp).clip(CircleShape),
        )
    }
}

@Composable
private fun PasswordField(
    value: String,
    onValueChanged: (String) -> Unit,
    label: Int,
    tag: String,
    enabled: Boolean,
) {
    SettingsTextField(
        value = value,
        onValueChange = onValueChanged,
        label = stringResource(label),
        password = true,
        enabled = enabled,
        showPasswordContentDescription = stringResource(R.string.login_show_password),
        hidePasswordContentDescription = stringResource(R.string.login_hide_password),
        modifier = Modifier.testTag(tag),
    )
}

@Composable
private fun InlineFailure(onRetry: (() -> Unit)? = null) {
    Row(
        Modifier.fillMaxWidth().padding(WarmPageThemeValues.spacing.two).testTag("settings-error"),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(stringResource(R.string.me_operation_failed), color = androidx.compose.material3.MaterialTheme.colorScheme.error)
        onRetry?.let { OutlinedButton(onClick = it) {
            Icon(Icons.Outlined.Refresh, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
            Spacer(Modifier.size(ButtonDefaults.IconSpacing))
            Text(stringResource(R.string.retry_action)) } }
    }
}

@Composable
private fun ConfirmationDialog(
    title: Int,
    message: Int,
    action: Int,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(title)) },
        text = { Text(stringResource(message)) },
        confirmButton = { OutlinedButton(onClick = onConfirm) {
            Icon(Icons.Outlined.Check, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
            Spacer(Modifier.size(ButtonDefaults.IconSpacing))
            Text(stringResource(action)) } },
        dismissButton = { OutlinedButton(onClick = onDismiss) {
            Icon(Icons.Outlined.Close, contentDescription = null, modifier = Modifier.size(ButtonDefaults.IconSize))
            Spacer(Modifier.size(ButtonDefaults.IconSpacing))
            Text(stringResource(R.string.cancel)) } },
    )
}

@Composable
private fun avatarFailureText(failure: AvatarSanitizationFailure): String = stringResource(
    when (failure) {
        AvatarSanitizationFailure.UnsupportedType -> R.string.me_avatar_unsupported
        AvatarSanitizationFailure.Unreadable -> R.string.me_avatar_unreadable
        AvatarSanitizationFailure.TooLarge -> R.string.me_avatar_too_large
    },
)
