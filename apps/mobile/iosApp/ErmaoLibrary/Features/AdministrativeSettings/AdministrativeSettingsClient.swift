import Foundation

protocol AdministrativeSettingsClient: Sendable {
    func invalidatePendingResponses() async throws
    func loadManagementSummary() async throws -> AdministrativeManagementSummary

    func loadEmailAndKindle() async throws -> EmailKindleSnapshot
    func saveKindle(_ settings: KindleSettings) async throws -> KindleSettings
    func saveSMTP(_ settings: SMTPSettings) async throws -> SMTPSettings
    func sendSMTPTest() async throws
    func loadKindleTasks(status: KindleTaskStatus?) async throws -> [KindleSendTask]
    func cancelKindleTask(id: String) async throws
    func retryKindleTask(id: String) async throws
    func deleteKindleTask(id: String) async throws

    func loadUsers(query: String, enabled: Bool?, page: Int) async throws -> UserPage
    func loadUser(id: String) async throws -> AdministrativeUser
    func createUser(_ draft: UserDraft) async throws -> AdministrativeUser
    func updateUser(id: String, draft: UserDraft) async throws -> AdministrativeUser
    func setUserEnabled(id: String, enabled: Bool) async throws -> AdministrativeUser
    func deleteUser(id: String) async throws
    func resetUserPassword(id: String, newPassword: String) async throws
    func loadUserAccess(id: String) async throws -> UserAccessSnapshot
    func saveUserAccess(
        id: String,
        libraryIDs: Set<String>,
        canViewManualImports: Bool
    ) async throws -> AdministrativeUser

    func loadLibrarySources() async throws -> LibrarySourcesSnapshot
    func loadLibrarySource(id: String) async throws -> LibrarySource
    func createLibrarySource(_ source: LibrarySource) async throws -> LibrarySource
    func updateLibrarySource(_ source: LibrarySource) async throws -> LibrarySource
    func deleteLibrarySource(id: String) async throws
    func rescanLibrarySource(id: String) async throws
    func loadServerDirectories(path: String?) async throws -> ServerDirectoryPage
    func scanDirectory(path: String) async throws
    func cancelDirectoryScan() async throws

    func loadImportTasks(status: ImportTaskStatus?) async throws -> [ImportTask]
    func loadImportTaskDetail(id: String) async throws -> ImportTaskDetail
    func retryImportTask(id: String) async throws
    func deleteImportTask(id: String) async throws
    func clearCompletedImportTasks() async throws
    func rescanAllLibrarySources() async throws
    func loadImportScans() async throws -> [ImportScanJob]
    func cancelImportScan(id: String) async throws
    func loadImportPreferences() async throws -> ImportPreferences
    func saveImportPreferences(_ preferences: ImportPreferences) async throws -> ImportPreferences

    func loadOrganizeJobs(status: OrganizeJobStatus?) async throws -> [OrganizeJob]
    func loadPendingOrganizeJobs() async throws -> [OrganizeJob]
    func loadOrganizeRuns() async throws -> [OrganizeRun]
    func recognizeOrganizeJob(id: String) async throws
    func deleteOrganizeJob(id: String) async throws
    func loadRecognitionCandidates() async throws -> [RecognitionCandidate]
    func loadRecognitionPolicy() async throws -> RecognitionPolicy
    func saveRecognitionPolicy(_ policy: RecognitionPolicy) async throws -> RecognitionPolicy

    func loadLibraryOperations() async throws -> [LibraryOperation]
    func undoLibraryOperation(id: String) async throws
    func loadCategories(kind: CategoryKind, query: String) async throws -> [GovernedCategory]
    func renameCategory(id: String, name: String) async throws -> String
    func mergeCategories(_ request: MergeCategoryRequest) async throws -> String
    func deleteCategory(id: String) async throws

    func loadMetadataProviders() async throws -> [MetadataProvider]
    func setMetadataProviderEnabled(id: String, enabled: Bool) async throws -> MetadataProvider
    func loadMetadataProviderConfiguration(id: String) async throws -> MetadataProviderConfiguration
    func saveMetadataProviderConfiguration(
        _ configuration: MetadataProviderConfiguration
    ) async throws -> MetadataProviderConfiguration
    func testMetadataProvider(id: String) async throws -> MetadataProvider
    func loadMetadataPipeline() async throws -> MetadataPipeline
    func saveMetadataPipeline(_ pipeline: MetadataPipeline) async throws -> MetadataPipeline

    func loadOPDSConfiguration() async throws -> OPDSConfiguration
    func saveOPDSConfiguration(_ configuration: OPDSConfiguration) async throws -> OPDSConfiguration
    func loadBackups() async throws -> [BackupRecord]
    func createBackup() async throws -> BackupRecord
    func prepareBackupExport(id: String) async throws -> AdministrativeExportFile
    func restoreBackup(id: String, confirmation: String) async throws
    func deleteBackup(id: String) async throws
    func loadWorkDetailOrder() async throws -> [AdministrativeWorkDetailSection]
    func saveWorkDetailOrder(_ order: [AdministrativeWorkDetailSection]) async throws -> [AdministrativeWorkDetailSection]

    func loadSystemHealth() async throws -> SystemHealthSnapshot
    func runSystemHealthCheck() async throws -> SystemHealthSnapshot
    func restartImportQueueSafely() async throws -> SystemHealthSnapshot
    func loadLogs(filter: LogFilter) async throws -> LogPage
    func loadLogSettings() async throws -> LogSettings
    func saveLogSettings(_ settings: LogSettings) async throws -> LogSettings
    func prepareLogExport(filter: LogFilter) async throws -> AdministrativeExportFile
    func clearLogs() async throws
    func loadAbout() async throws -> AdministrativeAbout
}
