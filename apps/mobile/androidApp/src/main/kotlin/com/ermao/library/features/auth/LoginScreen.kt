package com.ermao.library.features.auth

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.SwapHoriz
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.autofill.ContentType
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.contentType
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import com.ermao.library.R
import com.ermao.library.bootstrap.LoginFormState
import com.ermao.library.features.servers.BrandImage
import com.ermao.library.features.servers.BrandImageShape
import com.ermao.library.features.servers.PrimaryActionButton
import com.ermao.library.shared.modules.servers.domain.ServerProfileSnapshot
import com.ermao.library.ui.theme.WarmPageThemeValues

enum class LoginEntryAlert { ServerUnavailable, IncompatibleServer, UnsafeSsl }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LoginScreen(
    profiles: List<ServerProfileSnapshot>,
    currentProfileId: String?,
    savedAccountEmails: Map<String, String>,
    form: LoginFormState,
    isAuthenticating: Boolean,
    alert: LoginEntryAlert?,
    unexpectedFailure: Boolean,
    onServerAddressChanged: (String) -> Unit,
    onEmailChanged: (String) -> Unit,
    onPasswordChanged: (String) -> Unit,
    onLogin: () -> Unit,
    onSelectServer: (String) -> Unit,
    onDeleteCurrentServer: () -> Unit,
    onDismissAlert: () -> Unit,
    onRetry: () -> Unit,
    onAcceptUnsafeSsl: () -> Unit,
    modifier: Modifier = Modifier,
    offlineDaysRemaining: Int? = null,
    onEnterOffline: () -> Unit = {},
    canClose: Boolean = false,
    onClose: () -> Unit = {},
) {
    val theme = WarmPageThemeValues
    var passwordVisible by remember { mutableStateOf(false) }
    var showServerSheet by remember { mutableStateOf(false) }
    var showDeleteConfirmation by remember { mutableStateOf(false) }
    val otherProfiles = profiles.filterNot { it.id == currentProfileId }

    Scaffold(
        modifier = modifier,
        containerColor = theme.colors.canvas,
        topBar = {
            if (canClose) {
                TopAppBar(
                    title = { Text(stringResource(R.string.server_center_title)) },
                    navigationIcon = {
                        IconButton(onClick = onClose, modifier = Modifier.testTag("login-entry-close")) {
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = stringResource(R.string.navigate_back),
                            )
                        }
                    },
                )
            }
        },
    ) { contentPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = theme.spacing.three, vertical = theme.spacing.four),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            BrandImage(size = 96, shape = BrandImageShape.Circle)
            Spacer(Modifier.height(theme.spacing.three))
            Text(
                text = stringResource(R.string.login_entry_title),
                modifier = Modifier.semantics { heading() },
                color = theme.colors.textPrimary,
                style = theme.typography.display,
            )
            Spacer(Modifier.height(theme.spacing.one))
            Text(
                text = stringResource(R.string.login_entry_description),
                color = theme.colors.textSecondary,
                style = theme.typography.body,
            )
            Spacer(Modifier.height(theme.spacing.four))
            OutlinedTextField(
                value = form.serverAddress,
                onValueChange = onServerAddressChanged,
                modifier = Modifier
                    .fillMaxWidth()
                    .testTag("login-server-address"),
                enabled = !isAuthenticating,
                isError = form.serverAddressError,
                label = { Text(stringResource(R.string.server_url_label)) },
                placeholder = { Text(stringResource(R.string.server_url_placeholder)) },
                supportingText = if (form.serverAddressError) {
                    { Text(stringResource(R.string.server_invalid_url)) }
                } else {
                    { Text(stringResource(R.string.server_url_supporting_text)) }
                },
                leadingIcon = { Icon(Icons.Outlined.Dns, contentDescription = null) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Next),
                singleLine = true,
                shape = RoundedCornerShape(theme.radii.control),
            )
            Spacer(Modifier.height(theme.spacing.one))
            OutlinedTextField(
                value = form.email,
                onValueChange = onEmailChanged,
                modifier = Modifier.fillMaxWidth().semantics { contentType = ContentType.EmailAddress },
                enabled = !isAuthenticating,
                isError = form.emailRequired,
                label = { Text(stringResource(R.string.login_email_label)) },
                supportingText = when {
                    form.emailRequired -> ({ Text(stringResource(R.string.login_required_email)) })
                    else -> null
                },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
                singleLine = true,
                shape = RoundedCornerShape(theme.radii.control),
            )
            Spacer(Modifier.height(theme.spacing.one))
            OutlinedTextField(
                value = form.password,
                onValueChange = onPasswordChanged,
                modifier = Modifier.fillMaxWidth().semantics { contentType = ContentType.Password },
                enabled = !isAuthenticating,
                isError = form.passwordRequired || form.invalidCredentials,
                label = { Text(stringResource(R.string.login_password_label)) },
                supportingText = when {
                    form.passwordRequired -> ({ Text(stringResource(R.string.login_required_password)) })
                    form.invalidCredentials -> ({ Text(stringResource(R.string.login_invalid_credentials)) })
                    else -> null
                },
                visualTransformation = if (passwordVisible) VisualTransformation.None else PasswordVisualTransformation(),
                trailingIcon = {
                    val label = stringResource(if (passwordVisible) R.string.login_hide_password else R.string.login_show_password)
                    IconButton(onClick = { passwordVisible = !passwordVisible }) {
                        Icon(
                            if (passwordVisible) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                            contentDescription = label,
                        )
                    }
                },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { onLogin() }),
                singleLine = true,
                shape = RoundedCornerShape(theme.radii.control),
            )
            if (unexpectedFailure) {
                Spacer(Modifier.height(theme.spacing.one))
                Text(
                    stringResource(R.string.unexpected_failure),
                    modifier = Modifier.fillMaxWidth(),
                    color = MaterialTheme.colorScheme.error,
                    style = theme.typography.callout,
                )
            }
            Spacer(Modifier.height(theme.spacing.three))
            PrimaryActionButton(
                label = stringResource(if (isAuthenticating) R.string.login_in_progress else R.string.login_action),
                onClick = onLogin,
                enabled = !isAuthenticating,
                loading = isAuthenticating,
                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp).testTag("login-submit"),
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(
                    onClick = { showServerSheet = true },
                    enabled = !isAuthenticating && otherProfiles.isNotEmpty(),
                    modifier = Modifier.heightIn(min = 48.dp).testTag("login-switch-server"),
                ) {
                    Icon(Icons.Outlined.SwapHoriz, contentDescription = null)
                    Text(stringResource(R.string.login_switch_server))
                }
                TextButton(
                    onClick = { showDeleteConfirmation = true },
                    enabled = !isAuthenticating && currentProfileId != null,
                    modifier = Modifier.heightIn(min = 48.dp).testTag("login-delete-server"),
                ) {
                    Text(stringResource(R.string.login_delete_current_server))
                }
            }
            if (offlineDaysRemaining != null && offlineDaysRemaining > 0) {
                OutlinedButton(
                    onClick = onEnterOffline,
                    enabled = !isAuthenticating,
                    modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                ) {
                    Text(
                        pluralStringResource(
                            R.plurals.offline_enter_action,
                            offlineDaysRemaining,
                            offlineDaysRemaining,
                        ),
                    )
                }
                Text(
                    text = stringResource(R.string.offline_scope_message),
                    color = theme.colors.textSecondary,
                    style = theme.typography.caption,
                )
            }
            Spacer(Modifier.height(theme.spacing.two))
            Text(
                text = stringResource(R.string.login_secure_storage_note),
                color = theme.colors.textTertiary,
                style = theme.typography.caption,
            )
        }
    }

    if (showServerSheet) {
        ModalBottomSheet(onDismissRequest = { showServerSheet = false }) {
            Text(
                text = stringResource(R.string.login_switch_sheet_title),
                modifier = Modifier.padding(horizontal = theme.spacing.three).semantics { heading() },
                color = theme.colors.textPrimary,
                style = theme.typography.title,
            )
            Spacer(Modifier.height(theme.spacing.two))
            otherProfiles.forEach { profile ->
                val account = savedAccountEmails[profile.id] ?: profile.baseUrl
                val label = stringResource(R.string.login_server_option_description, profile.displayName, account)
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 64.dp)
                        .clickable {
                            showServerSheet = false
                            onSelectServer(profile.id)
                        }
                        .semantics { contentDescription = label }
                        .padding(horizontal = theme.spacing.three, vertical = theme.spacing.one),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(profile.displayName, color = theme.colors.textPrimary, style = theme.typography.headline)
                        Text(account, color = theme.colors.textSecondary, style = theme.typography.callout)
                    }
                }
                HorizontalDivider(color = theme.colors.divider)
            }
            Spacer(Modifier.height(theme.spacing.three))
        }
    }

    if (showDeleteConfirmation) {
        AlertDialog(
            onDismissRequest = { showDeleteConfirmation = false },
            title = { Text(stringResource(R.string.login_delete_confirm_title)) },
            text = { Text(stringResource(R.string.login_delete_confirm_message)) },
            confirmButton = {
                TextButton(onClick = {
                    showDeleteConfirmation = false
                    onDeleteCurrentServer()
                }) { Text(stringResource(R.string.login_delete_confirm_action), color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { showDeleteConfirmation = false }) { Text(stringResource(R.string.cancel)) } },
        )
    }

    alert?.let { currentAlert ->
        AlertDialog(
            onDismissRequest = onDismissAlert,
            title = {
                Text(stringResource(when (currentAlert) {
                    LoginEntryAlert.ServerUnavailable -> R.string.server_connection_failed_title
                    LoginEntryAlert.IncompatibleServer -> R.string.server_incompatible_title
                    LoginEntryAlert.UnsafeSsl -> R.string.tls_risk_title
                }))
            },
            text = {
                Text(stringResource(when (currentAlert) {
                    LoginEntryAlert.ServerUnavailable -> R.string.server_connection_failed_message
                    LoginEntryAlert.IncompatibleServer -> R.string.server_incompatible_message
                    LoginEntryAlert.UnsafeSsl -> R.string.tls_risk_message
                }))
            },
            confirmButton = {
                when (currentAlert) {
                    LoginEntryAlert.ServerUnavailable -> TextButton(onClick = onRetry) { Text(stringResource(R.string.server_retry_action)) }
                    LoginEntryAlert.IncompatibleServer -> TextButton(onClick = onDismissAlert) { Text(stringResource(R.string.cancel)) }
                    LoginEntryAlert.UnsafeSsl -> TextButton(onClick = onAcceptUnsafeSsl) {
                        Text(stringResource(R.string.tls_accept_risk_action), color = MaterialTheme.colorScheme.error)
                    }
                }
            },
            dismissButton = if (currentAlert != LoginEntryAlert.IncompatibleServer) {
                { TextButton(onClick = onDismissAlert) { Text(stringResource(R.string.cancel)) } }
            } else null,
        )
    }
}
