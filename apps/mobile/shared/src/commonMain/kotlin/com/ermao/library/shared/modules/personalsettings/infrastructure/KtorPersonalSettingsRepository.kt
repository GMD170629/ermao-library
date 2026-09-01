package com.ermao.library.shared.modules.personalsettings.infrastructure

import com.ermao.library.shared.core.network.ApiClient
import com.ermao.library.shared.core.network.ApiClientFactory
import com.ermao.library.shared.core.network.ApiMethod
import com.ermao.library.shared.core.network.ApiMultipartFile
import com.ermao.library.shared.core.network.ApiMultipartRequest
import com.ermao.library.shared.core.network.ApiRequest
import com.ermao.library.shared.core.network.ApiResult
import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.core.network.AppErrorKind
import com.ermao.library.shared.modules.personalsettings.application.PersonalSettingsRepository
import com.ermao.library.shared.modules.personalsettings.domain.PersonalAccount
import com.ermao.library.shared.modules.personalsettings.domain.PersonalAvatar
import com.ermao.library.shared.modules.personalsettings.domain.PersonalAvatarUpload
import com.ermao.library.shared.modules.personalsettings.domain.PersonalPasswordChange
import com.ermao.library.shared.modules.personalsettings.domain.PersonalPreferences
import com.ermao.library.shared.modules.personalsettings.domain.PersonalServerAbout
import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsContext
import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsError
import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsErrorKind
import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsFieldViolation
import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsLocale
import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsResult
import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsSnapshot
import com.ermao.library.shared.modules.personalsettings.domain.PersonalSettingsTlsMode
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrl
import com.ermao.library.shared.modules.servers.domain.ServerBaseUrlParseResult
import com.ermao.library.shared.modules.servers.domain.ServerProfile
import com.ermao.library.shared.modules.servers.domain.TlsMode
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

internal class KtorPersonalSettingsRepository(
    private val clientProvider: (ServerProfile) -> ApiClient,
) : PersonalSettingsRepository {
    constructor(clients: ApiClientFactory) : this(clients::create)

    override suspend fun loadSettings(
        context: PersonalSettingsContext,
    ): PersonalSettingsResult<PersonalSettingsSnapshot> =
        mapResult(
            request(context) { client ->
                client.execute(
                    ApiRequest(
                        method = ApiMethod.Get,
                        apiPath = "/api/auth/me",
                        responseDeserializer = SettingsSessionWire.serializer(),
                    ),
                )
            },
        ) { wire ->
            wire.toDomain()?.let { snapshot -> PersonalSettingsResult.Content(snapshot) }
                ?: protocolFailure("UNSUPPORTED_LOCALE")
        }

    override suspend fun updateName(
        context: PersonalSettingsContext,
        name: String,
    ): PersonalSettingsResult<PersonalAccount> {
        val normalizedName = name.trim()
        if (normalizedName.isEmpty() || normalizedName.length > MAX_NAME_LENGTH) {
            return validationFailure("INVALID_NAME", "name")
        }
        return mapResult(
            request(context) { client ->
                client.execute(
                    ApiRequest(
                        method = ApiMethod.Patch,
                        apiPath = "/api/auth/account/name",
                        responseDeserializer = SettingsUserPayloadWire.serializer(),
                        requestBody = encoder.encodeToString(UpdateNameWire(normalizedName)),
                    ),
                )
            },
        ) { wire -> PersonalSettingsResult.Content(wire.user.toDomain()) }
    }

    override suspend fun updateEmail(
        context: PersonalSettingsContext,
        email: String,
        currentPassword: String,
    ): PersonalSettingsResult<PersonalAccount> {
        val normalizedEmail = email.trim()
        if (normalizedEmail.isEmpty()) return validationFailure("INVALID_EMAIL", "email")
        if (currentPassword.isEmpty() || currentPassword.length > MAX_PASSWORD_LENGTH) {
            return validationFailure("INVALID_CURRENT_PASSWORD", "currentPassword")
        }
        return mapResult(
            request(context) { client ->
                client.execute(
                    ApiRequest(
                        method = ApiMethod.Patch,
                        apiPath = "/api/auth/account/email",
                        responseDeserializer = SettingsUserPayloadWire.serializer(),
                        requestBody =
                            encoder.encodeToString(
                                UpdateEmailWire(
                                    email = normalizedEmail,
                                    currentPassword = currentPassword,
                                ),
                            ),
                    ),
                )
            },
        ) { wire -> PersonalSettingsResult.Content(wire.user.toDomain()) }
    }

    override suspend fun updatePassword(
        context: PersonalSettingsContext,
        currentPassword: String,
        newPassword: String,
    ): PersonalSettingsResult<PersonalPasswordChange> {
        if (currentPassword.isEmpty() || currentPassword.length > MAX_PASSWORD_LENGTH) {
            return validationFailure("INVALID_CURRENT_PASSWORD", "currentPassword")
        }
        if (newPassword.length !in MIN_PASSWORD_LENGTH..MAX_PASSWORD_LENGTH) {
            return validationFailure("INVALID_NEW_PASSWORD", "newPassword")
        }
        return mapResult(
            request(context) { client ->
                client.execute(
                    ApiRequest(
                        method = ApiMethod.Patch,
                        apiPath = "/api/auth/account/password",
                        responseDeserializer = SettingsPasswordChangedWire.serializer(),
                        requestBody =
                            encoder.encodeToString(
                                UpdatePasswordWire(
                                    currentPassword = currentPassword,
                                    newPassword = newPassword,
                                ),
                            ),
                    ),
                )
            },
        ) { wire ->
            if (!wire.passwordChanged || !wire.requiresLogin) {
                protocolFailure("PASSWORD_CHANGE_NOT_CONFIRMED")
            } else {
                PersonalSettingsResult.Content(PersonalPasswordChange(wire.requiresLogin))
            }
        }
    }

    override suspend fun loadAvatar(
        context: PersonalSettingsContext,
        etag: String?,
    ): PersonalSettingsResult<PersonalAvatar> =
        mapResult(
            request(context) { client ->
                client.loadAuthenticatedAsset(
                    apiPath = "/api/auth/avatar",
                    etag = etag,
                    maximumBytes = MAX_AVATAR_BYTES,
                )
            },
        ) { asset ->
            PersonalSettingsResult.Content(
                PersonalAvatar(
                    bytes = asset.bytes,
                    contentType = asset.mimeType,
                    etag = asset.etag,
                    notModified = asset.notModified,
                ),
            )
        }

    override suspend fun uploadAvatar(
        context: PersonalSettingsContext,
        upload: PersonalAvatarUpload,
    ): PersonalSettingsResult<PersonalAccount> {
        if (upload.bytes.isEmpty()) return validationFailure("AVATAR_EMPTY", "avatar")
        if (upload.bytes.size > MAX_AVATAR_BYTES) return validationFailure("AVATAR_TOO_LARGE", "avatar")
        return mapResult(
            request(context) { client ->
                client.executeMultipart(
                    ApiMultipartRequest(
                        apiPath = "/api/auth/avatar",
                        responseDeserializer = SettingsUserPayloadWire.serializer(),
                        file =
                            ApiMultipartFile(
                                fieldName = "avatar",
                                fileName = "avatar.${upload.mimeType.fileExtension}",
                                contentType = upload.mimeType.wireValue,
                                bytes = upload.bytes,
                            ),
                    ),
                )
            },
        ) { wire -> PersonalSettingsResult.Content(wire.user.toDomain()) }
    }

    override suspend fun deleteAvatar(
        context: PersonalSettingsContext,
    ): PersonalSettingsResult<PersonalAccount> =
        mapResult(
            request(context) { client ->
                client.execute(
                    ApiRequest(
                        method = ApiMethod.Delete,
                        apiPath = "/api/auth/avatar",
                        responseDeserializer = SettingsUserPayloadWire.serializer(),
                    ),
                )
            },
        ) { wire -> PersonalSettingsResult.Content(wire.user.toDomain()) }

    override suspend fun updateLocale(
        context: PersonalSettingsContext,
        locale: PersonalSettingsLocale,
    ): PersonalSettingsResult<PersonalPreferences> =
        mapResult(
            request(context) { client ->
                client.execute(
                    ApiRequest(
                        method = ApiMethod.Patch,
                        apiPath = "/api/auth/preferences",
                        responseDeserializer = SettingsPreferencesPayloadWire.serializer(),
                        requestBody =
                            encoder.encodeToString(
                                UpdateLocaleWire(LocalePreferenceWire(locale.wireValue)),
                            ),
                    ),
                )
            },
        ) { wire ->
            wire.preferences.toDomain()?.let { preferences -> PersonalSettingsResult.Content(preferences) }
                ?: protocolFailure("UNSUPPORTED_LOCALE")
        }

    override suspend fun updateAudioPlaybackRate(
        context: PersonalSettingsContext,
        playbackRate: Double,
    ): PersonalSettingsResult<PersonalPreferences> {
        if (!playbackRate.isFinite() || playbackRate !in 0.5..3.0) {
            return validationFailure("INVALID_AUDIO_PLAYBACK_RATE", "audio.playbackRate")
        }
        return mapResult(
            request(context) { client ->
                client.execute(
                    ApiRequest(
                        method = ApiMethod.Patch,
                        apiPath = "/api/auth/preferences",
                        responseDeserializer = SettingsPreferencesPayloadWire.serializer(),
                        requestBody = encoder.encodeToString(
                            UpdateAudioPlaybackRateWire(AudioPlaybackRatePreferenceWire(playbackRate)),
                        ),
                    ),
                )
            },
        ) { wire ->
            wire.preferences.toDomain()?.let { preferences -> PersonalSettingsResult.Content(preferences) }
                ?: protocolFailure("UNSUPPORTED_AUDIO_PLAYBACK_RATE")
        }
    }

    override suspend fun loadServerAbout(
        context: PersonalSettingsContext,
    ): PersonalSettingsResult<PersonalServerAbout> =
        mapResult(
            request(context) { client ->
                client.execute(
                    ApiRequest(
                        method = ApiMethod.Get,
                        apiPath = "/api/mobile/compatibility",
                        responseDeserializer = PersonalCompatibilityWire.serializer(),
                    ),
                )
            },
        ) { wire -> PersonalSettingsResult.Content(wire.toDomain()) }

    private suspend fun <T> request(
        context: PersonalSettingsContext,
        block: suspend (ApiClient) -> ApiResult<T>,
    ): ApiResult<T> {
        val client = clientProvider(context.toServerProfile())
        return try {
            block(client)
        } finally {
            client.close()
        }
    }

    private fun PersonalSettingsContext.toServerProfile(): ServerProfile {
        val parsed = ServerBaseUrl.parse(baseUrl)
        check(parsed is ServerBaseUrlParseResult.Valid) { "Invalid personal-settings server base URL" }
        return ServerProfile(
            id = profileId,
            displayName = profileDisplayName,
            baseUrl = parsed.baseUrl,
            serverIdentity = serverIdentity,
            isActive = true,
            tlsMode =
                when (tlsMode) {
                    PersonalSettingsTlsMode.SystemTrust -> TlsMode.SystemTrust
                    PersonalSettingsTlsMode.InsecureSkipAllValidation -> TlsMode.InsecureSkipAllValidation
                },
        )
    }

    private fun <Wire, Domain> mapResult(
        result: ApiResult<Wire>,
        transform: (Wire) -> PersonalSettingsResult<Domain>,
    ): PersonalSettingsResult<Domain> =
        when (result) {
            is ApiResult.Success -> transform(result.value)
            is ApiResult.Failure -> PersonalSettingsResult.Failure(result.error.toPersonalSettingsError())
        }

    private fun <T> validationFailure(
        code: String,
        field: String,
    ): PersonalSettingsResult<T> =
        PersonalSettingsResult.Failure(
            PersonalSettingsError(
                kind = PersonalSettingsErrorKind.Validation,
                code = code,
                fieldViolations = listOf(PersonalSettingsFieldViolation(field, "INVALID_FIELD")),
            ),
        )

    private fun <T> protocolFailure(code: String): PersonalSettingsResult<T> =
        PersonalSettingsResult.Failure(
            PersonalSettingsError(
                kind = PersonalSettingsErrorKind.Protocol,
                code = code,
            ),
        )

    private fun AppError.toPersonalSettingsError(): PersonalSettingsError =
        PersonalSettingsError(
            kind =
                when (kind) {
                    AppErrorKind.InvalidRequest,
                    AppErrorKind.PayloadTooLarge,
                    AppErrorKind.Validation,
                    -> PersonalSettingsErrorKind.Validation
                    AppErrorKind.Unauthorized -> PersonalSettingsErrorKind.Unauthorized
                    AppErrorKind.Forbidden -> PersonalSettingsErrorKind.Forbidden
                    AppErrorKind.NotFoundOrUnavailable,
                    AppErrorKind.Gone,
                    -> PersonalSettingsErrorKind.NotFound
                    AppErrorKind.Conflict -> PersonalSettingsErrorKind.Conflict
                    AppErrorKind.RateLimited -> PersonalSettingsErrorKind.RateLimited
                    AppErrorKind.ServiceUnavailable,
                    AppErrorKind.ServerFailure,
                    -> PersonalSettingsErrorKind.Server
                    AppErrorKind.NetworkUnavailable,
                    AppErrorKind.Timeout,
                    AppErrorKind.TlsFailure,
                    AppErrorKind.StorageFailure,
                    AppErrorKind.Cancelled,
                    -> PersonalSettingsErrorKind.Transport
                    AppErrorKind.ProtocolViolation,
                    -> PersonalSettingsErrorKind.Protocol
                },
            code = code,
            fieldViolations =
                fieldErrors.keys.sorted().map { field ->
                    PersonalSettingsFieldViolation(field = field, code = "INVALID_FIELD")
                },
        )

    private companion object {
        val encoder = Json {
            encodeDefaults = false
            explicitNulls = false
        }
        const val MAX_NAME_LENGTH = 40
        const val MIN_PASSWORD_LENGTH = 10
        const val MAX_PASSWORD_LENGTH = 128
        const val MAX_AVATAR_BYTES = 5 * 1024 * 1024
    }
}
