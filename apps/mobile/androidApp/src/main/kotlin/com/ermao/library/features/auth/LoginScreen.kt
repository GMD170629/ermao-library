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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material.icons.outlined.Dns
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
import androidx.compose.ui.semantics.contentType
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import com.ermao.library.R
import com.ermao.library.bootstrap.LoginFormState
import com.ermao.library.features.servers.BrandImage
import com.ermao.library.features.servers.BrandImageShape
import com.ermao.library.features.servers.PrimaryActionButton
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.ui.theme.WarmPageThemeValues

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LoginScreen(
    profile: ServerProfile,
    form: LoginFormState,
    isAuthenticating: Boolean,
    sessionMessage: String?,
    unexpectedFailure: Boolean,
    onEmailChanged: (String) -> Unit,
    onPasswordChanged: (String) -> Unit,
    onLogin: () -> Unit,
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
                title = { Text(stringResource(R.string.login_action)) },
                navigationIcon = {
                    IconButton(onClick = onSwitchServer) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = stringResource(R.string.navigate_back),
                        )
                    }
                },
            )
        },
    ) { contentPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = theme.spacing.three, vertical = theme.spacing.three),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            BrandImage(size = 112, shape = BrandImageShape.Circle)
            Spacer(Modifier.height(theme.spacing.three))
            Text(
                text = stringResource(R.string.login_title),
                color = theme.colors.textPrimary,
                style = theme.typography.title,
            )
            Spacer(Modifier.height(theme.spacing.three))
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
            ) {
                Icon(
                    imageVector = Icons.Outlined.Dns,
                    contentDescription = null,
                    tint = theme.colors.textSecondary,
                )
                Column {
                    Text(
                        text = profile.displayName,
                        color = theme.colors.textPrimary,
                        style = theme.typography.headline,
                    )
                    Text(
                        text = profile.baseUrl.value.removePrefix("https://").removePrefix("http://"),
                        color = theme.colors.textSecondary,
                        style = theme.typography.callout,
                    )
                }
            }
            if (sessionMessage != null) {
                Spacer(Modifier.height(theme.spacing.two))
                Text(
                    text = sessionMessage,
                    modifier = Modifier.fillMaxWidth(),
                    color = MaterialTheme.colorScheme.error,
                    style = theme.typography.callout,
                )
            }
            Spacer(Modifier.height(theme.spacing.three))
            OutlinedTextField(
                value = form.email,
                onValueChange = onEmailChanged,
                modifier = Modifier
                    .fillMaxWidth()
                    .semantics { contentType = ContentType.EmailAddress },
                enabled = !isAuthenticating,
                isError = form.emailRequired,
                label = { Text(stringResource(R.string.login_email_label)) },
                supportingText = if (form.emailRequired) {
                    { Text(stringResource(R.string.login_required_email)) }
                } else {
                    null
                },
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Email,
                    imeAction = ImeAction.Next,
                ),
                singleLine = true,
                shape = RoundedCornerShape(theme.radii.control),
            )
            Spacer(Modifier.height(theme.spacing.one))
            OutlinedTextField(
                value = form.password,
                onValueChange = onPasswordChanged,
                modifier = Modifier
                    .fillMaxWidth()
                    .semantics { contentType = ContentType.Password },
                enabled = !isAuthenticating,
                isError = form.passwordRequired || form.invalidCredentials,
                label = { Text(stringResource(R.string.login_password_label)) },
                supportingText = when {
                    form.passwordRequired -> {
                        { Text(stringResource(R.string.login_required_password)) }
                    }
                    form.invalidCredentials -> {
                        { Text(stringResource(R.string.login_invalid_credentials)) }
                    }
                    else -> null
                },
                visualTransformation = if (passwordVisible) {
                    VisualTransformation.None
                } else {
                    PasswordVisualTransformation()
                },
                trailingIcon = {
                    val label = stringResource(
                        if (passwordVisible) R.string.login_hide_password else R.string.login_show_password,
                    )
                    IconButton(onClick = { passwordVisible = !passwordVisible }) {
                        Icon(
                            imageVector = if (passwordVisible) {
                                Icons.Filled.VisibilityOff
                            } else {
                                Icons.Filled.Visibility
                            },
                            contentDescription = label,
                        )
                    }
                },
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Password,
                    imeAction = ImeAction.Done,
                ),
                keyboardActions = KeyboardActions(onDone = { onLogin() }),
                singleLine = true,
                shape = RoundedCornerShape(theme.radii.control),
            )
            if (unexpectedFailure) {
                Spacer(Modifier.height(theme.spacing.one))
                Text(
                    text = stringResource(R.string.unexpected_failure),
                    modifier = Modifier.fillMaxWidth(),
                    color = MaterialTheme.colorScheme.error,
                    style = theme.typography.callout,
                )
            }
            Spacer(Modifier.height(theme.spacing.three))
            PrimaryActionButton(
                label = stringResource(
                    if (isAuthenticating) R.string.login_in_progress else R.string.login_action,
                ),
                onClick = onLogin,
                enabled = !isAuthenticating,
                loading = isAuthenticating,
                modifier = Modifier
                    .fillMaxWidth()
                    .testTag("login-submit"),
            )
            TextButton(onClick = onSwitchServer, enabled = !isAuthenticating) {
                Text(
                    text = stringResource(R.string.login_switch_server),
                    color = theme.colors.actionAccent,
                )
            }
        }
    }
}
