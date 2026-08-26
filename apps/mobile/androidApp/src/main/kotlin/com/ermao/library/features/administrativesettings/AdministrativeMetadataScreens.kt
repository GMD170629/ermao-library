package com.ermao.library.features.administrativesettings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp

@Composable
fun MetadataProvidersScreen(
    state: AdministrativePageState<MetadataProvidersSnapshot>,
    locale: AdministrativeLocale,
    onNavigate: (AdministrativeSettingsRoute) -> Unit,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AdministrativePage(AdministrativeCopy.MetadataProviders, locale, onBack, modifier) {
        PageStateContent(state, locale, onRetry) { snapshot ->
            var providers by remember(snapshot) { mutableStateOf(snapshot.providers) }
            AdministrativeSection(AdministrativeCopy.Providers, locale)
            providers.forEach { provider ->
                ListItem(
                    headlineContent = { Text(provider.name) },
                    supportingContent = {
                        Text(
                            if (provider.available) {
                                "${AdministrativeCopy.Available.text(locale)}${provider.latencyMilliseconds?.let { " · $it ms" }.orEmpty()}"
                            } else {
                                AdministrativeCopy.TemporarilyUnavailable.text(locale)
                            },
                        )
                    },
                    trailingContent = { Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null) },
                    colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
                    modifier = Modifier.fillMaxWidth().clickable(role = Role.Button) { onNavigate(AdministrativeSettingsRoute.MetadataProviderEdit(provider.id)) },
                )
                AdministrativeSwitchRow(
                    provider.name,
                    provider.enabled,
                    { enabled -> providers = providers.map { if (it.id == provider.id) it.copy(enabled = enabled) else it } },
                    enabled = provider.available,
                )
            }
            PrimaryAction(AdministrativeCopy.SaveConfiguration, locale, !state.mutationInFlight) {
                onCommand(AdministrativeCommand.SaveMetadataProviders(providers))
            }
        }
    }
}

@Composable
fun MetadataProviderEditScreen(
    state: AdministrativePageState<MetadataProviderEditorSnapshot>,
    locale: AdministrativeLocale,
    onCommand: (AdministrativeCommand) -> Unit,
    onRetry: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    AdministrativePage(AdministrativeCopy.ConfigureProvider, locale, onBack, modifier) {
        PageStateContent(state, locale, onRetry) { initial ->
            var enabled by remember(initial) { mutableStateOf(initial.provider.enabled) }
            var fieldValues by remember(initial) { mutableStateOf(initial.fields.associate { it.key to it.value }) }
            ListItem(
                headlineContent = { Text(initial.provider.name) },
                supportingContent = { Text(if (initial.provider.available) AdministrativeCopy.Available.text(locale) else AdministrativeCopy.TemporarilyUnavailable.text(locale)) },
                colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
            )
            AdministrativeSwitchRow(AdministrativeCopy.Enabled.text(locale), enabled, { enabled = it })
            initial.fields.forEach { field ->
                val value = fieldValues[field.key] ?: ProviderFieldValue.Empty
                when (field.kind) {
                    MetadataProviderFieldKind.Toggle -> AdministrativeSwitchRow(
                        field.label,
                        (value as? ProviderFieldValue.Toggle)?.value ?: false,
                        { next -> fieldValues = fieldValues + (field.key to ProviderFieldValue.Toggle(next)) },
                    )
                    else -> AdministrativeTextField(
                        value.displayText(),
                        { next -> fieldValues = fieldValues + (field.key to field.kind.parse(next)) },
                        AdministrativeCopy.SaveConfiguration,
                        locale,
                        password = field.secret,
                        supporting = if (field.secret && field.configuredSecret) AdministrativeCopy.PasswordUnchanged.text(locale) else field.label,
                    )
                }
            }
            initial.lastTest?.let { test ->
                ListItem(
                    headlineContent = { Text(if (test.successful) AdministrativeCopy.ConnectionHealthy.text(locale) else AdministrativeCopy.OperationFailed.text(locale)) },
                    supportingContent = { Text(test.latencyMilliseconds?.let { "$it ms" } ?: test.code.orEmpty()) },
                    colors = ListItemDefaults.colors(containerColor = androidx.compose.ui.graphics.Color.Transparent),
                )
            }
            val draft = { MetadataProviderDraft(initial.provider.id, enabled, initial.provider.id.hashCode(), fieldValues, emptySet()) }
            TextButton(
                onClick = { onCommand(AdministrativeCommand.TestMetadataProvider(initial.provider.id)) },
                enabled = !state.mutationInFlight,
                modifier = Modifier.fillMaxWidth(),
            ) { Text(AdministrativeCopy.TestProviders.text(locale)) }
            PrimaryAction(AdministrativeCopy.SaveConfiguration, locale, !state.mutationInFlight) {
                onCommand(AdministrativeCommand.SaveMetadataProvider(draft()))
            }
        }
    }
}

private fun ProviderFieldValue.displayText(): String = when (this) {
    is ProviderFieldValue.Text -> value
    is ProviderFieldValue.Integer -> value.toString()
    is ProviderFieldValue.Decimal -> value.toString()
    is ProviderFieldValue.TextList -> value.joinToString(", ")
    is ProviderFieldValue.Toggle -> value.toString()
    ProviderFieldValue.Empty -> ""
}

private fun MetadataProviderFieldKind.parse(value: String): ProviderFieldValue = when (this) {
    MetadataProviderFieldKind.Text -> ProviderFieldValue.Text(value)
    MetadataProviderFieldKind.Integer -> ProviderFieldValue.Integer(value.toLongOrNull() ?: 0L)
    MetadataProviderFieldKind.Decimal -> ProviderFieldValue.Decimal(value.toDoubleOrNull() ?: 0.0)
    MetadataProviderFieldKind.TextList -> ProviderFieldValue.TextList(value.split(',').map(String::trim).filter(String::isNotBlank))
    MetadataProviderFieldKind.Toggle -> ProviderFieldValue.Toggle(value.toBooleanStrictOrNull() ?: false)
}
