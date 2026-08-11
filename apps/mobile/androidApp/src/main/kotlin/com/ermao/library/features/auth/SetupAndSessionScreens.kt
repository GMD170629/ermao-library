package com.ermao.library.features.auth

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material.icons.outlined.CloudOff
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.semantics.contentType
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import com.ermao.library.R
import com.ermao.library.bootstrap.LoginFormState
import com.ermao.library.bootstrap.SetupFieldError
import com.ermao.library.bootstrap.SetupFormState
import com.ermao.library.features.servers.PrimaryActionButton
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.ui.theme.WarmPageThemeValues
import kotlin.math.ceil

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SetupScreen(
    profile: ServerProfile,
    form: SetupFormState,
    isSubmitting: Boolean,
    operationErrorCode: String?,
    onNameChanged: (String) -> Unit,
    onEmailChanged: (String) -> Unit,
    onPasswordChanged: (String) -> Unit,
    onConfirmationChanged: (String) -> Unit,
    onSubmit: () -> Unit,
    onSwitchServer: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    var passwordVisible by remember { mutableStateOf(false) }
    Scaffold(
        modifier = modifier,
        containerColor = theme.colors.canvas,
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.setup_title)) },
                navigationIcon = {
                    IconButton(onClick = onSwitchServer, enabled = !isSubmitting) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.navigate_back))
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = theme.spacing.three, vertical = theme.spacing.three),
            verticalArrangement = Arrangement.spacedBy(theme.spacing.two),
        ) {
            Text(stringResource(R.string.setup_heading), style = theme.typography.display)
            Text(stringResource(R.string.setup_description), color = theme.colors.textSecondary)
            ServerIdentity(profile.displayName, profile.baseUrl.value)
            SetupTextField(
                value = form.name,
                onValueChange = onNameChanged,
                label = stringResource(R.string.setup_name_label),
                error = form.nameError?.setupErrorText(),
                enabled = !isSubmitting,
                contentType = ContentType.PersonFullName,
            )
            SetupTextField(
                value = form.email,
                onValueChange = onEmailChanged,
                label = stringResource(R.string.login_email_label),
                error = form.emailError?.setupErrorText(),
                enabled = !isSubmitting,
                contentType = ContentType.EmailAddress,
                keyboardType = KeyboardType.Email,
            )
            PasswordField(
                value = form.password,
                onValueChange = onPasswordChanged,
                label = stringResource(R.string.setup_password_label),
                error = form.passwordError?.setupErrorText(),
                enabled = !isSubmitting,
                visible = passwordVisible,
                onToggleVisibility = { passwordVisible = !passwordVisible },
            )
            PasswordField(
                value = form.passwordConfirmation,
                onValueChange = onConfirmationChanged,
                label = stringResource(R.string.setup_password_confirmation_label),
                error = form.confirmationError?.setupErrorText(),
                enabled = !isSubmitting,
                visible = passwordVisible,
                onToggleVisibility = { passwordVisible = !passwordVisible },
                onDone = onSubmit,
            )
            if (operationErrorCode != null) {
                Text(
                    stringResource(R.string.setup_failed_message),
                    color = MaterialTheme.colorScheme.error,
                    style = theme.typography.callout,
                )
            }
            PrimaryActionButton(
                label = stringResource(if (isSubmitting) R.string.setup_in_progress else R.string.setup_action),
                onClick = onSubmit,
                enabled = !isSubmitting,
                loading = isSubmitting,
                modifier = Modifier.fillMaxWidth().testTag("setup-submit"),
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReauthenticateScreen(
    profile: ServerProfile,
    userDisplayName: String?,
    userEmail: String?,
    entitlementExpiresAtEpochMillis: Long?,
    form: LoginFormState,
    isAuthenticating: Boolean,
    serverUnavailable: Boolean,
    onPasswordChanged: (String) -> Unit,
    onLogin: () -> Unit,
    onEnterOffline: () -> Unit,
    onSwitchServer: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    val remainingDays = entitlementExpiresAtEpochMillis?.let {
        ceil((it - System.currentTimeMillis()).coerceAtLeast(0).toDouble() / MILLIS_PER_DAY).toInt()
    }
    var passwordVisible by remember { mutableStateOf(false) }
    Scaffold(
        modifier = modifier,
        containerColor = theme.colors.canvas,
        topBar = { TopAppBar(title = { Text(stringResource(R.string.reauthenticate_title)) }) },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(theme.spacing.three),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(theme.spacing.two),
        ) {
            Icon(Icons.Outlined.Dns, null, tint = theme.colors.brandAccent)
            Text(stringResource(R.string.reauthenticate_heading), style = theme.typography.title)
            ServerIdentity(profile.displayName, profile.baseUrl.value)
            Text(
                userDisplayName?.let { "$it · ${userEmail.orEmpty()}" } ?: userEmail.orEmpty(),
                color = theme.colors.textSecondary,
                style = theme.typography.callout,
            )
            Text(
                stringResource(
                    if (serverUnavailable) R.string.reauthenticate_unavailable_message
                    else R.string.reauthenticate_expired_message,
                ),
                color = theme.colors.textSecondary,
            )
            PasswordField(
                value = form.password,
                onValueChange = onPasswordChanged,
                label = stringResource(R.string.login_password_label),
                error = when {
                    form.passwordRequired -> stringResource(R.string.login_required_password)
                    form.invalidCredentials -> stringResource(R.string.login_invalid_credentials)
                    else -> null
                },
                enabled = !isAuthenticating,
                visible = passwordVisible,
                onToggleVisibility = { passwordVisible = !passwordVisible },
                onDone = onLogin,
            )
            PrimaryActionButton(
                label = stringResource(if (isAuthenticating) R.string.login_in_progress else R.string.reauthenticate_action),
                onClick = onLogin,
                enabled = !isAuthenticating,
                loading = isAuthenticating,
                modifier = Modifier.fillMaxWidth(),
            )
            if (remainingDays != null && remainingDays > 0) {
                Button(onClick = onEnterOffline, enabled = !isAuthenticating, modifier = Modifier.fillMaxWidth()) {
                    Text(pluralStringResource(R.plurals.offline_enter_action, remainingDays, remainingDays))
                }
                Text(stringResource(R.string.offline_scope_message), color = theme.colors.textSecondary)
            }
            TextButton(onClick = onSwitchServer, enabled = !isAuthenticating) {
                Text(stringResource(R.string.login_switch_server))
            }
        }
    }
}

@Composable
fun OfflineEmptyShell(
    profile: ServerProfile,
    userEmail: String,
    onRetryAuthentication: () -> Unit,
    onSwitchServer: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    Column(
        modifier = modifier.fillMaxSize().padding(theme.spacing.three),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(Icons.Outlined.CloudOff, null, tint = theme.colors.brandAccent)
        Spacer(Modifier.height(theme.spacing.two))
        Text(stringResource(R.string.offline_empty_title), style = theme.typography.title)
        Spacer(Modifier.height(theme.spacing.one))
        Text(stringResource(R.string.offline_empty_message), color = theme.colors.textSecondary)
        Spacer(Modifier.height(theme.spacing.two))
        ServerIdentity(profile.displayName, profile.baseUrl.value)
        Text(userEmail, color = theme.colors.textSecondary)
        Spacer(Modifier.height(theme.spacing.three))
        PrimaryActionButton(
            label = stringResource(R.string.offline_retry_authentication),
            onClick = onRetryAuthentication,
            modifier = Modifier.fillMaxWidth(),
        )
        TextButton(onClick = onSwitchServer) { Text(stringResource(R.string.login_switch_server)) }
    }
}

@Composable
private fun ServerIdentity(name: String, url: String) {
    val theme = WarmPageThemeValues
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(theme.spacing.one)) {
        Icon(Icons.Outlined.Dns, null, tint = theme.colors.textSecondary)
        Column {
            Text(name, style = theme.typography.headline)
            Text(url.removePrefix("https://").removePrefix("http://"), color = theme.colors.textSecondary)
        }
    }
}

@Composable
private fun SetupTextField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    error: String?,
    enabled: Boolean,
    contentType: ContentType,
    keyboardType: KeyboardType = KeyboardType.Text,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = Modifier.fillMaxWidth().semantics { this.contentType = contentType },
        enabled = enabled,
        label = { Text(label) },
        isError = error != null,
        supportingText = error?.let { { Text(it) } },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = keyboardType, imeAction = ImeAction.Next),
    )
}

@Composable
private fun PasswordField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    error: String?,
    enabled: Boolean,
    visible: Boolean,
    onToggleVisibility: () -> Unit,
    onDone: (() -> Unit)? = null,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = Modifier.fillMaxWidth().semantics { contentType = ContentType.Password },
        enabled = enabled,
        label = { Text(label) },
        isError = error != null,
        supportingText = error?.let { { Text(it) } },
        singleLine = true,
        visualTransformation = if (visible) VisualTransformation.None else PasswordVisualTransformation(),
        trailingIcon = {
            IconButton(onClick = onToggleVisibility) {
                Icon(
                    if (visible) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                    stringResource(if (visible) R.string.login_hide_password else R.string.login_show_password),
                )
            }
        },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = if (onDone == null) ImeAction.Next else ImeAction.Done),
        keyboardActions = KeyboardActions(onDone = { onDone?.invoke() }),
    )
}

@Composable
private fun SetupFieldError.setupErrorText(): String = stringResource(
    when (this) {
        SetupFieldError.Required -> R.string.setup_error_required
        SetupFieldError.InvalidEmail -> R.string.setup_error_email
        SetupFieldError.PasswordTooShort -> R.string.setup_error_password_length
        SetupFieldError.PasswordMismatch -> R.string.setup_error_password_mismatch
        SetupFieldError.Rejected -> R.string.setup_error_rejected
    },
)

private const val MILLIS_PER_DAY = 86_400_000L
