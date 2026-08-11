package com.ermao.library.shared.modules.auth.domain

data class Authorization(
    val isAdmin: Boolean,
    val canManageSystem: Boolean,
    val allLibraryScopes: Boolean,
    val monitorFolderIds: Set<String>,
    val canViewManualImports: Boolean,
    val authorizationVersion: Long,
)
