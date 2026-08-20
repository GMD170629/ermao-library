import Foundation
@preconcurrency import ErmaoShared

actor SharedAdministrativeSettingsClient: AdministrativeSettingsClient {
    private let repository: any ErmaoShared.AdministrativeSettingsRepository
    private let context: ErmaoShared.AdministrativeSettingsContext
    private let appIdentity: AdministrativeAppIdentity
    private let serverVersionLoader: @Sendable () async throws -> String
    private let permissions: AdministrativePermission
    private var cachedSMTP: SMTPSettings?
    private var cachedUsers: [String: AdministrativeUser] = [:]
    private var cachedSources: [String: LibrarySource] = [:]
    private var cachedProviderConfigurations: [String: MetadataProviderConfiguration] = [:]
    private var lastScanJobID: String?
    private var latestHealthRunID: String?
    private var latestQueueOperationID: String?

    init(
        repository: any ErmaoShared.AdministrativeSettingsRepository,
        context: ErmaoShared.AdministrativeSettingsContext,
        appIdentity: AdministrativeAppIdentity = .current(),
        permissions: AdministrativePermission,
        serverVersionLoader: @escaping @Sendable () async throws -> String
    ) {
        self.repository = repository
        self.context = context
        self.appIdentity = appIdentity
        self.permissions = permissions
        self.serverVersionLoader = serverVersionLoader
    }

    func invalidatePendingResponses() async throws {
        try await repository.invalidatePendingResponses()
    }

    func loadManagementSummary() async throws -> AdministrativeManagementSummary {
        guard permissions.canManageSystem || permissions.isAdmin else {
            throw AdministrativeFailure(kind: .forbidden, code: "ADMINISTRATIVE_FORBIDDEN")
        }
        if permissions.isAdmin && !permissions.canManageSystem {
            async let users: [ErmaoShared.ManagedUser] = value(try await repository.listUsers(context: context))
            async let kindle: ErmaoShared.KindleTaskPage = value(try await repository.listKindleTasks(context: context, filter: ErmaoShared.KindleTaskFilter(status: .failed, page: 1, pageSize: 1)))
            let loadedUsers = try await users
            let loadedKindle = try await kindle
            return AdministrativeManagementSummary(
                librarySourceCount: 0, enabledLibraryCount: 0, activeImportCount: 0,
                importFormatCount: 0, pendingOrganizeCount: 0,
                availableProviderCount: 0, providerCount: 0, userCount: loadedUsers.count,
                smtpEnabled: false, failedKindleCount: Int(loadedKindle.pageInfo.total), opdsRunning: false,
                latestBackupAt: nil, healthyComponentCount: 0, componentCount: 0,
                logBytes: 0, logLimitBytes: 0
            )
        }
        async let folders: ErmaoShared.Libraries = value(try await repository.loadLibraries(context: context))
        async let imports: ErmaoShared.ImportTaskPage = value(try await repository.listImportTasks(context: context, filter: ErmaoShared.ImportTaskFilter(status: nil, keyword: nil, page: 1, pageSize: 1)))
        async let preferences: ErmaoShared.ImportPreferences = value(try await repository.loadImportPreferences(context: context))
        async let organize: ErmaoShared.OrganizeJobPage = value(try await repository.listOrganizeJobs(context: context, filter: ErmaoShared.OrganizeJobFilter(search: nil, status: nil, page: 1, pageSize: 1)))
        async let providers: ErmaoShared.MetadataProviders = value(try await repository.loadMetadataProviders(context: context))
        async let users: [ErmaoShared.ManagedUser] = permissions.isAdmin
            ? value(try await repository.listUsers(context: context))
            : []
        async let email: ErmaoShared.EmailSettings = value(try await repository.loadEmailSettings(context: context))
        async let kindle: ErmaoShared.KindleTaskPage = value(try await repository.listKindleTasks(context: context, filter: ErmaoShared.KindleTaskFilter(status: .failed, page: 1, pageSize: 1)))
        async let opds: ErmaoShared.OpdsSettings = value(try await repository.loadOpdsSettings(context: context))
        async let backups: [ErmaoShared.BackupArchive] = value(try await repository.listBackups(context: context))
        async let events: ErmaoShared.ManagementEventPage = value(try await repository.listManagementEvents(context: context, filter: managementFilter(LogFilter(query: "", levels: Set(LogLevel.allCases), source: nil, since: nil), pageSize: 1)))
        let loadedFolders = try await folders
        let loadedImports = try await imports
        let loadedProviders = try await providers
        let loadedBackups = try await backups
        let loadedEvents = try await events
        let loadedPreferences = try await preferences
        let loadedOrganize = try await organize
        let loadedUsers = try await users
        let loadedEmail = try await email
        let loadedKindle = try await kindle
        let loadedOPDS = try await opds
        return AdministrativeManagementSummary(
            librarySourceCount: loadedFolders.libraries.count,
            enabledLibraryCount: loadedFolders.libraries.filter(\.enabled).count,
            activeImportCount: Int(loadedImports.summary.failed) + loadedImports.tasks.filter { $0.status == .pending || $0.status == .parsing }.count,
            importFormatCount: loadedPreferences.allowedExtensions.count,
            pendingOrganizeCount: Int(loadedOrganize.pageInfo.total),
            availableProviderCount: loadedProviders.providers.filter { $0.enabled && $0.lastTestStatus?.lowercased() == "ok" }.count,
            providerCount: loadedProviders.providers.count,
            userCount: loadedUsers.count,
            smtpEnabled: !loadedEmail.smtp.host.isEmpty,
            failedKindleCount: Int(loadedKindle.pageInfo.total),
            opdsRunning: loadedOPDS.enabled,
            latestBackupAt: loadedBackups.compactMap { date($0.createdAt) }.max(),
            healthyComponentCount: 0,
            componentCount: 0,
            logBytes: loadedEvents.storage.sizeBytes,
            logLimitBytes: loadedEvents.storage.maximumBytes
        )
    }

    func loadEmailAndKindle() async throws -> EmailKindleSnapshot {
        async let kindleResult = repository.loadKindleSettings(context: context)
        let kindleWire: ErmaoShared.KindleSettings = try value(await kindleResult)
        let kindle = map(kindleWire)
        do {
            let smtpWire: ErmaoShared.EmailSettings = try value(try await repository.loadEmailSettings(context: context))
            let smtp = map(smtpWire.smtp)
            cachedSMTP = smtp
            return EmailKindleSnapshot(kindle: kindle, smtp: smtp, canManageSMTP: true)
        } catch let failure as AdministrativeFailure where failure.kind == .forbidden {
            return EmailKindleSnapshot(kindle: kindle, smtp: nil, canManageSMTP: false)
        }
    }

    func saveKindle(_ settings: KindleSettings) async throws -> KindleSettings {
        let wire: ErmaoShared.KindleSettings = try value(try await repository.updateKindleEmail(context: context, email: settings.recipient))
        return map(wire)
    }
    func saveSMTP(_ settings: SMTPSettings) async throws -> SMTPSettings {
        let wire: ErmaoShared.EmailSettings = try value(try await repository.updateEmailSettings(context: context, update: smtpUpdate(settings)))
        let mapped = map(wire.smtp); cachedSMTP = mapped; return mapped
    }
    func sendSMTPTest() async throws {
        guard let settings = cachedSMTP else { throw AdministrativeFailure(kind: .validation, code: "SMTP_NOT_LOADED") }
        let tested: ErmaoShared.SmtpTestResult = try value(try await repository.testSmtp(context: context, update: smtpUpdate(settings)))
        guard tested.connected else { throw AdministrativeFailure(kind: .unavailable, code: "SMTP_TEST_FAILED") }
    }
    func loadKindleTasks(status: KindleTaskStatus?) async throws -> [KindleSendTask] {
        let wire: ErmaoShared.KindleTaskPage = try value(try await repository.listKindleTasks(context: context, filter: ErmaoShared.KindleTaskFilter(status: map(status), page: 1, pageSize: 200)))
        return wire.tasks.map(map)
    }
    func cancelKindleTask(id: String) async throws { let _: ErmaoShared.KindleTask = try value(try await repository.cancelKindleTask(context: context, taskId: id)) }
    func retryKindleTask(id: String) async throws { let _: ErmaoShared.KindleTask = try value(try await repository.retryKindleTask(context: context, taskId: id)) }
    func deleteKindleTask(id: String) async throws { let deleted: KotlinBoolean = try value(try await repository.deleteKindleTask(context: context, taskId: id)); guard deleted.boolValue else { throw protocolFailure() } }

    func loadUsers(query: String, enabled: Bool?, page: Int) async throws -> UserPage {
        let values: [ErmaoShared.ManagedUser] = try value(try await repository.listUsers(context: context))
        let mapped = values.map(map).filter { (query.isEmpty || $0.displayName.localizedCaseInsensitiveContains(query) || $0.email.localizedCaseInsensitiveContains(query)) && (enabled == nil || $0.enabled == enabled) }
        cachedUsers = Dictionary(uniqueKeysWithValues: mapped.map { ($0.id, $0) })
        return UserPage(users: mapped, page: 1, pageCount: 1, total: mapped.count)
    }
    func loadUser(id: String) async throws -> AdministrativeUser { let wire: ErmaoShared.ManagedUser = try value(try await repository.loadUser(context: context, userId: id)); let mapped = map(wire); cachedUsers[id] = mapped; return mapped }
    func createUser(_ draft: UserDraft) async throws -> AdministrativeUser {
        let wire: ErmaoShared.ManagedUser = try value(try await repository.createUser(context: context, user: ErmaoShared.CreateManagedUser(name: draft.displayName, email: draft.email, password: draft.initialPassword, role: map(draft.role), canManageSystem: draft.canManageSystem, canViewManualImports: false, libraryIds: [], locale: map(draft.locale))))
        let mapped = map(wire); cachedUsers[mapped.id] = mapped; return mapped
    }
    func updateUser(id: String, draft: UserDraft) async throws -> AdministrativeUser {
        let existing: AdministrativeUser
        if let cached = cachedUsers[id] { existing = cached } else { existing = try await loadUser(id: id) }
        let wire: ErmaoShared.ManagedUser = try value(try await repository.updateUser(context: context, userId: id, user: userUpdate(draft: draft, existing: existing)))
        let mapped = map(wire); cachedUsers[id] = mapped; return mapped
    }
    func setUserEnabled(id: String, enabled: Bool) async throws -> AdministrativeUser {
        let existing: AdministrativeUser
        if let cached = cachedUsers[id] { existing = cached } else { existing = try await loadUser(id: id) }
        let draft = UserDraft(displayName: existing.displayName, email: existing.email, role: existing.role, enabled: enabled, canManageSystem: existing.canManageSystem, locale: existing.locale, initialPassword: "")
        return try await updateUser(id: id, draft: draft)
    }
    func deleteUser(id: String) async throws { let wire: ErmaoShared.DeletedManagedUser = try value(try await repository.deleteUser(context: context, userId: id, confirmation: "DELETE")); guard wire.deleted else { throw protocolFailure() }; cachedUsers[id] = nil }
    func resetUserPassword(id: String, newPassword: String) async throws { let wire: ErmaoShared.ManagedPasswordChange = try value(try await repository.resetUserPassword(context: context, userId: id, password: newPassword)); guard wire.passwordChanged else { throw protocolFailure() } }
    func loadUserAccess(id: String) async throws -> UserAccessSnapshot { let user = try await loadUser(id: id); let folders = try await loadLibrarySources().sources.map { AdministrativeLibraryScope(id: $0.id, name: $0.displayName, serverPath: $0.serverPath, workCount: 0) }; return UserAccessSnapshot(user: user, scopes: folders) }
    func saveUserAccess(id: String, libraryIDs: Set<String>, canViewManualImports: Bool) async throws -> AdministrativeUser {
        let existing: AdministrativeUser
        if let cached = cachedUsers[id] { existing = cached } else { existing = try await loadUser(id: id) }
        let update = ErmaoShared.UpdateManagedUser(name: existing.displayName, email: existing.email, role: map(existing.role), status: existing.enabled ? .active : .disabled, canManageSystem: existing.canManageSystem, canViewManualImports: canViewManualImports, libraryIds: Array(libraryIDs), locale: map(existing.locale))
        let wire: ErmaoShared.ManagedUser = try value(try await repository.updateUser(context: context, userId: id, user: update)); let mapped = map(wire); cachedUsers[id] = mapped; return mapped
    }

    func loadLibrarySources() async throws -> LibrarySourcesSnapshot {
        let wire: ErmaoShared.Libraries = try value(try await repository.loadLibraries(context: context))
        let mapped = wire.libraries.map(map); cachedSources = Dictionary(uniqueKeysWithValues: mapped.map { ($0.id, $0) })
        var scan: DirectoryScanProgress?
        if let lastScanJobID, let job: ErmaoShared.ImportScanJob = try? value(try await repository.loadImportScanJob(context: context, jobId: lastScanJobID)) { scan = map(job) }
        return LibrarySourcesSnapshot(storage: nil, sources: mapped, activeScan: scan)
    }
    func loadLibrarySource(id: String) async throws -> LibrarySource { if let cached = cachedSources[id] { return cached }; _ = try await loadLibrarySources(); guard let result = cachedSources[id] else { throw AdministrativeFailure(kind: .notFound, code: "SOURCE_NOT_FOUND") }; return result }
    func createLibrarySource(_ source: LibrarySource) async throws -> LibrarySource { let wire: ErmaoShared.Library = try value(try await repository.createLibrary(context: context, library: sourceDraft(source))); return map(wire) }
    func updateLibrarySource(_ source: LibrarySource) async throws -> LibrarySource { let wire: ErmaoShared.Library = try value(try await repository.updateLibrary(context: context, libraryId: source.id, library: sourceDraft(source))); return map(wire) }
    func deleteLibrarySource(id: String) async throws { let deleted: KotlinBoolean = try value(try await repository.deleteLibrary(context: context, libraryId: id)); guard deleted.boolValue else { throw protocolFailure() } }
    func rescanLibrarySource(id: String) async throws { let source = try await loadLibrarySource(id: id); try await scanDirectory(path: source.serverPath) }
    func loadServerDirectories(path: String?) async throws -> ServerDirectoryPage { let wire: ErmaoShared.DirectoryNode = try value(try await repository.loadDirectory(context: context, path: path)); return map(wire) }
    func scanDirectory(path: String) async throws { let job: ErmaoShared.ImportScanJob = try value(try await repository.scanDirectory(context: context, path: path)); lastScanJobID = job.id }
    func cancelDirectoryScan() async throws { guard let lastScanJobID else { throw AdministrativeFailure(kind: .validation, code: "NO_ACTIVE_SCAN") }; let _: ErmaoShared.ImportScanJob = try value(try await repository.cancelImportScanJob(context: context, jobId: lastScanJobID)) }

    func loadImportTasks(status: ImportTaskStatus?) async throws -> [ImportTask] { let wire: ErmaoShared.ImportTaskPage = try value(try await repository.listImportTasks(context: context, filter: ErmaoShared.ImportTaskFilter(status: map(status), keyword: nil, page: 1, pageSize: 200))); return wire.tasks.map(map) }
    func loadImportTaskDetail(id: String) async throws -> ImportTaskDetail { async let task: ErmaoShared.ImportTask = value(try await repository.loadImportTask(context: context, taskId: id)); async let logs: ErmaoShared.ImportTaskLogPage = value(try await repository.listImportTaskLogs(context: context, taskId: id, page: 1, pageSize: 200)); return ImportTaskDetail(task: map(try await task), logs: try await logs.logs.map(map)) }
    func retryImportTask(id: String) async throws { let _: ErmaoShared.ImportTask = try value(try await repository.retryImportTask(context: context, taskId: id)) }
    func deleteImportTask(id: String) async throws { let _: ErmaoShared.ImportTaskDeletion = try value(try await repository.deleteImportTask(context: context, taskId: id)) }
    func clearCompletedImportTasks() async throws { let _: KotlinInt = try value(try await repository.clearCompletedImportTasks(context: context)) }
    func rescanAllLibrarySources() async throws { let _: ErmaoShared.ImportRescanRequest = try value(try await repository.rescanImportFolders(context: context)) }
    func loadImportScans() async throws -> [ImportScanJob] { let values: [ErmaoShared.ImportScanJob] = try value(try await repository.listImportScanJobs(context: context, status: nil)); return values.map(mapScan) }
    func cancelImportScan(id: String) async throws { let _: ErmaoShared.ImportScanJob = try value(try await repository.cancelImportScanJob(context: context, jobId: id)) }
    func loadImportPreferences() async throws -> ImportPreferences { let wire: ErmaoShared.ImportPreferences = try value(try await repository.loadImportPreferences(context: context)); return map(wire) }
    func saveImportPreferences(_ preferences: ImportPreferences) async throws -> ImportPreferences { let wire: ErmaoShared.ImportPreferences = try value(try await repository.updateImportPreferences(context: context, preferences: map(preferences))); return map(wire) }

    func loadOrganizeJobs(status: OrganizeJobStatus?) async throws -> [OrganizeJob] { let wire: ErmaoShared.OrganizeJobPage = try value(try await repository.listOrganizeJobs(context: context, filter: ErmaoShared.OrganizeJobFilter(search: nil, status: map(status), page: 1, pageSize: 200))); return wire.jobs.map(map) }
    func loadPendingOrganizeJobs() async throws -> [OrganizeJob] { let wire: ErmaoShared.PendingOrganizeJobs = try value(try await repository.loadPendingOrganizeJobs(context: context)); return wire.jobs.map(map) }
    func loadOrganizeRuns() async throws -> [OrganizeRun] { let values: [ErmaoShared.OrganizeRun] = try value(try await repository.listOrganizeRuns(context: context)); return values.map(map) }
    func recognizeOrganizeJob(id: String) async throws { let _: ErmaoShared.OrganizeJob = try value(try await repository.recognizeOrganizeJob(context: context, jobId: id)) }
    func deleteOrganizeJob(id: String) async throws { let deleted: KotlinBoolean = try value(try await repository.deleteOrganizeJob(context: context, jobId: id)); guard deleted.boolValue else { throw protocolFailure() } }
    func loadRecognitionCandidates() async throws -> [RecognitionCandidate] { let wire: ErmaoShared.OrganizeCandidates = try value(try await repository.loadOrganizeCandidates(context: context)); return wire.works.map { RecognitionCandidate(id: $0.id, title: $0.title ?? "—", author: $0.author, confidence: Double($0.metadataQuality) / 100) } }
    func loadRecognitionPolicy() async throws -> RecognitionPolicy { async let policyValue: ErmaoShared.OrganizePolicy = value(try await repository.loadOrganizePolicy(context: context)); async let queueValue: ErmaoShared.OpfQueueStatus = value(try await repository.loadOpfQueueStatus(context: context)); return map(try await policyValue, queue: try await queueValue) }
    func saveRecognitionPolicy(_ policy: RecognitionPolicy) async throws -> RecognitionPolicy { let current: ErmaoShared.OrganizePolicy = try value(try await repository.loadOrganizePolicy(context: context)); let wire: ErmaoShared.OrganizePolicy = try value(try await repository.updateOrganizePolicy(context: context, policy: map(policy, onto: current))); let queue: ErmaoShared.OpfQueueStatus = try value(try await repository.loadOpfQueueStatus(context: context)); return map(wire, queue: queue) }

    func loadLibraryOperations() async throws -> [LibraryOperation] { let values: [ErmaoShared.LibraryOperation] = try value(try await repository.listLibraryOperations(context: context)); return values.map(map) }
    func undoLibraryOperation(id: String) async throws { let _: ErmaoShared.LibraryOperation = try value(try await repository.undoLibraryOperation(context: context, operationId: id)) }
    func loadCategories(kind: CategoryKind, query: String) async throws -> [GovernedCategory] { let wire: ErmaoShared.CategoryPage = try value(try await repository.listCategories(context: context, filter: ErmaoShared.CategoryFilter(kind: map(kind), search: query.isEmpty ? nil : query, page: 1, pageSize: 200))); return wire.categories.map(map) }
    func renameCategory(id: String, name: String) async throws -> String { let wire: ErmaoShared.LibraryOperation = try value(try await repository.renameCategory(context: context, categoryId: id, name: name)); return wire.id }
    func mergeCategories(_ request: MergeCategoryRequest) async throws -> String { let wire: ErmaoShared.LibraryOperation = try value(try await repository.mergeCategories(context: context, kind: map(request.kind), targetId: request.targetID, sourceIds: Array(request.sourceIDs))); return wire.id }
    func deleteCategory(id: String) async throws { let _: ErmaoShared.LibraryOperation = try value(try await repository.deleteCategory(context: context, categoryId: id)) }

    func loadMetadataProviders() async throws -> [MetadataProvider] { let wire: ErmaoShared.MetadataProviders = try value(try await repository.loadMetadataProviders(context: context)); return wire.providers.map(map) }
    func setMetadataProviderEnabled(id: String, enabled: Bool) async throws -> MetadataProvider { let config = try await loadMetadataProviderConfiguration(id: id); var updated = config; let provider = config.provider; updated = MetadataProviderConfiguration(provider: MetadataProvider(id: provider.id, displayName: provider.displayName, enabled: enabled, status: provider.status, responseMilliseconds: provider.responseMilliseconds, supportedMediaKinds: provider.supportedMediaKinds, hasSecret: provider.hasSecret, priority: provider.priority), values: config.values, secretReplacements: config.secretReplacements, clearedSecretKeys: config.clearedSecretKeys); return try await saveMetadataProviderConfiguration(updated).provider }
    func loadMetadataProviderConfiguration(id: String) async throws -> MetadataProviderConfiguration { let wire: ErmaoShared.MetadataProvider = try value(try await repository.loadMetadataProvider(context: context, providerId: id)); let mapped = mapConfiguration(wire); cachedProviderConfigurations[id] = mapped; return mapped }
    func saveMetadataProviderConfiguration(_ configuration: MetadataProviderConfiguration) async throws -> MetadataProviderConfiguration { let wire: ErmaoShared.MetadataProvider = try value(try await repository.updateMetadataProvider(context: context, providerId: configuration.provider.id, update: map(configuration))); let mapped = mapConfiguration(wire); cachedProviderConfigurations[wire.id] = mapped; return mapped }
    func testMetadataProvider(id: String) async throws -> MetadataProvider { let wire: ErmaoShared.ProviderTestResult = try value(try await repository.testMetadataProvider(context: context, providerId: id)); return map(wire.provider) }
    func loadMetadataPipeline() async throws -> MetadataPipeline { let wire: ErmaoShared.MetadataProviders = try value(try await repository.loadMetadataProviders(context: context)); guard let pipeline = wire.pipelines.first else { return MetadataPipeline(mediaKind: .ebook, providerIDs: [], enabledProviderIDs: []) }; return map(pipeline) }
    func saveMetadataPipeline(_ pipeline: MetadataPipeline) async throws -> MetadataPipeline { let entries = pipeline.providerIDs.map { ErmaoShared.MetadataPipelineEntry(providerId: $0, enabled: pipeline.enabledProviderIDs.contains($0)) }; let wire: ErmaoShared.MetadataProviders = try value(try await repository.updateMetadataPipeline(context: context, mediaKind: map(pipeline.mediaKind), entries: entries)); guard let updated = wire.pipelines.first(where: { $0.mediaKind == map(pipeline.mediaKind) }) else { throw protocolFailure() }; return map(updated) }

    func loadOPDSConfiguration() async throws -> OPDSConfiguration { let wire: ErmaoShared.OpdsSettings = try value(try await repository.loadOpdsSettings(context: context)); return map(wire) }
    func saveOPDSConfiguration(_ configuration: OPDSConfiguration) async throws -> OPDSConfiguration { let wire: ErmaoShared.OpdsSettings = try value(try await repository.updateOpdsSettings(context: context, enabled: configuration.enabled, publicBaseUrl: configuration.publicBaseURL.isEmpty ? nil : configuration.publicBaseURL)); return map(wire) }
    func loadBackups() async throws -> [BackupRecord] { let values: [ErmaoShared.BackupArchive] = try value(try await repository.listBackups(context: context)); return values.map(map) }
    func createBackup() async throws -> BackupRecord { let wire: ErmaoShared.BackupArchive = try value(try await repository.createBackup(context: context)); return map(wire) }
    func prepareBackupExport(id: String) async throws -> AdministrativeExportFile { let wire: ErmaoShared.BackupDownload = try value(try await repository.downloadBackup(context: context, backupId: id, maximumBytes: 200 * 1024 * 1024)); return AdministrativeExportFile(data: data(wire.bytes), filename: wire.fileName) }
    func restoreBackup(id: String, confirmation: String) async throws { guard confirmation == "RESTORE" else { throw AdministrativeFailure(kind: .validation, code: "CONFIRMATION_REQUIRED") }; let wire: ErmaoShared.BackupRestoreResult = try value(try await repository.restoreBackup(context: context, backupId: id, confirmation: .restore)); guard wire.restored else { throw protocolFailure() } }
    func deleteBackup(id: String) async throws { let deleted: KotlinBoolean = try value(try await repository.deleteBackup(context: context, backupId: id)); guard deleted.boolValue else { throw protocolFailure() } }
    func loadWorkDetailOrder() async throws -> [AdministrativeWorkDetailSection] { let wire: ErmaoShared.WorkDetailTabOrder = try value(try await repository.loadWorkDetailTabOrder(context: context)); return wire.tabs.map(map) }
    func saveWorkDetailOrder(_ order: [AdministrativeWorkDetailSection]) async throws -> [AdministrativeWorkDetailSection] { let wire: ErmaoShared.WorkDetailTabOrder = try value(try await repository.updateWorkDetailTabOrder(context: context, order: ErmaoShared.WorkDetailTabOrder(tabs: order.map(map)))); return wire.tabs.map(map) }

    func loadSystemHealth() async throws -> SystemHealthSnapshot { if let latestHealthRunID { let wire: ErmaoShared.HealthRun = try value(try await repository.loadHealthRun(context: context, runId: latestHealthRunID)); return map(wire) }; return SystemHealthSnapshot(checkedAt: nil, components: [], queueRestartInProgress: false, queueRestartStatus: nil) }
    func runSystemHealthCheck() async throws -> SystemHealthSnapshot { var wire: ErmaoShared.HealthRun = try value(try await repository.startHealthRun(context: context)); latestHealthRunID = wire.runId; while wire.status == .running { try Task.checkCancellation(); try await Task.sleep(nanoseconds: 600_000_000); wire = try value(try await repository.loadHealthRun(context: context, runId: wire.runId)) }; return map(wire) }
    func restartImportQueueSafely() async throws -> SystemHealthSnapshot { var operation: ErmaoShared.QueueOperation = try value(try await repository.restartImportQueue(context: context)); latestQueueOperationID = operation.id; while !["completed", "failed"].contains(operation.status.lowercased()) { try Task.checkCancellation(); try await Task.sleep(nanoseconds: 600_000_000); operation = try value(try await repository.loadQueueOperation(context: context, operationId: operation.id)) }; let health = try await loadSystemHealth(); return SystemHealthSnapshot(checkedAt: health.checkedAt, components: health.components, queueRestartInProgress: false, queueRestartStatus: operation.messageCode) }
    func loadLogs(filter: LogFilter) async throws -> LogPage { let wire: ErmaoShared.ManagementEventPage = try value(try await repository.listManagementEvents(context: context, filter: managementFilter(filter, pageSize: 200))); return map(wire) }
    func loadLogSettings() async throws -> LogSettings { let wire: ErmaoShared.LogSettings = try value(try await repository.loadLogSettings(context: context)); return LogSettings(limitMegabytes: Int(wire.storage.maximumBytes / 1_048_576)) }
    func saveLogSettings(_ settings: LogSettings) async throws -> LogSettings { let wire: ErmaoShared.EventStorage = try value(try await repository.updateLogCapacity(context: context, maximumBytes: Int64(settings.limitMegabytes) * 1_048_576)); return LogSettings(limitMegabytes: Int(wire.maximumBytes / 1_048_576)) }
    func prepareLogExport(filter: LogFilter) async throws -> AdministrativeExportFile { let values: [ErmaoShared.ManagementEvent] = try value(try await repository.loadAllManagementEventsForExport(context: context, filter: managementFilter(filter, pageSize: 200))); let csv = (["timestamp,level,source,action,target,id"] + values.map { [$0.createdAt ?? "", $0.level, $0.source, $0.action, $0.targetType ?? "", $0.targetId ?? ""].map(csvField).joined(separator: ",") }).joined(separator: "\n"); return AdministrativeExportFile(data: Data(csv.utf8), filename: "management-events.csv") }
    func clearLogs() async throws { let _: ErmaoShared.ClearedManagementEvents = try value(try await repository.clearManagementEvents(context: context)) }
    func loadAbout() async throws -> AdministrativeAbout { AdministrativeAbout(appVersion: appIdentity.version, appBuild: appIdentity.build, serverVersion: try await serverVersionLoader(), supportedFormats: appIdentity.supportedFormats, license: appIdentity.license, repositoryURL: appIdentity.repositoryURL, releases: appIdentity.releases) }
}
