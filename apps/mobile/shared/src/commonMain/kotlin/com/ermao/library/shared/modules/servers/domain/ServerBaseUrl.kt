package com.ermao.library.shared.modules.servers.domain

class ServerBaseUrl private constructor(
    val value: String,
) {
    val origin: String
        get() {
            val authorityStart = value.indexOf("://") + 3
            val pathStart = value.indexOf('/', startIndex = authorityStart)
            return if (pathStart < 0) value else value.substring(0, pathStart)
        }

    val hostName: String
        get() {
            val authority = origin.substringAfter("://")
            return if (authority.startsWith('[')) {
                authority.substringBefore(']').removePrefix("[")
            } else {
                authority.substringBefore(':')
            }
        }

    val basePath: String
        get() = value.removePrefix(origin).ifEmpty { "/" }

    fun resolveApiPath(apiPath: String): String {
        require(apiPath.startsWith("/api/")) { "API path must start with /api/" }
        return value + apiPath
    }

    override fun equals(other: Any?): Boolean = other is ServerBaseUrl && value == other.value

    override fun hashCode(): Int = value.hashCode()

    override fun toString(): String = value

    companion object {
        fun parse(rawValue: String): ServerBaseUrlParseResult {
            val trimmed = rawValue.trim()
            if (trimmed.any { it.code < 0x20 || it.code == 0x7f }) {
                return ServerBaseUrlParseResult.Invalid(ServerBaseUrlError.InvalidFormat)
            }
            val match = URL_PATTERN.matchEntire(trimmed)
                ?: return ServerBaseUrlParseResult.Invalid(ServerBaseUrlError.InvalidFormat)
            val scheme = match.groupValues[1].lowercase()
            val authority = match.groupValues[2]
            val rawPath = match.groupValues[3]
            if (authority.contains('@')) {
                return ServerBaseUrlParseResult.Invalid(ServerBaseUrlError.UserInfoNotAllowed)
            }
            if (authority.any(Char::isWhitespace) || authority.any { it.code > 0x7f }) {
                return ServerBaseUrlParseResult.Invalid(ServerBaseUrlError.InvalidAuthority)
            }
            val normalizedAuthority = normalizeAuthority(scheme, authority)
                ?: return ServerBaseUrlParseResult.Invalid(ServerBaseUrlError.InvalidAuthority)
            val normalizedPath = normalizePath(rawPath)
                ?: return ServerBaseUrlParseResult.Invalid(ServerBaseUrlError.InvalidPath)
            return ServerBaseUrlParseResult.Valid(
                ServerBaseUrl("$scheme://$normalizedAuthority$normalizedPath"),
            )
        }

        private val URL_PATTERN = Regex(
            "^(https?)://([^/?#]+)(/[^?#]*)?$",
            RegexOption.IGNORE_CASE,
        )

        private fun normalizeAuthority(scheme: String, authority: String): String? {
            val (rawHost, rawPort) = if (authority.startsWith('[')) {
                val closing = authority.indexOf(']')
                if (closing <= 1) return null
                val remainder = authority.substring(closing + 1)
                val port = when {
                    remainder.isEmpty() -> null
                    remainder.startsWith(':') -> remainder.drop(1).takeIf(String::isNotEmpty)
                    else -> return null
                }
                val literal = authority.substring(1, closing)
                if (!IPV6_PATTERN.matches(literal)) return null
                "[${literal.lowercase()}]" to port
            } else {
                if (authority.count { it == ':' } > 1) return null
                val separator = authority.lastIndexOf(':')
                if (separator >= 0) authority.substring(0, separator) to authority.substring(separator + 1)
                else authority to null
            }
            if (rawHost.isEmpty()) return null
            if (!rawHost.startsWith('[') && !isValidAsciiHost(rawHost)) return null
            val port = rawPort?.toIntOrNull()?.takeIf { it in 1..65535 }
            if (rawPort != null && port == null) return null
            val normalizedPort = port?.takeUnless {
                (scheme == "http" && it == 80) || (scheme == "https" && it == 443)
            }
            return buildString {
                append(rawHost.lowercase())
                normalizedPort?.let { append(':').append(it) }
            }
        }

        private fun isValidAsciiHost(host: String): Boolean {
            if (host.length > 253 || host.endsWith('.')) return false
            return host.split('.').all { label ->
                label.isNotEmpty() &&
                    label.length <= 63 &&
                    label.first() != '-' &&
                    label.last() != '-' &&
                    label.all { it.isLetterOrDigit() || it == '-' }
            }
        }

        private fun normalizePath(path: String): String? {
            if (path.contains('\\') || path.any { it.code < 0x20 || it.code == 0x7f }) return null
            if (!hasValidPercentEscapes(path)) return null
            val segments = mutableListOf<String>()
            path.split('/').forEach { segment ->
                when (segment.lowercase()) {
                    ".", "%2e" -> Unit
                    "..", ".%2e", "%2e.", "%2e%2e" -> if (segments.isNotEmpty()) segments.removeAt(segments.lastIndex)
                    else -> if (segment.isNotEmpty()) segments += segment
                }
            }
            return segments.joinToString(separator = "/", prefix = "/")
                .trimEnd('/')
                .takeUnless(String::isEmpty)
                .orEmpty()
        }

        private fun hasValidPercentEscapes(value: String): Boolean {
            var index = 0
            while (index < value.length) {
                if (value[index] == '%') {
                    if (index + 2 >= value.length ||
                        !value[index + 1].isHexDigit() ||
                        !value[index + 2].isHexDigit()
                    ) return false
                    index += 3
                } else {
                    index += 1
                }
            }
            return true
        }

        private fun Char.isHexDigit(): Boolean =
            this in '0'..'9' || this in 'a'..'f' || this in 'A'..'F'

        private val IPV6_PATTERN = Regex("^[0-9A-Fa-f:.]+$")
    }
}

sealed interface ServerBaseUrlParseResult {
    data class Valid(val baseUrl: ServerBaseUrl) : ServerBaseUrlParseResult

    data class Invalid(val reason: ServerBaseUrlError) : ServerBaseUrlParseResult
}

enum class ServerBaseUrlError {
    InvalidFormat,
    InvalidAuthority,
    UserInfoNotAllowed,
    InvalidPath,
}
