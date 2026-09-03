import Foundation
import XCTest
@testable import ErmaoLibrary

final class AdministrativeSettingsTests: XCTestCase {
    func testCopyCatalogHasStrictZhEnglishParity() {
        XCTAssertTrue(AdministrativeCopyCatalog.hasCompleteParity())
        let zh = AdministrativeCopyCatalog(locale: .zhCN)
        let en = AdministrativeCopyCatalog(locale: .enUS)
        for key in AdministrativeCopyKey.allCases {
            XCTAssertFalse(zh[key].isEmpty, "Missing zh-CN copy: \(key)")
            XCTAssertFalse(en[key].isEmpty, "Missing en-US copy: \(key)")
        }
        XCTAssertEqual(zh[.managementTitle], "管理")
        XCTAssertEqual(en[.managementTitle], "Management")
    }

    func testHealthCodesAreLocalizedInsteadOfDisplayedAsServerKeys() {
        let zh = AdministrativeCopyCatalog(locale: .zhCN)
        let en = AdministrativeCopyCatalog(locale: .enUS)

        XCTAssertEqual(zh.healthText("health.item.database"), "数据库连接")
        XCTAssertEqual(zh.healthText("health.queue.ok"), "队列运行正常")
        XCTAssertEqual(en.healthText("health.item.database"), "Database Connection")
        XCTAssertEqual(en.healthText("health.queue.ok"), "Queue is running normally")
        XCTAssertEqual(zh.healthText("server.future.health.code"), "未知检查项目")
        XCTAssertEqual(en.healthText("server.future.health.code"), "Unknown check item")
    }

    @MainActor
    func testStoreCopyTracksAChangedLocale() {
        let store = AdministrativeSettingsStore(
            client: AdministrativeSettingsClientFake(),
            permissions: .init(isAdmin: true, canManageSystem: true),
            locale: .enUS,
            onUnauthorized: {}
        )

        store.updateLocale(.zhCN)

        XCTAssertEqual(store.copy.locale, .zhCN)
        XCTAssertEqual(store.copy[.managementTitle], "管理")
    }

    func testPermissionsKeepUserManagementAdminOnly() {
        let member = AdministrativePermission(isAdmin: false, canManageSystem: false)
        let systemManager = AdministrativePermission(isAdmin: false, canManageSystem: true)
        let admin = AdministrativePermission(isAdmin: true, canManageSystem: true)

        XCTAssertTrue(member.permits(.emailAndKindle))
        XCTAssertFalse(member.permits(.health))
        XCTAssertFalse(systemManager.permits(.health))
        XCTAssertTrue(systemManager.permits(.logs))
        XCTAssertFalse(systemManager.permits(.users))
        XCTAssertTrue(admin.permits(.users))
    }

    func testRetiredMobileAdministrativeRoutesAreNotPermitted() {
        let manager = AdministrativePermission(isAdmin: true, canManageSystem: true)
        let retired: [AdministrativeSettingsRoute] = [
            .librarySources,
            .librarySourceEditor(sourceID: nil),
            .serverDirectoryPicker(purpose: .scanDirectory),
            .importTasks(libraryID: "library"),
            .importTaskDetail(taskID: "task"),
            .importScans,
            .importPreferences,
            .organizeQueue,
            .organizeCandidates,
            .organizeRuns,
            .recognitionPolicy,
            .libraryOperations,
            .categoryGovernance,
            .metadataProviders,
            .metadataProvider(providerID: "provider"),
            .backups,
            .workDetailOrder,
            .health,
        ]

        XCTAssertTrue(retired.allSatisfy { !$0.isAvailableOnMobile && !manager.permits($0) })
    }

    @MainActor
    func testUnauthorizedOperationRequestsReauthenticationAndDoesNotReportSuccess() async {
        let client = AdministrativeSettingsClientFake()
        client.nextError = AdministrativeFailure(kind: .unauthorized, code: "SESSION_EXPIRED")
        var reauthenticationCount = 0
        let store = AdministrativeSettingsStore(
            client: client,
            permissions: .init(isAdmin: true, canManageSystem: true),
            locale: .enUS,
            onUnauthorized: { reauthenticationCount += 1 }
        )

        let result = await store.perform(id: "save") {
            _ = try await client.saveKindle(.init(recipient: "reader@kindle.com", smtpConfigured: true, senderEmail: "sender@example.com"))
        }

        XCTAssertFalse(result)
        XCTAssertEqual(reauthenticationCount, 1)
        XCTAssertEqual(store.notice?.style, .error)
    }

    @MainActor
    func testStaleSummaryResponseCannotReplaceNewerResponse() async {
        let client = AdministrativeSettingsClientFake()
        client.summaryDelay = 150_000_000
        let store = AdministrativeSettingsStore(
            client: client,
            permissions: .init(isAdmin: true, canManageSystem: true),
            locale: .enUS,
            onUnauthorized: {}
        )

        let first = Task { await store.loadSummary(force: true) }
        await Task.yield()
        client.summaryDelay = 0
        client.summary = AdministrativeManagementSummary(smtpEnabled: true, failedKindleCount: 0)
        await store.loadSummary(force: true)
        await first.value

        guard case let .loaded(summary) = store.summary else {
            return XCTFail("Expected loaded summary")
        }
        XCTAssertTrue(summary.smtpEnabled)
    }

    func testEveryAvailableMobileDestinationHasAStableRoute() {
        let routes: [AdministrativeSettingsRoute] = [
            .emailAndKindle, .kindleQueue, .users, .userEditor(userID: nil),
            .userAccess(userID: "u"), .opds, .logs, .about
        ]
        XCTAssertEqual(Set(routes).count, routes.count)
        XCTAssertTrue(routes.allSatisfy { $0.isAvailableOnMobile })
    }

    @MainActor
    func testServerDirectorySelectionIsScopedAndConsumedOnce() {
        let store = AdministrativeSettingsStore(
            client: AdministrativeSettingsClientFake(),
            permissions: .init(isAdmin: true, canManageSystem: true),
            locale: .enUS,
            onUnauthorized: {}
        )
        store.selectServerDirectory("/library/new", for: .createSource)
        XCTAssertNil(store.consumeServerDirectorySelection(for: .scanDirectory))
        XCTAssertEqual(store.consumeServerDirectorySelection(for: .createSource), "/library/new")
        XCTAssertNil(store.consumeServerDirectorySelection(for: .createSource))

        store.selectServerDirectory("/library/existing", for: .updateSource(sourceID: "source-1"))
        XCTAssertEqual(
            store.consumeServerDirectorySelection(for: .updateSource(sourceID: "source-1")),
            "/library/existing"
        )
    }
}

private final class AdministrativeSettingsClientFake: AdministrativeSettingsClient, @unchecked Sendable {
    var nextError: Error?
    var summaryDelay: UInt64 = 0
    var summary = AdministrativeManagementSummary(smtpEnabled: false, failedKindleCount: 0)

    func invalidatePendingResponses() async throws {}
    func loadManagementSummary() async throws -> AdministrativeManagementSummary { if summaryDelay > 0 { try await Task.sleep(nanoseconds: summaryDelay) }; return summary }
    private func fail() throws { if let nextError { throw nextError } }
    func loadEmailAndKindle() async throws -> EmailKindleSnapshot { try fail(); throw AdministrativeFailure(kind: .notFound, code: "fixture") }
    func saveKindle(_ settings: KindleSettings) async throws -> KindleSettings { try fail(); return settings }
    func saveSMTP(_ settings: SMTPSettings) async throws -> SMTPSettings { try fail(); return settings }
    func sendSMTPTest(_ settings: SMTPSettings) async throws { try fail() }
    func loadKindleTasks(status: KindleTaskStatus?) async throws -> [KindleSendTask] { try fail(); return [] }
    func cancelKindleTask(id: String) async throws { try fail() }; func retryKindleTask(id: String) async throws { try fail() }; func deleteKindleTask(id: String) async throws { try fail() }
    func loadUsers(query: String, enabled: Bool?, page: Int) async throws -> UserPage { try fail(); return .init(users: [], page: 1, pageCount: 1, total: 0) }
    func loadUser(id: String) async throws -> AdministrativeUser { try fail(); throw AdministrativeFailure(kind: .notFound, code: "fixture") }
    func createUser(_ draft: UserDraft) async throws -> AdministrativeUser { try fail(); throw AdministrativeFailure(kind: .notFound, code: "fixture") }
    func updateUser(id: String, draft: UserDraft) async throws -> AdministrativeUser { try fail(); throw AdministrativeFailure(kind: .notFound, code: "fixture") }
    func setUserEnabled(id: String, enabled: Bool) async throws -> AdministrativeUser { try fail(); throw AdministrativeFailure(kind: .notFound, code: "fixture") }
    func deleteUser(id: String) async throws { try fail() }; func resetUserPassword(id: String, newPassword: String) async throws { try fail() }
    func loadUserAccess(id: String) async throws -> UserAccessSnapshot { try fail(); throw AdministrativeFailure(kind: .notFound, code: "fixture") }
    func saveUserAccess(id: String, libraryIDs: Set<String>, canViewManualImports: Bool) async throws -> AdministrativeUser { try fail(); throw AdministrativeFailure(kind: .notFound, code: "fixture") }
    func loadLibrarySources() async throws -> LibrarySourcesSnapshot { try fail(); return .init(storage: nil, sources: [], activeScan: nil) }
    func loadLibrarySource(id: String) async throws -> LibrarySource { try fail(); throw AdministrativeFailure(kind: .notFound, code: "fixture") }
    func createLibrarySource(_ source: LibrarySource) async throws -> LibrarySource { try fail(); return source }; func updateLibrarySource(_ source: LibrarySource) async throws -> LibrarySource { try fail(); return source }
    func deleteLibrarySource(id: String) async throws { try fail() }; func rescanLibrarySource(id: String) async throws { try fail() }
    func loadServerDirectories(path: String?) async throws -> ServerDirectoryPage { try fail(); return .init(currentPath: "/", breadcrumbs: [], directories: []) }; func scanDirectory(path: String) async throws { try fail() }; func cancelDirectoryScan() async throws { try fail() }
    func loadImportTasks(libraryID: String) async throws -> [ImportTask] { try fail(); return [] }; func retryImportTask(id: String) async throws { try fail() }; func deleteImportTask(id: String) async throws { try fail() }; func clearCompletedImportTasks() async throws { try fail() }; func rescanAllLibrarySources() async throws { try fail() }
    func loadImportTaskDetail(id: String) async throws -> ImportTaskDetail { try fail(); throw AdministrativeFailure(kind: .notFound, code: "fixture") }
    func loadImportScans() async throws -> [ImportScanJob] { try fail(); return [] }; func cancelImportScan(id: String) async throws { try fail() }
    func loadImportPreferences() async throws -> ImportPreferences { try fail(); throw AdministrativeFailure(kind: .notFound, code: "fixture") }; func saveImportPreferences(_ preferences: ImportPreferences) async throws -> ImportPreferences { try fail(); return preferences }
    func loadLibraryScanSettings() async throws -> LibraryScanSettings { try fail(); return .init(watchEnabled: true, intervalMinutes: 30) }; func saveLibraryScanSettings(_ settings: LibraryScanSettings) async throws -> LibraryScanSettings { try fail(); return settings }
    func loadOrganizeJobs(status: OrganizeJobStatus?) async throws -> [OrganizeJob] { try fail(); return [] }; func loadPendingOrganizeJobs() async throws -> [OrganizeJob] { try fail(); return [] }; func loadOrganizeRuns() async throws -> [OrganizeRun] { try fail(); return [] }; func recognizeOrganizeJob(id: String) async throws { try fail() }; func deleteOrganizeJob(id: String) async throws { try fail() }; func loadRecognitionCandidates() async throws -> [RecognitionCandidate] { try fail(); return [] }
    func loadRecognitionPolicy() async throws -> RecognitionPolicy { try fail(); throw AdministrativeFailure(kind: .notFound, code: "fixture") }; func saveRecognitionPolicy(_ policy: RecognitionPolicy) async throws -> RecognitionPolicy { try fail(); return policy }
    func loadLibraryOperations() async throws -> [LibraryOperation] { try fail(); return [] }; func undoLibraryOperation(id: String) async throws { try fail() }
    func loadCategories(kind: CategoryKind, query: String) async throws -> [GovernedCategory] { try fail(); return [] }; func renameCategory(id: String, name: String) async throws -> String { try fail(); return "operation" }; func mergeCategories(_ request: MergeCategoryRequest) async throws -> String { try fail(); return "operation" }; func deleteCategory(id: String) async throws { try fail() }
    func loadMetadataProviders() async throws -> [MetadataProvider] { try fail(); return [] }; func setMetadataProviderEnabled(id: String, enabled: Bool) async throws -> MetadataProvider { try fail(); throw AdministrativeFailure(kind: .notFound, code: "fixture") }; func loadMetadataProviderConfiguration(id: String) async throws -> MetadataProviderConfiguration { try fail(); throw AdministrativeFailure(kind: .notFound, code: "fixture") }; func saveMetadataProviderConfiguration(_ configuration: MetadataProviderConfiguration) async throws -> MetadataProviderConfiguration { try fail(); return configuration }; func testMetadataProvider(id: String) async throws -> MetadataProvider { try fail(); throw AdministrativeFailure(kind: .notFound, code: "fixture") }
    func loadOPDSConfiguration() async throws -> OPDSConfiguration { try fail(); return .init(enabled: false, publicBaseURL: "", catalogURL: nil, running: false) }; func saveOPDSConfiguration(_ configuration: OPDSConfiguration) async throws -> OPDSConfiguration { try fail(); return configuration }
    func loadBackups() async throws -> [BackupRecord] { try fail(); return [] }; func createBackup() async throws -> BackupRecord { try fail(); throw AdministrativeFailure(kind: .notFound, code: "fixture") }; func prepareBackupExport(id: String) async throws -> AdministrativeExportFile { try fail(); throw AdministrativeFailure(kind: .notFound, code: "fixture") }; func restoreBackup(id: String, confirmation: String) async throws { try fail() }; func deleteBackup(id: String) async throws { try fail() }
    func loadWorkDetailOrder() async throws -> [AdministrativeWorkDetailSection] { try fail(); return AdministrativeWorkDetailSection.allCases }; func saveWorkDetailOrder(_ order: [AdministrativeWorkDetailSection]) async throws -> [AdministrativeWorkDetailSection] { try fail(); return order }
    func loadSystemHealth() async throws -> SystemHealthSnapshot { try fail(); return .init(checkedAt: nil, components: []) }; func runSystemHealthCheck() async throws -> SystemHealthSnapshot { try await loadSystemHealth() }
    func loadLogs(filter: LogFilter) async throws -> LogPage { try fail(); return .init(events: [], usedBytes: 0, limitBytes: 1) }; func loadLogSettings() async throws -> LogSettings { try fail(); return .init(limitMegabytes: 50) }; func saveLogSettings(_ settings: LogSettings) async throws -> LogSettings { try fail(); return settings }; func prepareLogExport(filter: LogFilter) async throws -> AdministrativeExportFile { try fail(); throw AdministrativeFailure(kind: .notFound, code: "fixture") }; func clearLogs() async throws { try fail() }
    func loadAbout() async throws -> AdministrativeAbout { try fail(); return .init(appVersion: "", appBuild: "", serverVersion: "", supportedFormats: [], license: "", repositoryURL: nil, releases: []) }
}
