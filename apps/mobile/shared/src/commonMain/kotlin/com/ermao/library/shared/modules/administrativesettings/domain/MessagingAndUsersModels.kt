package com.ermao.library.shared.modules.administrativesettings.domain

data class KindleSettings(
    val recipientEmail: String,
    val smtpConfigured: Boolean,
    val senderEmail: String,
)

enum class KindleTaskStatus(val wireValue: String) {
    Queued("queued"),
    Sending("sending"),
    Sent("sent"),
    Failed("failed"),
    Cancelled("cancelled"),
    Unknown("unknown"),
}

data class KindleTaskFilter(
    val status: KindleTaskStatus? = null,
    val page: Int = 1,
    val pageSize: Int = 100,
)

data class KindleTask(
    val id: String,
    val workId: String?,
    val volumeId: String?,
    val fileId: String?,
    val bookTitle: String,
    val volumeTitle: String?,
    val fileName: String,
    val format: String,
    val mimeType: String,
    val sizeBytes: Long,
    val senderEmail: String?,
    val recipientEmail: String,
    val subject: String,
    val smtpHost: String?,
    val smtpPort: Int?,
    val smtpSecurity: String?,
    val smtpUsername: String?,
    val messageId: String?,
    val status: KindleTaskStatus,
    val attemptCount: Int,
    val nextAttemptAt: String?,
    val errorMessage: String?,
    val startedAt: String?,
    val sentAt: String?,
    val createdAt: String,
    val updatedAt: String,
    val canCancel: Boolean,
    val canRetry: Boolean,
    val canDelete: Boolean,
)

data class KindleTaskPage(
    val tasks: List<KindleTask>,
    val pageInfo: PageInfo,
)

enum class SmtpSecurity(val wireValue: String) {
    StartTls("starttls"),
    Ssl("ssl"),
    None("none"),
}

data class SmtpSettings(
    val host: String,
    val port: Int,
    val security: SmtpSecurity,
    val username: String,
    val fromEmail: String,
    val fromName: String,
    val maximumAttachmentMegabytes: Double?,
    val passwordConfigured: Boolean,
)

data class SmtpSettingsUpdate(
    val host: String,
    val port: Int,
    val security: SmtpSecurity,
    val username: String,
    val password: String?,
    val fromEmail: String,
    val fromName: String,
    val maximumAttachmentMegabytes: Double?,
    val clearPassword: Boolean,
)

data class EmailSettings(
    val smtp: SmtpSettings,
    val kindleRecipientEmail: String,
)

data class SmtpTestResult(
    val connected: Boolean,
)

enum class ManagedUserRole(val wireValue: String) {
    Admin("admin"),
    Member("member"),
}

enum class ManagedUserStatus(val wireValue: String) {
    Active("active"),
    Disabled("disabled"),
}

data class ManagedUser(
    val id: String,
    val name: String,
    val email: String,
    val role: ManagedUserRole,
    val status: ManagedUserStatus,
    val canManageSystem: Boolean,
    val canViewManualImports: Boolean,
    val libraryIds: List<String>,
    val locale: ManagedLocale,
    val authorizationVersion: Long,
    val avatarUrl: String?,
    val createdAt: String,
    val updatedAt: String,
)

data class CreateManagedUser(
    val name: String,
    val email: String,
    val password: String,
    val role: ManagedUserRole,
    val canManageSystem: Boolean,
    val canViewManualImports: Boolean,
    val libraryIds: List<String>,
    val locale: ManagedLocale,
)

data class UpdateManagedUser(
    val name: String,
    val email: String,
    val role: ManagedUserRole,
    val status: ManagedUserStatus,
    val canManageSystem: Boolean,
    val canViewManualImports: Boolean,
    val libraryIds: List<String>,
    val locale: ManagedLocale,
)

data class DeletedManagedUser(
    val userId: String,
    val deleted: Boolean,
)

data class ManagedPasswordChange(
    val passwordChanged: Boolean,
    val sessionsRevoked: Boolean,
)
