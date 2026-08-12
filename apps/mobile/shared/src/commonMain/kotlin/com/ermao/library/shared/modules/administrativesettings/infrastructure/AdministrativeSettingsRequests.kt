package com.ermao.library.shared.modules.administrativesettings.infrastructure

import com.ermao.library.shared.modules.administrativesettings.domain.*
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

internal fun smtpRequest(update: SmtpSettingsUpdate): JsonObject = buildJsonObject {
    put("smtp", buildJsonObject {
        put("host", update.host)
        put("port", update.port)
        put("security", update.security.wireValue)
        put("username", update.username)
        update.password?.let { put("password", it) }
        put("fromEmail", update.fromEmail)
        put("fromName", update.fromName)
        put("maxAttachmentMb", update.maximumAttachmentMegabytes?.let(::JsonPrimitive) ?: JsonNull)
    })
    put("clearSmtpPassword", update.clearPassword)
}

internal fun CreateManagedUser.toRequest(): JsonObject = buildJsonObject {
    put("name", name.trim())
    put("email", email.trim())
    put("password", password)
    put("role", role.wireValue)
    put("canManageSystem", role == ManagedUserRole.Member && canManageSystem)
    put("canViewManualImports", role == ManagedUserRole.Member && canViewManualImports)
    put("monitorFolderIds", JsonArray(if (role == ManagedUserRole.Member) monitorFolderIds.map(::JsonPrimitive) else emptyList()))
    put("locale", locale.wireValue)
}

internal fun UpdateManagedUser.toRequest(): JsonObject = buildJsonObject {
    put("name", name.trim())
    put("email", email.trim())
    put("role", role.wireValue)
    put("status", status.wireValue)
    put("canManageSystem", role == ManagedUserRole.Member && canManageSystem)
    put("canViewManualImports", role == ManagedUserRole.Member && canViewManualImports)
    put("monitorFolderIds", JsonArray(if (role == ManagedUserRole.Member) monitorFolderIds.map(::JsonPrimitive) else emptyList()))
    put("locale", locale.wireValue)
}

internal fun MonitorFolderDraft.toRequest(): JsonObject = buildJsonObject {
    put("rootPath", rootPath.trim())
    put("name", name?.trim()?.let(::JsonPrimitive) ?: JsonNull)
    put("shelfId", shelfId?.let(::JsonPrimitive) ?: JsonNull)
    put("enabled", enabled)
    put("mediaKindPolicy", mediaKindPolicy.wireValue)
    put("ignorePatterns", ignorePatterns?.let(::JsonPrimitive) ?: JsonNull)
    put("ignoreHidden", ignoreHidden)
    put("minFileSizeBytes", minimumFileSizeBytes)
    put("description", description?.trim()?.let(::JsonPrimitive) ?: JsonNull)
}

internal fun OrganizePolicy.toRequest(): JsonObject = buildJsonObject {
    put("enabled", enabled)
    put("scheduleMode", scheduleMode.wireValue)
    put("intervalMinutes", intervalMinutes)
    put("autoRunOnNew", autoRunOnNew)
    put("rules", buildJsonObject {
        put("unrecognized", rules.unrecognized)
        put("missingMetadata", rules.missingMetadata)
    })
    put("writeMetadataToFiles", writeMetadataToFiles)
    put("preferLocalMetadata", preferLocalMetadata)
    put("localMetadataPriority", JsonArray(localMetadataPriority.map { JsonPrimitive(it.wireValue) }))
}

private fun ProviderSettingValue.toJson(): JsonElement = when (this) {
    ProviderSettingValue.Empty -> JsonNull
    is ProviderSettingValue.Text -> JsonPrimitive(value)
    is ProviderSettingValue.Toggle -> JsonPrimitive(value)
    is ProviderSettingValue.Integer -> JsonPrimitive(value)
    is ProviderSettingValue.Decimal -> JsonPrimitive(value)
    is ProviderSettingValue.TextList -> JsonArray(value.map(::JsonPrimitive))
}

internal fun MetadataProviderUpdate.toRequest(): JsonObject = buildJsonObject {
    put("enabled", enabled)
    put("priority", priority)
    put("config", JsonObject(config.mapValues { (_, value) -> value.toJson() }))
    put("clearSecrets", JsonArray(clearSecrets.map(::JsonPrimitive)))
}

internal fun List<MetadataPipelineEntry>.toPipelineRequest(): JsonObject = buildJsonObject {
    put("items", buildJsonArray {
        this@toPipelineRequest.forEach { entry ->
            add(buildJsonObject {
                put("providerId", entry.providerId)
                put("enabled", entry.enabled)
            })
        }
    })
}

private fun SettingValue.toJson(): JsonElement = when (this) {
    SettingValue.Empty -> JsonNull
    is SettingValue.Text -> JsonPrimitive(value)
    is SettingValue.Integer -> JsonPrimitive(value)
    is SettingValue.Decimal -> JsonPrimitive(value)
    is SettingValue.Toggle -> JsonPrimitive(value)
    is SettingValue.TextList -> JsonArray(value.map(::JsonPrimitive))
}

internal fun systemSettingsRequest(settings: Map<String, SettingValue>): JsonObject = buildJsonObject {
    put("settings", JsonObject(settings.mapValues { (_, value) -> value.toJson() }))
}
