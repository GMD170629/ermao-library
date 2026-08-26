package com.ermao.library.shared.modules.administrativesettings.infrastructure

import com.ermao.library.shared.modules.administrativesettings.domain.*
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull

internal class AdministrativeSettingsWireException(
    val stableCode: String,
) : IllegalArgumentException(stableCode)

private fun contract(code: String): Nothing = throw AdministrativeSettingsWireException(code)

private fun JsonElement.objectValue(code: String): JsonObject = this as? JsonObject ?: contract(code)
private fun JsonObject.requiredObject(name: String): JsonObject = get(name)?.objectValue("INVALID_$name") ?: contract("MISSING_$name")
private fun JsonObject.optionalObject(name: String): JsonObject? = when (val value = get(name)) {
    null, JsonNull -> null
    else -> value.objectValue("INVALID_$name")
}
private fun JsonObject.requiredArray(name: String): JsonArray = get(name) as? JsonArray ?: contract("INVALID_$name")
private fun JsonObject.requiredString(name: String): String =
    (get(name) as? JsonPrimitive)?.takeIf(JsonPrimitive::isString)?.contentOrNull ?: contract("INVALID_$name")
private fun JsonObject.optionalString(name: String): String? = when (val value = get(name)) {
    null, JsonNull -> null
    is JsonPrimitive -> value.takeIf(JsonPrimitive::isString)?.contentOrNull ?: contract("INVALID_$name")
    else -> contract("INVALID_$name")
}
private fun JsonObject.requiredNullableString(name: String): String? {
    if (!containsKey(name)) contract("MISSING_$name")
    return optionalString(name)
}
private fun JsonObject.requiredBoolean(name: String): Boolean =
    (get(name) as? JsonPrimitive)?.takeUnless(JsonPrimitive::isString)?.booleanOrNull
        ?: contract("INVALID_$name")
private fun JsonObject.optionalBoolean(name: String): Boolean? = when (val value = get(name)) {
    null, JsonNull -> null
    is JsonPrimitive -> value.takeUnless(JsonPrimitive::isString)?.booleanOrNull ?: contract("INVALID_$name")
    else -> contract("INVALID_$name")
}
private fun JsonObject.requiredInt(name: String): Int =
    (get(name) as? JsonPrimitive)?.takeUnless(JsonPrimitive::isString)?.intOrNull
        ?: contract("INVALID_$name")
private fun JsonObject.optionalInt(name: String): Int? = when (val value = get(name)) {
    null, JsonNull -> null
    is JsonPrimitive -> value.takeUnless(JsonPrimitive::isString)?.intOrNull ?: contract("INVALID_$name")
    else -> contract("INVALID_$name")
}
private fun JsonObject.requiredLong(name: String): Long =
    (get(name) as? JsonPrimitive)?.takeUnless(JsonPrimitive::isString)?.longOrNull
        ?: contract("INVALID_$name")
private fun JsonObject.optionalLong(name: String): Long? = when (val value = get(name)) {
    null, JsonNull -> null
    is JsonPrimitive -> value.takeUnless(JsonPrimitive::isString)?.longOrNull ?: contract("INVALID_$name")
    else -> contract("INVALID_$name")
}
private fun JsonObject.requiredNullableLong(name: String): Long? {
    if (!containsKey(name)) contract("MISSING_$name")
    return optionalLong(name)
}
private fun JsonObject.requiredDouble(name: String): Double =
    (get(name) as? JsonPrimitive)?.takeUnless(JsonPrimitive::isString)?.doubleOrNull
        ?: contract("INVALID_$name")
private fun JsonObject.optionalDouble(name: String): Double? = when (val value = get(name)) {
    null, JsonNull -> null
    is JsonPrimitive -> value.takeUnless(JsonPrimitive::isString)?.doubleOrNull ?: contract("INVALID_$name")
    else -> contract("INVALID_$name")
}
private fun JsonObject.requiredNullableDouble(name: String): Double? {
    if (!containsKey(name)) contract("MISSING_$name")
    return optionalDouble(name)
}
private fun JsonObject.requiredStringList(name: String): List<String> =
    requiredArray(name).mapIndexed { index, value ->
        (value as? JsonPrimitive)?.takeIf(JsonPrimitive::isString)?.contentOrNull ?: contract("INVALID_${name}_$index")
    }
private fun JsonObject.optionalStringList(name: String): List<String> =
    if (containsKey(name)) requiredStringList(name) else emptyList()
private fun JsonObject.stringIntMap(name: String): Map<String, Int> =
    requiredObject(name).mapValues { (key, value) ->
        (value as? JsonPrimitive)?.takeUnless(JsonPrimitive::isString)?.intOrNull
            ?: contract("INVALID_${name}_$key")
    }
private fun JsonObject.optionalStringIntMap(name: String): Map<String, Int> =
    optionalObject(name)?.mapValues { (key, value) ->
        (value as? JsonPrimitive)?.takeUnless(JsonPrimitive::isString)?.intOrNull
            ?: contract("INVALID_${name}_$key")
    }.orEmpty()
private fun JsonObject.requiredNullableStringIntMap(name: String): Map<String, Int> {
    if (!containsKey(name)) contract("MISSING_$name")
    return optionalStringIntMap(name)
}

private fun JsonObject.requiredNullableObject(name: String): JsonObject? {
    if (!containsKey(name)) contract("MISSING_$name")
    return optionalObject(name)
}

private fun JsonObject.validateRequiredArray(name: String) {
    requiredArray(name)
}

private fun JsonObject.expectKeys(vararg allowed: String): JsonObject {
    val unexpected = keys - allowed.toSet()
    if (unexpected.isNotEmpty()) contract("UNEXPECTED_${unexpected.sorted().first()}")
    return this
}

private fun <T> enumValue(value: String, values: Iterable<T>, wire: (T) -> String, code: String): T =
    values.firstOrNull { wire(it) == value } ?: contract(code)

internal fun JsonElement.toKindleSettings(): KindleSettings {
    val root = objectValue("INVALID_KINDLE_SETTINGS").expectKeys("kindle", "smtp")
    val kindle = root.requiredObject("kindle").expectKeys("email")
    val smtp = root.optionalObject("smtp")?.expectKeys("configured", "fromEmail")
    return KindleSettings(
        recipientEmail = kindle.requiredString("email"),
        smtpConfigured = smtp?.requiredBoolean("configured") ?: false,
        senderEmail = smtp?.requiredString("fromEmail").orEmpty(),
    )
}

internal fun JsonElement.toKindleTask(): KindleTask {
    val value = objectValue("INVALID_KINDLE_TASK").expectKeys(
        "id", "userId", "bookId", "resourceId", "assetId", "bookTitle", "resourceTitle", "fileName",
        "format", "mimeType", "sizeBytes", "senderEmail", "recipientEmail", "subject", "smtpHost",
        "smtpPort", "smtpSecurity", "smtpUsername", "messageId", "status", "attemptCount", "nextAttemptAt",
        "errorMessage", "startedAt", "sentAt", "createdAt", "updatedAt", "canCancel", "canRetry", "canDelete",
    )
    return KindleTask(
        id = value.requiredString("id"),
        bookId = value.optionalString("bookId"),
        resourceId = value.optionalString("resourceId"),
        assetId = value.optionalString("assetId"),
        bookTitle = value.requiredString("bookTitle"),
        resourceTitle = value.optionalString("resourceTitle"),
        fileName = value.requiredString("fileName"),
        format = value.requiredString("format"),
        mimeType = value.requiredString("mimeType"),
        sizeBytes = value.requiredLong("sizeBytes"),
        senderEmail = value.optionalString("senderEmail"),
        recipientEmail = value.requiredString("recipientEmail"),
        subject = value.requiredString("subject"),
        smtpHost = value.optionalString("smtpHost"),
        smtpPort = value.optionalInt("smtpPort"),
        smtpSecurity = value.optionalString("smtpSecurity"),
        smtpUsername = value.optionalString("smtpUsername"),
        messageId = value.optionalString("messageId"),
        status = enumValue(value.requiredString("status"), KindleTaskStatus.entries, KindleTaskStatus::wireValue, "UNSUPPORTED_KINDLE_STATUS"),
        attemptCount = value.requiredInt("attemptCount"),
        nextAttemptAt = value.optionalString("nextAttemptAt"),
        errorMessage = value.optionalString("errorMessage"),
        startedAt = value.optionalString("startedAt"),
        sentAt = value.optionalString("sentAt"),
        createdAt = value.requiredString("createdAt"),
        updatedAt = value.requiredString("updatedAt"),
        canCancel = value.requiredBoolean("canCancel"),
        canRetry = value.requiredBoolean("canRetry"),
        canDelete = value.requiredBoolean("canDelete"),
    )
}

internal fun JsonElement.toKindleTaskPayload(): KindleTask {
    val root = objectValue("INVALID_KINDLE_TASK_PAYLOAD").expectKeys("task", "alreadyQueued")
    root.optionalBoolean("alreadyQueued")
    return root.requiredObject("task").toKindleTask()
}

internal fun JsonElement.toKindleTaskPage(): KindleTaskPage {
    val root = objectValue("INVALID_KINDLE_TASKS").expectKeys("tasks", "total", "page", "pageSize", "totalPages")
    return KindleTaskPage(
        tasks = root.requiredArray("tasks").map(JsonElement::toKindleTask),
        pageInfo = root.toPageInfo(),
    )
}

private fun JsonObject.toPageInfo(): PageInfo = PageInfo(
    page = requiredInt("page"),
    pageSize = requiredInt("pageSize"),
    total = requiredInt("total"),
    totalPages = requiredInt("totalPages"),
)

internal fun JsonElement.toEmailSettings(): EmailSettings {
    val root = objectValue("INVALID_EMAIL_SETTINGS").expectKeys("smtp", "kindle")
    val smtp = root.requiredObject("smtp").expectKeys(
        "host", "port", "security", "username", "fromEmail", "fromName", "maxAttachmentMb", "passwordConfigured",
    )
    return EmailSettings(
        smtp = SmtpSettings(
            host = smtp.requiredString("host"),
            port = smtp.requiredInt("port"),
            security = enumValue(smtp.requiredString("security"), SmtpSecurity.entries, SmtpSecurity::wireValue, "UNSUPPORTED_SMTP_SECURITY"),
            username = smtp.requiredString("username"),
            fromEmail = smtp.requiredString("fromEmail"),
            fromName = smtp.requiredString("fromName"),
            maximumAttachmentMegabytes = smtp.requiredNullableDouble("maxAttachmentMb"),
            passwordConfigured = smtp.requiredBoolean("passwordConfigured"),
        ),
        kindleRecipientEmail = root.requiredObject("kindle").expectKeys("email").requiredString("email"),
    )
}

internal fun JsonElement.toSmtpTestResult(): SmtpTestResult =
    SmtpTestResult(objectValue("INVALID_SMTP_TEST").expectKeys("connected", "message").requiredBoolean("connected"))

internal fun JsonElement.toManagedUser(): ManagedUser {
    val user = objectValue("INVALID_ADMIN_USER").expectKeys(
        "id", "email", "name", "role", "status", "canManageSystem", "canViewManualImports", "authzVersion",
        "avatarUrl", "locale", "libraryIds", "authorization", "createdAt", "updatedAt",
    )
    return ManagedUser(
        id = user.requiredString("id"),
        name = user.requiredString("name"),
        email = user.requiredString("email"),
        role = enumValue(user.requiredString("role"), ManagedUserRole.entries, ManagedUserRole::wireValue, "UNSUPPORTED_USER_ROLE"),
        status = enumValue(user.requiredString("status"), ManagedUserStatus.entries, ManagedUserStatus::wireValue, "UNSUPPORTED_USER_STATUS"),
        canManageSystem = user.requiredBoolean("canManageSystem"),
        canViewManualImports = user.requiredBoolean("canViewManualImports"),
        libraryIds = user.requiredStringList("libraryIds"),
        locale = enumValue(user.requiredString("locale"), ManagedLocale.entries, ManagedLocale::wireValue, "UNSUPPORTED_LOCALE"),
        authorizationVersion = user.requiredLong("authzVersion"),
        avatarUrl = user.requiredNullableString("avatarUrl"),
        createdAt = user.requiredString("createdAt"),
        updatedAt = user.requiredString("updatedAt"),
    )
}

internal fun JsonElement.toManagedUserPayload(): ManagedUser =
    objectValue("INVALID_ADMIN_USER_PAYLOAD").expectKeys("user", "createdBy").requiredObject("user").toManagedUser()

internal fun JsonElement.toManagedUsers(): List<ManagedUser> =
    objectValue("INVALID_ADMIN_USERS").expectKeys("users").requiredArray("users").map(JsonElement::toManagedUser)

internal fun JsonElement.toDeletedManagedUser(): DeletedManagedUser {
    val root = objectValue("INVALID_DELETED_USER").expectKeys("deleted", "userId")
    return DeletedManagedUser(root.requiredString("userId"), root.requiredBoolean("deleted"))
}

internal fun JsonElement.toManagedPasswordChange(): ManagedPasswordChange {
    val root = objectValue("INVALID_PASSWORD_CHANGE").expectKeys("passwordChanged", "sessionsRevoked")
    return ManagedPasswordChange(
        passwordChanged = root.requiredBoolean("passwordChanged"),
        sessionsRevoked = root.requiredBoolean("sessionsRevoked"),
    )
}

internal fun JsonElement.toDeletedFlag(expectedId: String): Boolean {
    val root = objectValue("INVALID_DELETION").expectKeys("deleted", "id", "bookId")
    root.optionalString("bookId")
    if (root.requiredString("id") != expectedId) contract("DELETION_ID_MISMATCH")
    return root.requiredBoolean("deleted")
}

internal fun JsonElement.toLibrary(): Library {
    val library = objectValue("INVALID_LIBRARY").expectKeys(
        "id", "name", "rootPath", "organizationMode", "enabled", "ignorePatterns", "ignoreHidden",
        "minFileSizeBytes", "description", "createdAt", "updatedAt",
    )
    return Library(
        id = library.requiredString("id"),
        name = library.requiredString("name"),
        rootPath = library.requiredString("rootPath"),
        organizationMode = enumValue(library.requiredString("organizationMode"), LibraryOrganizationMode.entries, LibraryOrganizationMode::wireValue, "UNSUPPORTED_ORGANIZATION_MODE"),
        enabled = library.requiredBoolean("enabled"),
        ignorePatterns = library.optionalString("ignorePatterns"),
        ignoreHidden = library.requiredBoolean("ignoreHidden"),
        minimumFileSizeBytes = library.requiredLong("minFileSizeBytes"),
        description = library.requiredNullableString("description"),
        createdAt = library.requiredString("createdAt"),
        updatedAt = library.requiredString("updatedAt"),
    )
}

internal fun JsonElement.toLibraryPayload(): Library =
    objectValue("INVALID_LIBRARY_PAYLOAD").expectKeys("library").requiredObject("library").toLibrary()

internal fun JsonElement.toLibraries(): Libraries {
    val root = objectValue("INVALID_LIBRARIES").expectKeys(
        "libraries", "lastUploadTargetPath", "lastDownloadTargetPath",
    )
    return Libraries(
        libraries = root.requiredArray("libraries").map(JsonElement::toLibrary),
        lastUploadTargetPath = root.requiredNullableString("lastUploadTargetPath"),
        lastDownloadTargetPath = root.requiredNullableString("lastDownloadTargetPath"),
    )
}

internal fun JsonElement.toDirectoryNode(): DirectoryNode {
    val node = objectValue("INVALID_DIRECTORY_PAYLOAD").expectKeys("node").requiredObject("node")
        .expectKeys("name", "path", "readable", "error", "children")
    return DirectoryNode(
        name = node.requiredString("name"),
        path = node.requiredString("path"),
        readable = node.requiredBoolean("readable"),
        error = node.requiredNullableString("error"),
        children = node.requiredArray("children").map { item ->
            val child = item.objectValue("INVALID_DIRECTORY_CHILD").expectKeys("name", "path", "readable")
            DirectoryChild(
                name = child.requiredString("name"),
                path = child.requiredString("path"),
                readable = child.requiredBoolean("readable"),
            )
        },
    )
}

internal fun JsonElement.toImportTask(): ImportTask {
    val task = objectValue("INVALID_IMPORT_TASK").expectKeys(
        "id", "kind", "libraryId", "libraryName", "resourceId", "resourceTitle", "sourceNodeId", "sourceName",
        "sourceRelativePath", "bookTitle", "role", "state", "errorSummary",
        "createdAt", "startedAt", "finishedAt",
    )
    return ImportTask(
        id = task.requiredString("id"),
        kind = task.requiredString("kind"),
        libraryId = task.requiredString("libraryId"),
        libraryName = task.requiredNullableString("libraryName"),
        resourceId = task.requiredNullableString("resourceId"),
        resourceTitle = task.requiredNullableString("resourceTitle"),
        sourceNodeId = task.requiredNullableString("sourceNodeId"),
        sourceName = task.requiredNullableString("sourceName"),
        sourceRelativePath = task.requiredNullableString("sourceRelativePath"),
        bookTitle = task.requiredNullableString("bookTitle"),
        role = task.requiredNullableString("role"),
        state = enumValue(task.requiredString("state"), ImportTaskState.entries, ImportTaskState::wireValue, "UNSUPPORTED_IMPORT_STATE"),
        errorSummary = task.requiredNullableString("errorSummary"),
        createdAt = task.requiredString("createdAt"),
        startedAt = task.requiredNullableString("startedAt"),
        finishedAt = task.requiredNullableString("finishedAt"),
    )
}

internal fun JsonElement.toImportTaskPage(): ImportTaskPage {
    val root = objectValue("INVALID_IMPORT_TASKS").expectKeys("tasks", "page", "pageSize", "total", "totalPages", "completed", "failed")
    return ImportTaskPage(
        tasks = root.requiredArray("tasks").map(JsonElement::toImportTask),
        pageInfo = root.toPageInfo(),
        completed = root.requiredInt("completed"),
        failed = root.requiredInt("failed"),
    )
}

internal fun JsonElement.toImportTaskPayload(): ImportTask =
    objectValue("INVALID_IMPORT_TASK_PAYLOAD").expectKeys("task").requiredObject("task").toImportTask()

internal fun JsonElement.toImportTaskLogPage(): ImportTaskLogPage {
    val root = objectValue("INVALID_IMPORT_LOGS").expectKeys("logs", "page", "pageSize", "total", "totalPages")
    return ImportTaskLogPage(
        logs = root.requiredArray("logs").map { element ->
            val log = element.objectValue("INVALID_IMPORT_LOG").expectKeys("id", "level", "message", "createdAt")
            ImportTaskLog(
                id = log.requiredString("id"),
                level = log.requiredString("level"),
                message = log.requiredString("message"),
                createdAt = log.requiredNullableString("createdAt"),
            )
        },
        pageInfo = root.toPageInfo(),
    )
}

internal fun JsonElement.toImportTaskDeletion(): ImportTaskDeletion {
    val deletion = objectValue("INVALID_IMPORT_DELETION").expectKeys(
        "deleted", "id",
    )
    return ImportTaskDeletion(
        id = deletion.requiredString("id"),
        deleted = deletion.requiredBoolean("deleted"),
    )
}

internal fun JsonElement.toDeletedCount(): Int =
    objectValue("INVALID_DELETED_COUNT").expectKeys("deleted").requiredInt("deleted")

internal fun JsonElement.toImportScanJob(): ImportScanJob {
    val job = objectValue("INVALID_SCAN_JOB").expectKeys(
        "id", "libraryId", "rootPath", "trigger", "status", "directoriesScanned", "filesScanned",
        "candidatesFound", "queuedCount", "skippedCount", "errorCount", "ignoredReasonCounts", "errorSamples",
        "restartCount", "startedAt", "heartbeatAt", "finishedAt", "createdAt", "updatedAt",
    )
    job.requiredObject("ignoredReasonCounts")
    job.validateRequiredArray("errorSamples")
    return ImportScanJob(
        id = job.requiredString("id"),
        libraryId = job.requiredNullableString("libraryId"),
        rootPath = job.requiredString("rootPath"),
        trigger = job.requiredString("trigger"),
        status = enumValue(job.requiredString("status"), ImportScanStatus.entries, ImportScanStatus::wireValue, "UNSUPPORTED_SCAN_STATUS"),
        directoriesScanned = job.requiredInt("directoriesScanned"),
        filesScanned = job.requiredInt("filesScanned"),
        candidatesFound = job.requiredInt("candidatesFound"),
        queuedCount = job.requiredInt("queuedCount"),
        skippedCount = job.requiredInt("skippedCount"),
        errorCount = job.requiredInt("errorCount"),
        restartCount = job.requiredInt("restartCount"),
        startedAt = job.requiredNullableString("startedAt"),
        heartbeatAt = job.requiredNullableString("heartbeatAt"),
        finishedAt = job.requiredNullableString("finishedAt"),
        createdAt = job.requiredString("createdAt"),
        updatedAt = job.requiredString("updatedAt"),
    )
}

internal fun JsonElement.toImportScanJobPayload(): ImportScanJob =
    objectValue("INVALID_SCAN_JOB_PAYLOAD").expectKeys("job", "created").requiredObject("job").toImportScanJob()

internal fun JsonElement.toImportScanJobs(): List<ImportScanJob> =
    objectValue("INVALID_SCAN_JOBS").expectKeys("jobs").requiredArray("jobs").map(JsonElement::toImportScanJob)

internal fun JsonElement.toImportRescanRequest(): ImportRescanRequest {
    val root = objectValue("INVALID_RESCAN_PAYLOAD").expectKeys("requestedAt", "jobs")
    return ImportRescanRequest(
        requestedAt = root.requiredString("requestedAt"),
        jobs = root.requiredArray("jobs").map(JsonElement::toImportScanJob),
    )
}

private fun JsonObject.toOrganizeBook(): OrganizeBookSummary = OrganizeBookSummary(
    id = requiredString("id"),
    title = requiredString("title"),
    author = requiredNullableString("author"),
)

internal fun JsonElement.toOrganizeJob(): OrganizeJob {
    val job = objectValue("INVALID_ORGANIZE_JOB").expectKeys(
        "id", "runId", "resourceId", "trigger", "status", "statusCategory", "issueCodes",
        "reasonCodes", "summary", "errorSummary", "metadataLookupStatus", "metadataLookupSource",
        "metadataLookupProviders", "metadataSources", "metadataLookupError", "providerExecutions", "metadataWriteback",
        "startedAt", "finishedAt", "createdAt", "updatedAt", "book",
    )
    job.optionalString("runId")
    job.optionalString("resourceId")
    job.optionalString("summary")
    job.optionalString("errorSummary")
    job.optionalString("metadataLookupStatus")
    job.optionalString("metadataLookupSource")
    job.optionalString("metadataLookupError")
    job.optionalString("startedAt")
    job.optionalString("finishedAt")
    job.optionalString("status")
    job.optionalStringList("metadataLookupProviders")
    if (job.containsKey("providerExecutions")) job.validateRequiredArray("providerExecutions")
    return OrganizeJob(
        id = job.requiredString("id"),
        trigger = job.requiredString("trigger"),
        statusCategory = enumValue(job.requiredString("statusCategory"), OrganizeStatusCategory.entries, OrganizeStatusCategory::wireValue, "UNSUPPORTED_ORGANIZE_STATUS"),
        issueCodes = job.requiredStringList("issueCodes"),
        reasonCodes = job.requiredStringList("reasonCodes"),
        metadataSources = job.requiredStringList("metadataSources"),
        createdAt = job.requiredNullableString("createdAt"),
        updatedAt = job.requiredNullableString("updatedAt"),
        resourceId = job.optionalString("resourceId"),
        book = job.requiredObject("book").toOrganizeBook(),
    )
}

internal fun JsonElement.toOrganizeJobPayload(): OrganizeJob =
    objectValue("INVALID_ORGANIZE_JOB_PAYLOAD").expectKeys("job").requiredObject("job").toOrganizeJob()

internal fun JsonElement.toOrganizeJobPage(): OrganizeJobPage {
    val root = objectValue("INVALID_ORGANIZE_JOBS").expectKeys(
        "jobs", "page", "pageSize", "total", "totalPages", "statusCounts", "providerNames",
    )
    val counts = root.requiredObject("statusCounts")
    return OrganizeJobPage(
        jobs = root.requiredArray("jobs").map(JsonElement::toOrganizeJob),
        pageInfo = root.toPageInfo(),
        statusCounts = OrganizeStatusCategory.entries.associateWith { status ->
            counts.requiredInt(status.wireValue)
        },
        providerNames = root.requiredObject("providerNames").mapValues { (key, value) ->
            (value as? JsonPrimitive)?.takeIf(JsonPrimitive::isString)?.contentOrNull
                ?: contract("INVALID_PROVIDER_NAME_$key")
        },
    )
}

internal fun JsonElement.toPendingOrganizeJobs(): PendingOrganizeJobs {
    val root = objectValue("INVALID_PENDING_ORGANIZE_JOBS").expectKeys("jobs", "books", "total")
    return PendingOrganizeJobs(
        jobs = root.requiredArray("jobs").map(JsonElement::toOrganizeJob),
        books = root.requiredArray("books").map { it.objectValue("INVALID_ORGANIZE_BOOK").toOrganizeBook() },
        total = root.requiredInt("total"),
    )
}

internal fun JsonElement.toOrganizeRuns(): List<OrganizeRun> =
    objectValue("INVALID_ORGANIZE_RUNS").expectKeys("runs").requiredArray("runs").map { element ->
        val run = element.objectValue("INVALID_ORGANIZE_RUN").expectKeys(
            "id", "trigger", "scope", "status", "queuedCount", "completedCount", "reviewCount", "failedCount",
            "startedAt", "finishedAt", "createdAt", "updatedAt",
        )
        val scope = run.requiredObject("scope").expectKeys("bookIds", "rules")
        val rules = scope.requiredObject("rules").expectKeys("unrecognized", "missingMetadata")
        OrganizeRun(
            id = run.requiredString("id"),
            trigger = run.requiredString("trigger"),
            status = run.requiredString("status"),
            scope = OrganizeRunScope(
                bookIds = scope.requiredStringList("bookIds"),
                rules = OrganizeRules(
                    unrecognized = rules.requiredBoolean("unrecognized"),
                    missingMetadata = rules.requiredBoolean("missingMetadata"),
                ),
            ),
            queuedCount = run.requiredInt("queuedCount"),
            completedCount = run.requiredInt("completedCount"),
            reviewCount = run.requiredInt("reviewCount"),
            failedCount = run.requiredInt("failedCount"),
            startedAt = run.requiredNullableString("startedAt"),
            finishedAt = run.requiredNullableString("finishedAt"),
            createdAt = run.requiredNullableString("createdAt"),
            updatedAt = run.requiredNullableString("updatedAt"),
        )
    }

internal fun JsonElement.toOrganizeCandidates(): OrganizeCandidates {
    val candidates = objectValue("INVALID_CANDIDATES_PAYLOAD").expectKeys("candidates").requiredObject("candidates")
        .expectKeys("total", "reasonCounts", "books")
    return OrganizeCandidates(
        total = candidates.requiredInt("total"),
        reasonCounts = candidates.stringIntMap("reasonCounts"),
        books = candidates.requiredArray("books").map { element ->
            val work = element.objectValue("INVALID_CANDIDATE").expectKeys(
                "id", "title", "author", "coverPath", "metadataQuality", "reasonCodes", "createdAt",
            )
            OrganizeCandidate(
                id = work.requiredString("id"),
                title = work.requiredNullableString("title"),
                author = work.requiredNullableString("author"),
                coverPath = work.requiredNullableString("coverPath"),
                metadataQuality = work.requiredInt("metadataQuality"),
                reasonCodes = work.requiredStringList("reasonCodes"),
                createdAt = work.requiredNullableString("createdAt"),
            )
        },
    )
}

internal fun JsonElement.toOrganizePolicyPayload(): OrganizePolicy =
    objectValue("INVALID_POLICY_PAYLOAD").expectKeys("policy").requiredObject("policy").toOrganizePolicy()

internal fun JsonElement.toOpfQueueStatus(): OpfQueueStatus {
    val queue = objectValue("INVALID_OPF_PAYLOAD").expectKeys("queue").requiredObject("queue")
        .expectKeys("pendingTargets", "pendingPreparations", "capacity", "utilization")
    return OpfQueueStatus(
        pendingTargets = queue.requiredInt("pendingTargets"),
        pendingPreparations = queue.requiredInt("pendingPreparations"),
        capacity = queue.requiredInt("capacity"),
        utilization = queue.requiredDouble("utilization"),
    )
}

internal fun JsonElement.toLibraryOperations(): List<LibraryOperation> =
    objectValue("INVALID_LIBRARY_OPERATIONS").expectKeys("operations").requiredArray("operations").map(JsonElement::toLibraryOperation)

internal fun JsonElement.toUndoOperation(): LibraryOperation =
    objectValue("INVALID_UNDO_OPERATION").expectKeys("operation", "restored").requiredObject("operation").toLibraryOperation()

internal fun JsonElement.toCategoryPage(): CategoryPage {
    val root = objectValue("INVALID_CATEGORIES").expectKeys("facets", "page", "pageSize", "total", "totalPages")
    return CategoryPage(
        categories = root.requiredArray("facets").map(JsonElement::toLibraryCategory),
        pageInfo = root.toPageInfo(),
    )
}

internal fun JsonElement.toCategoryOperation(expectedDeletedId: String? = null): LibraryOperation {
    val root = objectValue("INVALID_CATEGORY_OPERATION").expectKeys(
        "facetId", "name", "kind", "affectedBookCount", "targetId", "mergedIds", "deleted", "operation",
    )
    expectedDeletedId?.let { expectedId ->
        if (root.requiredString("facetId") != expectedId) contract("CATEGORY_ID_MISMATCH")
        if (!root.requiredBoolean("deleted")) contract("CATEGORY_NOT_DELETED")
    }
    return root.requiredObject("operation").toLibraryOperation()
}

internal fun JsonElement.toOrganizePolicy(): OrganizePolicy {
    val policy = objectValue("INVALID_ORGANIZE_POLICY").expectKeys(
        "id", "enabled", "scheduleMode", "intervalMinutes", "autoRunOnNew", "autoRunOnNewSince", "rules",
        "writeMetadataToFiles", "preferLocalMetadata", "localMetadataPriority", "lastScheduledAt", "nextRunAt", "updatedAt",
    )
    val rules = policy.requiredObject("rules").expectKeys("unrecognized", "missingMetadata")
    return OrganizePolicy(
        id = policy.requiredString("id"),
        enabled = policy.requiredBoolean("enabled"),
        scheduleMode = enumValue(policy.requiredString("scheduleMode"), OrganizeScheduleMode.entries, OrganizeScheduleMode::wireValue, "UNSUPPORTED_SCHEDULE_MODE"),
        intervalMinutes = policy.requiredInt("intervalMinutes"),
        autoRunOnNew = policy.requiredBoolean("autoRunOnNew"),
        autoRunOnNewSince = policy.requiredNullableString("autoRunOnNewSince"),
        rules = OrganizeRules(rules.requiredBoolean("unrecognized"), rules.requiredBoolean("missingMetadata")),
        writeMetadataToFiles = policy.requiredBoolean("writeMetadataToFiles"),
        preferLocalMetadata = policy.requiredBoolean("preferLocalMetadata"),
        localMetadataPriority = policy.requiredStringList("localMetadataPriority").map {
            enumValue(it, LocalMetadataSource.entries, LocalMetadataSource::wireValue, "UNSUPPORTED_LOCAL_METADATA_SOURCE")
        },
        lastScheduledAt = policy.requiredNullableString("lastScheduledAt"),
        nextRunAt = policy.requiredNullableString("nextRunAt"),
        updatedAt = policy.requiredString("updatedAt"),
    )
}

internal fun JsonElement.toLibraryOperation(): LibraryOperation {
    val operation = objectValue("INVALID_LIBRARY_OPERATION").expectKeys(
        "id", "action", "status", "summary", "expiresAt", "undoAvailable",
    )
    return LibraryOperation(
        id = operation.requiredString("id"),
        action = operation.requiredString("action"),
        status = operation.requiredString("status"),
        summary = operation.requiredString("summary"),
        expiresAt = operation.optionalString("expiresAt"),
        undoAvailable = operation.requiredBoolean("undoAvailable"),
    )
}

internal fun JsonElement.toLibraryCategory(): LibraryCategory {
    val category = objectValue("INVALID_CATEGORY").expectKeys(
        "id", "kind", "name", "normalizedName", "aliases", "createdAt", "updatedAt", "bookCount",
    )
    return LibraryCategory(
        id = category.requiredString("id"),
        kind = enumValue(category.requiredString("kind"), CategoryKind.entries, CategoryKind::wireValue, "UNSUPPORTED_CATEGORY_KIND"),
        name = category.requiredString("name"),
        normalizedName = category.requiredString("normalizedName"),
        aliases = category.requiredStringList("aliases"),
        bookCount = category.requiredInt("bookCount"),
        createdAt = category.optionalString("createdAt"),
        updatedAt = category.optionalString("updatedAt"),
    )
}

private fun JsonElement.toProviderValue(): ProviderSettingValue = when (this) {
    JsonNull -> ProviderSettingValue.Empty
    is JsonArray -> ProviderSettingValue.TextList(mapIndexed { index, item ->
        (item as? JsonPrimitive)?.takeIf(JsonPrimitive::isString)?.contentOrNull
            ?: contract("INVALID_PROVIDER_LIST_$index")
    })
    is JsonPrimitive -> takeIf(JsonPrimitive::isString)?.contentOrNull?.let(ProviderSettingValue::Text)
        ?: booleanOrNull?.let(ProviderSettingValue::Toggle)
        ?: longOrNull?.let(ProviderSettingValue::Integer)
        ?: doubleOrNull?.let(ProviderSettingValue::Decimal)
        ?: contract("INVALID_PROVIDER_VALUE")
    else -> contract("INVALID_PROVIDER_VALUE")
}

internal fun JsonElement.toMetadataProvider(): MetadataProvider {
    val provider = objectValue("INVALID_METADATA_PROVIDER").expectKeys(
        "id", "sourceId", "name", "version", "description", "mode", "fields", "capabilities",
        "automaticRateLimit", "configFields", "config", "configuredSecrets", "enabled", "priority", "lastTestAt",
        "lastTestStatus", "lastError",
    )
    val rateLimit = provider.requiredNullableObject("automaticRateLimit")?.expectKeys("requests", "periodSeconds")
    return MetadataProvider(
        id = provider.requiredString("id"),
        sourceId = provider.requiredNullableString("sourceId"),
        name = provider.requiredString("name"),
        version = provider.requiredString("version"),
        description = provider.requiredString("description"),
        mode = provider.requiredString("mode"),
        fields = provider.requiredStringList("fields"),
        capabilities = provider.requiredStringList("capabilities"),
        automaticRateLimit = rateLimit?.let { ProviderAutomaticRateLimit(it.requiredInt("requests"), it.requiredDouble("periodSeconds")) },
        configFields = provider.requiredArray("configFields").map { element ->
            val field = element.objectValue("INVALID_PROVIDER_CONFIG_FIELD").expectKeys(
                "key", "label", "kind", "required", "secret", "placeholder", "help", "default",
            )
            ProviderConfigField(
                key = field.requiredString("key"),
                label = field.requiredString("label"),
                kind = field.requiredString("kind"),
                required = field.requiredBoolean("required"),
                secret = field.requiredBoolean("secret"),
                placeholder = field.requiredNullableString("placeholder"),
                help = field.requiredNullableString("help"),
                defaultValue = field["default"]?.toProviderValue() ?: contract("MISSING_PROVIDER_DEFAULT"),
            )
        },
        config = provider.requiredObject("config").mapValues { (_, value) -> value.toProviderValue() },
        configuredSecrets = provider.requiredObject("configuredSecrets").mapValues { (key, value) ->
            (value as? JsonPrimitive)?.takeUnless(JsonPrimitive::isString)?.booleanOrNull
                ?: contract("INVALID_PROVIDER_SECRET_$key")
        },
        enabled = provider.requiredBoolean("enabled"),
        priority = provider.requiredInt("priority"),
        lastTestAt = provider.requiredNullableString("lastTestAt"),
        lastTestStatus = provider.requiredNullableString("lastTestStatus"),
        lastError = provider.requiredNullableString("lastError"),
    )
}

internal fun JsonElement.toMetadataProviders(): MetadataProviders {
    val root = objectValue("INVALID_METADATA_PROVIDERS").expectKeys("providers")
    return MetadataProviders(providers = root.requiredArray("providers").map(JsonElement::toMetadataProvider))
}

internal fun JsonElement.toMetadataProviderPayload(): MetadataProvider =
    objectValue("INVALID_PROVIDER_PAYLOAD").expectKeys("provider").requiredObject("provider").toMetadataProvider()

internal fun JsonElement.toProviderTestResult(): ProviderTestResult {
    val root = objectValue("INVALID_PROVIDER_TEST").expectKeys("result", "provider")
    val result = root.requiredObject("result").expectKeys("ok", "message")
    return ProviderTestResult(
        ok = result.requiredBoolean("ok"),
        provider = root.requiredObject("provider").toMetadataProvider(),
    )
}

internal fun JsonElement.toBackup(): BackupArchive {
    val backup = objectValue("INVALID_BACKUP").expectKeys(
        "id", "kind", "name", "filename", "sizeBytes", "createdAt", "counts",
    )
    return BackupArchive(
        id = backup.requiredString("id"),
        kind = backup.optionalString("kind"),
        name = backup.requiredString("name"),
        fileName = backup.optionalString("filename"),
        sizeBytes = backup.requiredLong("sizeBytes"),
        createdAt = backup.requiredString("createdAt"),
        counts = backup.optionalStringIntMap("counts"),
    )
}

internal fun JsonElement.toBackupPayload(): BackupArchive =
    objectValue("INVALID_BACKUP_PAYLOAD").expectKeys("backup").requiredObject("backup").toBackup()

internal fun JsonElement.toBackups(): List<BackupArchive> =
    objectValue("INVALID_BACKUPS").expectKeys("backups").requiredArray("backups").map(JsonElement::toBackup)

internal fun JsonElement.toBackupRestore(): BackupRestoreResult {
    val root = objectValue("INVALID_BACKUP_RESTORE").expectKeys(
        "id", "restored", "restoredAt", "counts", "restoredCounts", "actualCounts",
    )
    root.requiredNullableStringIntMap("counts")
    return BackupRestoreResult(
        id = root.requiredString("id"),
        restored = root.requiredBoolean("restored"),
        restoredAt = root.requiredString("restoredAt"),
        restoredCounts = root.stringIntMap("restoredCounts"),
        actualCounts = root.stringIntMap("actualCounts"),
    )
}

internal fun JsonElement.toOpdsSettings(): OpdsSettings {
    val root = objectValue("INVALID_OPDS_SETTINGS").expectKeys(
        "enabled", "configured", "publicBaseUrl", "catalogUrl",
    )
    return OpdsSettings(
        enabled = root.requiredBoolean("enabled"),
        configured = root.requiredBoolean("configured"),
        publicBaseUrl = root.requiredNullableString("publicBaseUrl"),
        catalogUrl = root.requiredNullableString("catalogUrl"),
    )
}

private fun JsonElement.stableText(): String = when (this) {
    JsonNull -> "null"
    is JsonPrimitive -> content
    else -> toString()
}

private fun JsonElement.toEventMetadataValue(): EventMetadataValue = when (this) {
    JsonNull -> EventMetadataValue.Empty
    is JsonArray -> EventMetadataValue.ListValue(map(JsonElement::toEventMetadataValue))
    is JsonObject -> EventMetadataValue.ObjectValue(mapValues { (_, value) -> value.toEventMetadataValue() })
    is JsonPrimitive -> if (isString) {
        EventMetadataValue.Text(content)
    } else {
        booleanOrNull?.let(EventMetadataValue::Toggle)
            ?: longOrNull?.let(EventMetadataValue::Integer)
            ?: doubleOrNull?.let(EventMetadataValue::Decimal)
            ?: contract("INVALID_EVENT_METADATA_VALUE")
    }
}

private fun JsonObject.toHealthRun(): HealthRun {
    expectKeys("runId", "status", "version", "startedAt", "finishedAt", "groups", "items", "summary", "created")
    val summary = requiredObject("summary").expectKeys("total", "completed", "ok", "warning", "error", "skipped")
    return HealthRun(
        runId = requiredString("runId"),
        status = enumValue(requiredString("status"), HealthRunStatus.entries, HealthRunStatus::wireValue, "UNSUPPORTED_HEALTH_RUN_STATUS"),
        version = requiredLong("version"),
        startedAt = requiredLong("startedAt"),
        finishedAt = requiredNullableLong("finishedAt"),
        groups = requiredArray("groups").map { item ->
            val group = item.objectValue("INVALID_HEALTH_GROUP").expectKeys("id", "labelCode")
            HealthRunGroup(group.requiredString("id"), group.requiredString("labelCode"))
        },
        items = requiredArray("items").map { item ->
            val check = item.objectValue("INVALID_HEALTH_ITEM").expectKeys(
                "id", "group", "labelCode", "kind", "options", "status", "messageCode", "messageParams", "details",
                "startedAt", "finishedAt", "durationMs",
            )
            check.requiredObject("options")
            check.requiredObject("messageParams")
            HealthRunItem(
                id = check.requiredString("id"),
                group = check.requiredString("group"),
                labelCode = check.requiredString("labelCode"),
                kind = check.requiredString("kind"),
                status = enumValue(check.requiredString("status"), HealthCheckStatus.entries, HealthCheckStatus::wireValue, "UNSUPPORTED_HEALTH_STATUS"),
                messageCode = check.requiredString("messageCode"),
                detailCodes = check.requiredObject("details").mapValues { (_, value) -> value.stableText() },
                startedAt = check.requiredNullableLong("startedAt"),
                finishedAt = check.requiredNullableLong("finishedAt"),
                durationMilliseconds = check.requiredNullableLong("durationMs"),
            )
        },
        summary = HealthRunSummary(
            total = summary.requiredInt("total"),
            completed = summary.requiredInt("completed"),
            ok = summary.requiredInt("ok"),
            warning = summary.requiredInt("warning"),
            error = summary.requiredInt("error"),
            skipped = summary.requiredInt("skipped"),
        ),
    )
}

internal fun JsonElement.toHealthRun(): HealthRun =
    objectValue("INVALID_HEALTH_PAYLOAD").expectKeys("run", "created").requiredObject("run").toHealthRun()

internal fun JsonElement.toEventStorage(): EventStorage {
    val storage = objectValue("INVALID_EVENT_STORAGE").expectKeys("deleted", "sizeBytes", "maxBytes", "lastPrunedAt")
    return EventStorage(
        sizeBytes = storage.requiredLong("sizeBytes"),
        maximumBytes = storage.requiredLong("maxBytes"),
        lastPrunedAt = if (storage.containsKey("deleted")) null else storage.requiredNullableString("lastPrunedAt"),
    )
}

internal fun JsonElement.toManagementEventPage(): ManagementEventPage {
    val root = objectValue("INVALID_MANAGEMENT_EVENTS").expectKeys(
        "events", "page", "pageSize", "total", "totalPages", "storage", "facets",
    )
    val facets = root.requiredObject("facets").expectKeys("sources", "levels")
    return ManagementEventPage(
        events = root.requiredArray("events").map { element ->
            val event = element.objectValue("INVALID_MANAGEMENT_EVENT").expectKeys(
                "id", "level", "source", "actorType", "actorId", "action", "targetType", "targetId", "message", "metadata", "createdAt",
            )
            ManagementEvent(
                id = event.requiredString("id"),
                level = event.requiredString("level"),
                source = event.requiredString("source"),
                actorType = event.requiredString("actorType"),
                actorId = event.requiredNullableString("actorId"),
                action = event.requiredString("action"),
                targetType = event.requiredNullableString("targetType"),
                targetId = event.requiredNullableString("targetId"),
                message = event.requiredString("message"),
                metadata = event.requiredObject("metadata").mapValues { (_, value) -> value.toEventMetadataValue() },
                createdAt = event.requiredNullableString("createdAt"),
            )
        },
        pageInfo = root.toPageInfo(),
        storage = root.requiredObject("storage").toEventStorage(),
        sources = facets.requiredArray("sources").map { item ->
            val facet = item.objectValue("INVALID_SOURCE_FACET").expectKeys("source", "count")
            EventFacet(facet.requiredString("source"), facet.requiredInt("count"))
        },
        levels = facets.requiredArray("levels").map { item ->
            val facet = item.objectValue("INVALID_LEVEL_FACET").expectKeys("level", "count")
            EventFacet(facet.requiredString("level"), facet.requiredInt("count"))
        },
    )
}

internal fun JsonElement.toClearedManagementEvents(): ClearedManagementEvents {
    val root = objectValue("INVALID_CLEARED_EVENTS").expectKeys("deleted", "storage")
    return ClearedManagementEvents(
        deleted = root.requiredInt("deleted"),
        storage = root.optionalObject("storage")?.toEventStorage(),
    )
}

internal fun JsonElement.toLogSettings(): LogSettings {
    val root = objectValue("INVALID_LOG_SETTINGS").expectKeys("storage", "minBytes", "maxBytes")
    return LogSettings(
        storage = root.requiredObject("storage").toEventStorage(),
        minimumBytes = root.optionalLong("minBytes"),
        maximumBytes = root.optionalLong("maxBytes"),
    )
}

internal fun JsonElement.toSettingValueMap(): Map<String, SettingValue> =
    objectValue("INVALID_SETTINGS").mapValues { (_, value) ->
        when (value) {
            JsonNull -> SettingValue.Empty
            is JsonArray -> SettingValue.TextList(value.mapIndexed { index, item ->
                (item as? JsonPrimitive)?.takeIf(JsonPrimitive::isString)?.contentOrNull
                    ?: contract("INVALID_SETTING_LIST_$index")
            })
            is JsonPrimitive -> value.takeIf(JsonPrimitive::isString)?.contentOrNull?.let(SettingValue::Text)
                ?: value.booleanOrNull?.let(SettingValue::Toggle)
                ?: value.longOrNull?.let(SettingValue::Integer)
                ?: value.doubleOrNull?.let(SettingValue::Decimal)
                ?: contract("INVALID_SETTING")
            else -> contract("INVALID_SETTING")
        }
    }

internal fun JsonElement.toSystemSettings(): Map<String, SettingValue> =
    objectValue("INVALID_SYSTEM_SETTINGS_PAYLOAD").expectKeys("settings").requiredObject("settings").toSettingValueMap()
