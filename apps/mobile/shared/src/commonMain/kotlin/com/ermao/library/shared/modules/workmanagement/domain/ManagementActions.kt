package com.ermao.library.shared.modules.workmanagement.domain

enum class ManagementObject { Book, Directory, Resource }

data class ManagementTarget(val kind: ManagementObject, val bookId: String, val id: String, val title: String) {
    init { require(bookId.isNotBlank() && id.isNotBlank()); require(kind != ManagementObject.Book || id == bookId) }
}

data class ManagementMenuContext(
    val completed: Boolean? = null,
    val kindleSendAvailable: Boolean = false,
    val hasRepresentativeResource: Boolean = false,
)

enum class ManagementAction { Edit, Regenerate, ReadingStatus, Recognize, Rescan, UploadCover, Kindle, Delete }

data class ManagementMenuItem(val action: ManagementAction, val enabled: Boolean = true)

fun managementActions(
    kind: ManagementObject,
    canManage: Boolean,
    kindleSendAvailable: Boolean,
    hasRepresentativeResource: Boolean,
): List<ManagementMenuItem> = when (kind) {
    ManagementObject.Book -> if (canManage) listOf(
        ManagementAction.Edit, ManagementAction.Regenerate, ManagementAction.ReadingStatus,
        ManagementAction.Recognize, ManagementAction.Rescan, ManagementAction.Delete,
    ).map(::ManagementMenuItem) else listOf(ManagementMenuItem(ManagementAction.ReadingStatus))
    ManagementObject.Directory -> if (canManage) listOf(
        ManagementMenuItem(ManagementAction.Edit),
        ManagementMenuItem(ManagementAction.Regenerate, hasRepresentativeResource),
        ManagementMenuItem(ManagementAction.Recognize), ManagementMenuItem(ManagementAction.Rescan),
    ) else emptyList()
    ManagementObject.Resource -> buildList {
        if (canManage) addAll(listOf(ManagementAction.Edit, ManagementAction.UploadCover,
            ManagementAction.Regenerate, ManagementAction.Recognize).map(::ManagementMenuItem))
        if (kindleSendAvailable) add(ManagementMenuItem(ManagementAction.Kindle))
        if (canManage) add(ManagementMenuItem(ManagementAction.Delete))
    }
}

enum class ManagementField(val wireName: String) {
    Title("title"), Author("author"), Description("description"), SeriesName("seriesName"),
    SeriesIndex("seriesIndex"), Tags("tags"), ResourceIndex("resourceIndex"), Publisher("publisher"),
    PublishedAt("publishedAt"), Language("language"), Isbn("isbn"), Identifier("identifier"),
    Narrator("narrator"), Abridged("abridged"), Cover("cover"),
}

data class ManagementFieldValue(val field: ManagementField, val value: String)

data class ManagedBook(
    val id: String, val sourceNodeId: String, val title: String, val author: String,
    val description: String, val seriesName: String, val seriesIndex: Double?,
    val tags: List<String>, val coverUrl: String, val completed: Boolean,
)

data class ManagedAsset(val id: String, val title: String, val role: String, val size: String)

data class ManagedResource(
    val id: String, val bookId: String, val sourceNodeId: String, val title: String,
    val description: String, val format: String, val kindleSendAvailable: Boolean,
    val fields: List<ManagementFieldValue>, val coverUrl: String, val assets: List<ManagedAsset>,
)

data class ManagedDirectory(
    val id: String, val title: String, val description: String, val coverUrl: String,
    val representativeResourceId: String?,
)

data class ManagementSnapshot(val book: ManagedBook, val resources: List<ManagedResource>, val directory: ManagedDirectory?)

enum class CoverEdit { Keep, Replace, Remove }

data class RecognizedField(val scope: ManagementObject, val field: ManagementField) {
    val wireValue: String get() = "${if (scope == ManagementObject.Book) "book" else "resource"}.${this.field.wireName}"
}

data class MetadataApplyOutcome(val appliedFields: List<String>, val skippedFields: List<String>, val coverStatus: String)

enum class ManagementSaveStage { Metadata, Tags, Cover, Refresh }

data class ManagementChange(val bookId: String, val resourceId: String?, val deleted: Boolean, val coverChanged: Boolean, val readingStatusChanged: Boolean = false)

fun editableManagementFields(kind: ManagementObject): List<ManagementField> = when (kind) {
    ManagementObject.Book -> listOf(ManagementField.Title, ManagementField.Author, ManagementField.SeriesName,
        ManagementField.SeriesIndex, ManagementField.Tags, ManagementField.Description)
    ManagementObject.Directory -> listOf(ManagementField.Title, ManagementField.Description)
    ManagementObject.Resource -> listOf(ManagementField.Title, ManagementField.ResourceIndex,
        ManagementField.Description, ManagementField.Publisher, ManagementField.PublishedAt,
        ManagementField.Language, ManagementField.Isbn, ManagementField.Identifier, ManagementField.Narrator)
}

fun recognizedManagementFields(kind: ManagementObject): List<RecognizedField> = when (kind) {
    ManagementObject.Book -> (editableManagementFields(kind) + ManagementField.Cover).map { RecognizedField(kind, it) }
    ManagementObject.Directory -> editableManagementFields(kind).map { RecognizedField(kind, it) }
    ManagementObject.Resource -> listOf(ManagementField.Author, ManagementField.SeriesName,
        ManagementField.SeriesIndex, ManagementField.Tags).map { RecognizedField(ManagementObject.Book, it) } +
        (editableManagementFields(kind) + listOf(ManagementField.Abridged, ManagementField.Cover)).map { RecognizedField(kind, it) }
}
