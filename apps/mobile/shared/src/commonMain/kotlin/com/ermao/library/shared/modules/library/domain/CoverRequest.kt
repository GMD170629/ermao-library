package com.ermao.library.shared.modules.library.domain

/** Only server cover endpoints have thumbnail variants; publication previews keep their URL. */
fun smallCoverRequestPath(apiPath: String): String {
    val path = apiPath.substringBefore('?').substringBefore('#')
    if (!Regex("/api/(books/[^/]+(?:/source-nodes/[^/]+)?|resources/[^/]+)/cover").matches(path)) return apiPath
    val fragment = apiPath.substringAfter('#', "").let { if (apiPath.contains('#')) "#$it" else "" }
    val query = apiPath.substringBefore('#').substringAfter('?', "")
        .split('&').filter { it.isNotEmpty() && it.substringBefore('=') != "size" }
    return "$path?${(query + "size=small").joinToString("&")}$fragment"
}
