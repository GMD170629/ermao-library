package com.ermao.library.features.servers

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.outlined.Security
import androidx.compose.material.icons.outlined.WarningAmber
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import com.ermao.library.R
import com.ermao.library.bootstrap.ServerFormError
import com.ermao.library.bootstrap.ServerFormState
import com.ermao.library.ui.theme.WarmPageThemeValues

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ServerEditorScreen(
    form: ServerFormState,
    isChecking: Boolean,
    connectionFailed: Boolean,
    unexpectedFailure: Boolean,
    modifier: Modifier = Modifier,
    isEditing: Boolean = false,
    insecureTls: Boolean = false,
    onDisplayNameChanged: (String) -> Unit,
    onBaseUrlChanged: (String) -> Unit,
    onSubmit: () -> Unit,
    onBack: () -> Unit,
) {
    val theme = WarmPageThemeValues
    Scaffold(
        modifier = modifier,
        containerColor = theme.colors.canvas,
        topBar = {
            TopAppBar(
                title = {
                    Text(stringResource(if (isEditing) R.string.server_edit_title else R.string.server_add_title))
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
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
                .padding(horizontal = theme.spacing.two, vertical = theme.spacing.three),
            verticalArrangement = Arrangement.spacedBy(theme.spacing.two),
        ) {
            Text(
                text = stringResource(R.string.server_screen_description),
                color = theme.colors.textSecondary,
                style = theme.typography.body,
            )
            OutlinedTextField(
                value = form.displayName,
                onValueChange = onDisplayNameChanged,
                modifier = Modifier.fillMaxWidth(),
                enabled = !isChecking,
                isError = form.displayNameError != null,
                label = { Text(stringResource(R.string.server_display_name_label)) },
                placeholder = { Text(stringResource(R.string.server_display_name_placeholder)) },
                supportingText = form.displayNameError?.let {
                    { Text(stringResource(R.string.server_invalid_name)) }
                },
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                singleLine = true,
                shape = RoundedCornerShape(theme.radii.control),
            )
            OutlinedTextField(
                value = form.rawBaseUrl,
                onValueChange = onBaseUrlChanged,
                modifier = Modifier.fillMaxWidth(),
                enabled = !isChecking,
                isError = form.baseUrlError == ServerFormError.InvalidBaseUrl,
                label = { Text(stringResource(R.string.server_url_label)) },
                placeholder = { Text(stringResource(R.string.server_url_placeholder)) },
                supportingText = {
                    Text(
                        stringResource(
                            if (form.baseUrlError == ServerFormError.InvalidBaseUrl) {
                                R.string.server_invalid_url
                            } else {
                                R.string.server_url_supporting_text
                            },
                        ),
                    )
                },
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Uri,
                    imeAction = ImeAction.Done,
                ),
                keyboardActions = KeyboardActions(onDone = { onSubmit() }),
                singleLine = true,
                shape = RoundedCornerShape(theme.radii.control),
            )
            if (insecureTls) {
                Text(
                    text = stringResource(R.string.server_tls_insecure_status),
                    color = MaterialTheme.colorScheme.error,
                    style = theme.typography.callout,
                )
            } else {
                SystemTrustRow()
            }
            if (connectionFailed || unexpectedFailure) {
                InlineConnectionError(unexpectedFailure = unexpectedFailure)
            }
            PrimaryActionButton(
                label = stringResource(
                    when {
                        isChecking -> R.string.server_connecting_action
                        connectionFailed || unexpectedFailure -> R.string.server_retry_action
                        isEditing -> R.string.server_save_action
                        else -> R.string.server_connect_action
                    },
                ),
                onClick = onSubmit,
                enabled = !isChecking,
                loading = isChecking,
                modifier = Modifier
                    .fillMaxWidth()
                    .testTag("server-connect"),
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TlsRiskScreen(
    serverDisplayName: String,
    serverAddress: String,
    onBackToEdit: () -> Unit,
    onPermanentlyIgnore: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    var showConfirmation by remember { mutableStateOf(false) }

    Scaffold(
        modifier = modifier,
        containerColor = theme.colors.canvas,
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.tls_risk_title)) },
                navigationIcon = {
                    IconButton(onClick = onBackToEdit) {
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
                .padding(theme.spacing.three),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Icon(
                imageVector = Icons.Outlined.WarningAmber,
                contentDescription = null,
                modifier = Modifier.size(theme.spacing.six),
                tint = MaterialTheme.colorScheme.error,
            )
            Spacer(Modifier.height(theme.spacing.three))
            Text(
                text = stringResource(R.string.tls_risk_title),
                color = theme.colors.textPrimary,
                style = theme.typography.title,
            )
            Spacer(Modifier.height(theme.spacing.one))
            Text(
                text = stringResource(R.string.tls_server_identity, serverDisplayName, serverAddress),
                color = theme.colors.textPrimary,
                style = theme.typography.headline,
            )
            Spacer(Modifier.height(theme.spacing.two))
            Text(
                text = stringResource(R.string.tls_risk_message),
                color = theme.colors.textSecondary,
                style = theme.typography.body,
            )
            Spacer(Modifier.height(theme.spacing.four))
            PrimaryActionButton(
                label = stringResource(R.string.tls_back_to_edit),
                onClick = onBackToEdit,
                modifier = Modifier.fillMaxWidth(),
            )
            TextButton(
                onClick = { showConfirmation = true },
                modifier = Modifier.heightIn(min = theme.spacing.six),
                colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
            ) {
                Text(stringResource(R.string.tls_ignore_action))
            }
        }
    }

    if (showConfirmation) {
        AlertDialog(
            onDismissRequest = { showConfirmation = false },
            title = { Text(stringResource(R.string.tls_confirmation_title)) },
            text = { Text(stringResource(R.string.tls_confirmation_message, serverDisplayName)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        showConfirmation = false
                        onPermanentlyIgnore()
                    },
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
                ) {
                    Text(stringResource(R.string.tls_ignore_action))
                }
            },
            dismissButton = {
                TextButton(onClick = { showConfirmation = false }) {
                    Text(stringResource(R.string.cancel))
                }
            },
        )
    }
}

@Composable
fun BlockingServerStateScreen(
    title: String,
    message: String,
    primaryLabel: String,
    onPrimary: () -> Unit,
    modifier: Modifier = Modifier,
    secondaryLabel: String? = null,
    onSecondary: (() -> Unit)? = null,
) {
    val theme = WarmPageThemeValues
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(theme.spacing.three),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(title, color = theme.colors.textPrimary, style = theme.typography.title)
        Spacer(Modifier.height(theme.spacing.two))
        Text(message, color = theme.colors.textSecondary, style = theme.typography.body)
        Spacer(Modifier.height(theme.spacing.four))
        PrimaryActionButton(
            label = primaryLabel,
            onClick = onPrimary,
            modifier = Modifier.fillMaxWidth(),
        )
        if (secondaryLabel != null && onSecondary != null) {
            Spacer(Modifier.height(theme.spacing.one))
            OutlinedButton(
                onClick = onSecondary,
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = theme.spacing.six),
                shape = RoundedCornerShape(theme.radii.control),
            ) {
                Text(secondaryLabel)
            }
        }
    }
}

enum class BrandImageShape {
    Task,
    Circle,
}

@Composable
fun BrandImage(
    size: Int,
    shape: BrandImageShape,
    modifier: Modifier = Modifier,
) {
    val theme = WarmPageThemeValues
    Image(
        painter = painterResource(R.drawable.ermao_library_brand),
        contentDescription = null,
        contentScale = ContentScale.Crop,
        modifier = modifier
            .size(size.dp)
            .clip(
                when (shape) {
                    BrandImageShape.Task -> RoundedCornerShape(theme.radii.task)
                    BrandImageShape.Circle -> CircleShape
                },
            ),
    )
}

@Composable
fun PrimaryActionButton(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    loading: Boolean = false,
) {
    val theme = WarmPageThemeValues
    Button(
        onClick = onClick,
        modifier = modifier.heightIn(min = theme.spacing.six),
        enabled = enabled,
        shape = RoundedCornerShape(theme.radii.control),
        colors = ButtonDefaults.buttonColors(
            containerColor = theme.colors.actionAccent,
            contentColor = theme.colors.onAction,
        ),
    ) {
        if (loading) {
            CircularProgressIndicator(
                modifier = Modifier.size(theme.spacing.three),
                color = theme.colors.onAction,
                strokeWidth = 2.dp,
            )
        } else {
            Text(label, style = theme.typography.button)
        }
    }
}

@Composable
private fun SystemTrustRow() {
    val theme = WarmPageThemeValues
    Surface(color = Color.Transparent) {
        Column {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = theme.spacing.six)
                    .padding(vertical = theme.spacing.oneAndHalf),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(theme.spacing.oneAndHalf),
            ) {
                Icon(
                    imageVector = Icons.Outlined.Security,
                    contentDescription = null,
                    tint = theme.colors.textSecondary,
                )
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        stringResource(R.string.server_system_trust_title),
                        color = theme.colors.textPrimary,
                        style = theme.typography.headline,
                    )
                    Text(
                        stringResource(R.string.server_system_trust_description),
                        color = theme.colors.textSecondary,
                        style = theme.typography.callout,
                    )
                }
            }
            HorizontalDivider(color = theme.colors.divider)
        }
    }
}

@Composable
private fun InlineConnectionError(unexpectedFailure: Boolean) {
    val theme = WarmPageThemeValues
    Surface(
        color = MaterialTheme.colorScheme.errorContainer,
        shape = RoundedCornerShape(theme.radii.control),
    ) {
        Box(Modifier.padding(theme.spacing.two)) {
            Column(verticalArrangement = Arrangement.spacedBy(theme.spacing.half)) {
                Text(
                    text = stringResource(R.string.server_connection_failed_title),
                    color = MaterialTheme.colorScheme.onErrorContainer,
                    style = theme.typography.headline,
                )
                Text(
                    text = stringResource(
                        if (unexpectedFailure) {
                            R.string.unexpected_failure
                        } else {
                            R.string.server_connection_failed_message
                        },
                    ),
                    color = MaterialTheme.colorScheme.onErrorContainer,
                    style = theme.typography.callout,
                )
            }
        }
    }
}
