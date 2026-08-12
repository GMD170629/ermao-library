package com.ermao.library.shared.core.network

data class AppError(
    val kind: AppErrorKind,
    val code: String,
    val diagnosticMessage: String? = null,
    val fieldErrors: Map<String, List<String>> = emptyMap(),
    val parameters: Map<String, String> = emptyMap(),
)

enum class AppErrorKind {
    InvalidRequest,
    Unauthorized,
    Forbidden,
    NotFoundOrUnavailable,
    Conflict,
    Gone,
    PayloadTooLarge,
    Validation,
    RateLimited,
    ServiceUnavailable,
    ServerFailure,
    NetworkUnavailable,
    Timeout,
    TlsFailure,
    Cancelled,
    ProtocolViolation,
    StorageFailure,
}

sealed interface ApiResult<out T> {
    data class Success<T>(
        val value: T,
        val metadata: ApiResponseMetadata = ApiResponseMetadata(),
    ) : ApiResult<T>

    data class Failure(val error: AppError) : ApiResult<Nothing>
}

data class ApiResponseMetadata(
    val statusCode: Int = 200,
    val headers: Map<String, List<String>> = emptyMap(),
) {
    fun firstHeader(name: String): String? = headers.entries
        .firstOrNull { (key, _) -> key.equals(name, ignoreCase = true) }
        ?.value
        ?.firstOrNull()
}
