package com.ermao.library.shared.core.network

import kotlinx.serialization.DeserializationStrategy
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.decodeFromJsonElement

@Serializable
internal data class ApiErrorWire(
    val message: String? = null,
    val code: String? = null,
    val details: JsonElement? = null,
    val params: JsonObject? = null,
    val current: JsonObject? = null,
)

internal class ApiEnvelopeDecoder(
    private val json: Json,
) {
    fun <T> decode(
        statusCode: Int,
        body: String,
        dataDeserializer: DeserializationStrategy<T>,
        headers: Map<String, List<String>> = emptyMap(),
    ): ApiResult<T> {
        val envelope = try {
            json.parseToJsonElement(body) as? JsonObject
        } catch (_: SerializationException) {
            null
        } ?: return protocolFailure("Response is not a JSON object")

        val ok = (envelope["ok"] as? JsonPrimitive)?.booleanOrNull
            ?: return protocolFailure("Response is missing a boolean ok field")
        return if (ok) {
            val data = envelope["data"]
                ?: return protocolFailure("Successful response is missing data")
            try {
                ApiResult.Success(
                    json.decodeFromJsonElement(dataDeserializer, data),
                    ApiResponseMetadata(statusCode, headers),
                )
            } catch (error: SerializationException) {
                protocolFailure(error.message ?: "Response data does not match its contract")
            }
        } else {
            val errorElement = envelope["error"]
                ?: return protocolFailure("Failed response is missing error")
            val error = try {
                json.decodeFromJsonElement(ApiErrorWire.serializer(), errorElement)
            } catch (serializationError: SerializationException) {
                return protocolFailure(serializationError.message ?: "Invalid error response")
            }
            ApiResult.Failure(ApiErrorMapper.fromHttp(statusCode, error))
        }
    }

    private fun protocolFailure(message: String): ApiResult.Failure = ApiResult.Failure(
        AppError(
            kind = AppErrorKind.ProtocolViolation,
            code = "PROTOCOL_VIOLATION",
            diagnosticMessage = message,
        ),
    )
}

internal object ApiErrorMapper {
    fun fromHttp(statusCode: Int, error: ApiErrorWire): AppError {
        val kind = when (statusCode) {
            400 -> AppErrorKind.InvalidRequest
            401 -> AppErrorKind.Unauthorized
            403 -> AppErrorKind.Forbidden
            404 -> AppErrorKind.NotFoundOrUnavailable
            409, 412 -> AppErrorKind.Conflict
            410 -> AppErrorKind.Gone
            413 -> AppErrorKind.PayloadTooLarge
            422 -> AppErrorKind.Validation
            429 -> AppErrorKind.RateLimited
            503 -> AppErrorKind.ServiceUnavailable
            in 500..599 -> AppErrorKind.ServerFailure
            else -> AppErrorKind.ProtocolViolation
        }
        return AppError(
            kind = kind,
            code = error.code?.takeIf(String::isNotBlank)
                ?: nestedCode(error.details)
                ?: fallbackCode(statusCode),
            diagnosticMessage = error.message,
            fieldErrors = if (statusCode == 422) extractFieldErrors(error.details) else emptyMap(),
            parameters = error.params.orEmpty().mapNotNull { (key, value) ->
                (value as? JsonPrimitive)?.contentOrNull?.let { key to it }
            }.toMap(),
            details = error.current ?: error.details,
        )
    }

    private fun nestedCode(details: JsonElement?): String? =
        ((details as? JsonObject)?.get("code") as? JsonPrimitive)
            ?.contentOrNull
            ?.takeIf(String::isNotBlank)

    private fun fallbackCode(statusCode: Int): String = when (statusCode) {
        400 -> "BAD_REQUEST"
        401 -> "UNAUTHORIZED"
        403 -> "FORBIDDEN"
        404 -> "NOT_FOUND"
        409, 412 -> "CONFLICT"
        410 -> "GONE"
        413 -> "PAYLOAD_TOO_LARGE"
        422 -> "VALIDATION"
        429 -> "RATE_LIMITED"
        503 -> "UNAVAILABLE"
        in 500..599 -> "SERVER_FAILURE"
        else -> "HTTP_$statusCode"
    }

    private fun extractFieldErrors(details: JsonElement?): Map<String, List<String>> {
        if (details is JsonArray) {
            return details.mapNotNull(::parseValidationEntry)
                .groupBy({ it.first }, { it.second })
        }
        val detailsObject = details as? JsonObject ?: return emptyMap()
        val fields = (detailsObject["fields"] ?: detailsObject["fieldErrors"])
        if (fields is JsonArray) {
            return fields.mapNotNull(::parseValidationEntry)
                .groupBy({ it.first }, { it.second })
        }
        val fieldObject = fields as? JsonObject ?: return emptyMap()
        return fieldObject.mapNotNull { (field, rawMessages) ->
            val messages = when (rawMessages) {
                is JsonArray -> rawMessages.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
                is JsonPrimitive -> listOfNotNull(rawMessages.contentOrNull)
                else -> emptyList()
            }
            field.takeIf { messages.isNotEmpty() }?.let { it to messages }
        }.toMap()
    }

    private fun parseValidationEntry(element: JsonElement): Pair<String, String>? {
        val entry = element as? JsonObject ?: return null
        val location = entry["loc"] as? JsonArray ?: return null
        val fieldPath = location.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
            .dropWhile { it == "body" || it == "query" || it == "path" }
            .joinToString(".")
            .takeIf(String::isNotBlank)
            ?: return null
        val stableCode = ((entry["type"] ?: entry["code"]) as? JsonPrimitive)
            ?.contentOrNull
            ?.takeIf(String::isNotBlank)
        val fallbackMessage = ((entry["message"] ?: entry["msg"]) as? JsonPrimitive)
            ?.contentOrNull
            ?.takeIf(String::isNotBlank)
        return fieldPath to (stableCode ?: fallbackMessage ?: return null)
    }
}
