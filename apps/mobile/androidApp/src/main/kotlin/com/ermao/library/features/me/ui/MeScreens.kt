package com.ermao.library.features.me.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.result.PickVisualMediaRequest
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.AccountCircle
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Language
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material.icons.outlined.Email
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LargeTopAppBar
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.PasswordVisualTransformation
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
import com.ermao.library.ui.theme.WarmPageThemeValues
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MeRootScreen(
    state: MeRootViewState,
    onOpenProfile: () -> Unit,
    onOpenSecurity: () -> Unit,
    onOpenLanguage: () -> Unit,
    onOpenAbout: () -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
    canOpenAdministration: Boolean = false,
    onOpenEmailAndKindle: () -> Unit = {},
    onOpenKindleQueue: () -> Unit = {},
    onOpenAdministration: () -> Unit = {},
) {
    val theme = WarmPageThemeValues
    Scaffold(
        modifier = modifier,
        containerColor = theme.colors.canvas,
        topBar = {
            LargeTopAppBar(
                title = { Text(stringResource(R.string.me_title), style = theme.typography.display) },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = theme.colors.canvas),
            )
        },
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()),
        ) {
            state.account?.let { AccountIdentity(it, state.avatarBytes) }
            state.failure?.let { InlineFailure(onRetry) }
            SettingsSection(R.string.me_section_account)
            SettingsRow(R.string.me_profile_title, R.string.me_profile_summary, Icons.Outlined.AccountCircle, onOpenProfile)
            SettingsDivider()
            SettingsRow(R.string.me_security_title, R.string.me_security_summary, Icons.Outlined.Lock, onOpenSecurity)
            SettingsSection(R.string.me_section_connected_services)
            SettingsRow(
                R.string.me_email_kindle_title,
                R.string.me_email_kindle_summary,
                Icons.Outlined.Email,
                onOpenEmailAndKindle,
            )
            SettingsDivider()
            SettingsRow(
                R.string.me_kindle_queue_title,
                R.string.me_kindle_queue_summary,
                Icons.AutoMirrored.Outlined.Send,
                onOpenKindleQueue,
            )
            if (canOpenAdministration) {
                SettingsSection(R.string.me_section_administration)
                SettingsRow(
                    R.string.me_administration_title,
                    R.string.me_administration_summary,
                    Icons.Outlined.Settings,
                    onOpenAdministration,
                )
            }
            SettingsSection(R.string.me_section_server)
            ReadOnlyServerRow(state.serverName, state.serverBaseUrl)
            SettingsSection(R.string.me_section_preferences)
            SettingsRow(
                R.string.me_language_title,
                if (state.locale == PersonalSettingsLocale.ZhCn) R.string.me_language_zh_cn else R.string.me_language_en_us,
                Icons.Outlined.Language,
                onOpenLanguage,
            )
            SettingsSection(R.string.me_section_product)
            SettingsRow(R.string.me_about_title, null, Icons.Outlined.Info, onOpenAbout)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
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
    SettingsPageScaffold(R.string.me_profile_title, onBack, modifier) {
        Column(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Avatar(account.displayName, state.pendingAvatar?.bytes ?: avatarBytes)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = {
                        picker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                    },
                    modifier = Modifier.heightIn(min = 48.dp),
                ) { Text(stringResource(R.string.me_avatar_choose)) }
                if (account.avatarUrl != null) {
                    TextButton(onClick = { confirmDelete = true }, modifier = Modifier.heightIn(min = 48.dp)) {
                        Icon(Icons.Outlined.Delete, contentDescription = null)
                        Text(stringResource(R.string.me_avatar_delete))
                    }
                }
            }
            if (state.pendingAvatar != null) {
                Text(stringResource(R.string.me_avatar_ready), color = WarmPageThemeValues.colors.textSecondary)
                Button(onClick = onUploadAvatar, enabled = !state.isSaving, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) {
                    Text(stringResource(R.string.me_avatar_upload))
                }
            }
            avatarError?.let { Text(avatarFailureText(it), color = androidx.compose.material3.MaterialTheme.colorScheme.error) }
            HorizontalDivider(color = WarmPageThemeValues.colors.divider)
            OutlinedTextField(
                value = state.displayName,
                onValueChange = onDisplayNameChanged,
                label = { Text(stringResource(R.string.me_display_name_label)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            state.failure?.let { InlineFailure() }
            Button(
                onClick = onSaveName,
                enabled = !state.isSaving && state.displayName.isNotBlank(),
                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
            ) { Text(stringResource(if (state.isSaving) R.string.me_saving else R.string.me_save)) }
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
    var confirmEmail by rememberSaveable { mutableStateOf(false) }
    var confirmPassword by rememberSaveable { mutableStateOf(false) }
    var confirmLogout by rememberSaveable { mutableStateOf(false) }
    SettingsPageScaffold(R.string.me_security_title, onBack, modifier) {
        Column(
            Modifier.fillMaxWidth().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            SectionHeading(R.string.me_email_section)
            OutlinedTextField(
                value = state.email,
                onValueChange = onEmailChanged,
                label = { Text(stringResource(R.string.me_email_label)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            PasswordField(state.emailCurrentPassword, onEmailCurrentPasswordChanged, R.string.me_current_password_label)
            Button(
                onClick = { confirmEmail = true },
                enabled = !state.isSaving && state.email.isNotBlank() && state.emailCurrentPassword.isNotBlank(),
                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
            ) { Text(stringResource(R.string.me_email_change)) }
            HorizontalDivider()
            SectionHeading(R.string.me_password_section)
            PasswordField(state.currentPassword, onCurrentPasswordChanged, R.string.me_current_password_label)
            PasswordField(state.newPassword, onNewPasswordChanged, R.string.me_new_password_label)
            PasswordField(state.confirmPassword, onPasswordConfirmationChanged, R.string.me_confirm_password_label)
            Button(
                onClick = { confirmPassword = true },
                enabled = !state.isSaving && state.currentPassword.isNotBlank() && state.newPassword.isNotBlank() &&
                    state.confirmPassword.isNotBlank(),
                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
            ) { Text(stringResource(R.string.me_password_change)) }
            state.failure?.let { InlineFailure() }
            HorizontalDivider()
            TextButton(onClick = { confirmLogout = true }, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) {
                Text(stringResource(R.string.logout_action), color = androidx.compose.material3.MaterialTheme.colorScheme.error)
            }
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
            TextButton(onClick = { confirmLogout = false; onLogout() }) {
                Text(stringResource(R.string.logout_confirm_action), color = androidx.compose.material3.MaterialTheme.colorScheme.error)
            }
        },
        dismissButton = { TextButton(onClick = { confirmLogout = false }) { Text(stringResource(R.string.cancel)) } },
    )
}

@Composable
fun LanguageScreen(
    selected: PersonalSettingsLocale,
    onBack: () -> Unit,
    onSelect: (PersonalSettingsLocale) -> Unit,
    modifier: Modifier = Modifier,
) {
    SettingsPageScaffold(R.string.me_language_title, onBack, modifier) {
        LanguageRow(R.string.me_language_zh_cn, PersonalSettingsLocale.ZhCn, selected, onSelect)
        SettingsDivider()
        LanguageRow(R.string.me_language_en_us, PersonalSettingsLocale.EnUs, selected, onSelect)
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
    SettingsPageScaffold(R.string.me_about_title, onBack, modifier) {
        SettingsSection(R.string.me_about_versions)
        ReadOnlyValueRow(R.string.me_app_version, state.appVersion)
        SettingsDivider()
        ReadOnlyValueRow(
            R.string.me_server_version,
            state.serverVersion ?: stringResource(if (state.isLoading) R.string.me_loading else R.string.me_not_available),
        )
        state.failure?.let { InlineFailure(onRetry) }
    }
}

@Composable
private fun AccountIdentity(account: MeAccountViewState, avatarBytes: ByteArray?) {
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Avatar(account.displayName, avatarBytes)
        Column(Modifier.weight(1f)) {
            Text(account.displayName, style = WarmPageThemeValues.typography.headline)
            Text(account.email, color = WarmPageThemeValues.colors.textSecondary)
        }
    }
}

@Composable
private fun Avatar(name: String, bytes: ByteArray?) {
    val image = remember(bytes) {
        bytes?.let { decodeBoundedAvatarPreview(it) }?.asImageBitmap()
    }
    androidx.compose.material3.Surface(
        modifier = Modifier.size(64.dp).clip(CircleShape),
        color = WarmPageThemeValues.colors.accentSoft,
        shape = CircleShape,
    ) {
        if (image != null) {
            androidx.compose.foundation.Image(
                bitmap = image,
                contentDescription = stringResource(R.string.me_avatar_content_description),
                contentScale = androidx.compose.ui.layout.ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
            )
        } else {
            Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                Text(name.trim().take(1).ifEmpty { "?" }, style = WarmPageThemeValues.typography.title)
            }
        }
    }
}

@Composable
private fun SettingsSection(title: Int) {
    Text(
        stringResource(title),
        style = WarmPageThemeValues.typography.label,
        color = WarmPageThemeValues.colors.textSecondary,
        modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 24.dp, bottom = 8.dp).semantics { heading() },
    )
}

@Composable
private fun SectionHeading(title: Int) {
    Text(stringResource(title), style = WarmPageThemeValues.typography.sectionTitle, modifier = Modifier.semantics { heading() })
}

@Composable
private fun SettingsRow(
    title: Int,
    summaryResource: Int?,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    onClick: () -> Unit,
    summary: String? = null,
    trailingIcon: androidx.compose.ui.graphics.vector.ImageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
) {
    val supportingText = summary ?: summaryResource?.let { stringResource(it) }
    ListItem(
        headlineContent = { Text(stringResource(title)) },
        supportingContent = supportingText?.let { value -> ({ Text(value) }) },
        leadingContent = { Icon(icon, contentDescription = null) },
        trailingContent = { Icon(trailingIcon, contentDescription = null) },
        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
        modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp).clickable(role = Role.Button, onClick = onClick),
    )
}

@Composable
private fun ReadOnlyServerRow(name: String, address: String) {
    ListItem(
        headlineContent = { Text(name) },
        supportingContent = { Text(address) },
        leadingContent = { Icon(Icons.Outlined.Storage, contentDescription = null) },
        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
        modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp),
    )
}

@Composable
private fun ReadOnlyValueRow(label: Int, value: String) {
    ListItem(
        headlineContent = { Text(stringResource(label)) },
        trailingContent = { Text(value, color = WarmPageThemeValues.colors.textSecondary) },
        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
    )
}

@Composable
private fun SettingsDivider() {
    HorizontalDivider(Modifier.padding(start = 56.dp), color = WarmPageThemeValues.colors.divider)
}

@Composable
private fun LanguageRow(
    label: Int,
    locale: PersonalSettingsLocale,
    selected: PersonalSettingsLocale,
    onSelect: (PersonalSettingsLocale) -> Unit,
) {
    ListItem(
        headlineContent = { Text(stringResource(label)) },
        trailingContent = { RadioButton(selected = selected == locale, onClick = null) },
        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
        modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp).clickable(role = Role.RadioButton) { onSelect(locale) },
    )
}

@Composable
private fun PasswordField(value: String, onValueChanged: (String) -> Unit, label: Int) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChanged,
        label = { Text(stringResource(label)) },
        visualTransformation = PasswordVisualTransformation(),
        singleLine = true,
        modifier = Modifier.fillMaxWidth(),
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SettingsPageScaffold(
    title: Int,
    onBack: () -> Unit,
    modifier: Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    Scaffold(
        modifier = modifier,
        containerColor = WarmPageThemeValues.colors.canvas,
        topBar = {
            TopAppBar(
                title = { Text(stringResource(title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.navigate_back))
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = WarmPageThemeValues.colors.canvas),
            )
        },
    ) { padding ->
        Column(Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()), content = content)
    }
}

@Composable
private fun InlineFailure(onRetry: (() -> Unit)? = null) {
    Row(
        Modifier.fillMaxWidth().padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(stringResource(R.string.me_operation_failed), color = androidx.compose.material3.MaterialTheme.colorScheme.error)
        onRetry?.let { TextButton(onClick = it) { Text(stringResource(R.string.retry_action)) } }
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
        confirmButton = { TextButton(onClick = onConfirm) { Text(stringResource(action)) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
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
