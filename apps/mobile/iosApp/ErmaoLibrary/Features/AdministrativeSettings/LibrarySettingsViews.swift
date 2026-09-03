import SwiftUI

struct LibrarySourcesView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<LibrarySourcesSnapshot> = .idle
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme
    @Environment(\.administrativeNavigate) private var navigate

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { snapshot in
            SettingsList {
                if let storage = snapshot.storage {
                    Section {
                        SettingsValueRow(
                            LocalizedStringKey(copy[.storageLocation]),
                            value: "\(storage.label) · \(storage.path)",
                            systemImage: "externaldrive"
                        )
                        if let free = storage.freeBytes, let total = storage.totalBytes {
                            SettingsValueRow(
                                LocalizedStringKey(copy[.availableSpace]),
                                value: "\(free.administrativeByteCount) / \(total.administrativeByteCount)"
                            )
                        }
                    }
                }
                Section(copy[.libraries]) {
                    ForEach(snapshot.sources) { source in sourceRow(source) }
                }
                Section(header: SettingsSectionHeader(verbatim: copy[.importTasksTitle])) {
                    ForEach(snapshot.sources) { source in
                        SettingsNavigationRow(
                            verbatim: source.displayName,
                            status: copy[.importTasks],
                            systemImage: "arrow.down.to.line"
                        ) { navigate(.importTasks(libraryID: source.id)) }
                    }
                    SettingsNavigationRow(
                        LocalizedStringKey(copy[.importPreferences]),
                        systemImage: "slider.horizontal.3"
                    ) { navigate(.importPreferences) }
                }
                if let scan = snapshot.activeScan { scanRow(scan) }
            }
        }
        .navigationTitle(copy[.sourcesTitle]).navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Button(copy[.add]) { navigate(.librarySourceEditor(sourceID: nil)) } } }
        .refreshable { await loadAsync() }.task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func sourceRow(_ source: LibrarySource) -> some View {
        SettingsNavigationRow(
            verbatim: source.displayName,
            status: "\(source.enabled ? copy[.enabled] : copy[.disabled]) · \(source.serverPath)",
            systemImage: "folder"
        ) { navigate(.librarySourceEditor(sourceID: source.id)) }
    }
    private func scanRow(_ scan: DirectoryScanProgress) -> some View {
        Section {
            VStack(alignment: .leading, spacing: .space1) {
                Text("\(copy[.scanning]) \(scan.path)")
                ProgressView(value: Double(scan.processed), total: Double(max(scan.discovered ?? scan.processed + 1, 1))).tint(theme.brandAccent)
                HStack { Text("\(scan.processed)/\(scan.discovered.map(String.init) ?? "—")").font(.caption); Spacer(); if scan.canCancel { Button(copy[.cancelScan]) { Task { if await store.perform(id: "cancel-scan", operation: { try await store.client.cancelDirectoryScan() }) { await loadAsync() } } } } }
            }
        }
    }
    private func load() { Task { await loadAsync() } }
    private func loadAsync() async { state = .loading; state = await store.load(scope: "library-sources") { try await store.client.loadLibrarySources() } }
}

struct LibrarySourceEditorView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    let sourceID: String?
    @State private var source = LibrarySource(id: "", displayName: "", serverPath: "", enabled: true, organizationMode: .flat, ignorePatterns: "", ignoreHidden: true, minimumFileSizeBytes: 0, description: "")
    @State private var deleteShown = false
    @State private var loading = false
    @Environment(\.dismiss) private var dismiss
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.administrativeNavigate) private var navigate

    var body: some View {
        SettingsForm {
            Section {
                SettingsTextInputRow(LocalizedStringKey(copy[.sourceName])) {
                    TextField(LocalizedStringKey(copy[.sourceName]), text: $source.displayName)
                }
                SettingsValueRow(LocalizedStringKey(copy[.serverPath]), value: source.serverPath.isEmpty ? "—" : source.serverPath)
                SettingsActionRow(LocalizedStringKey(copy[.browseDirectory])) {
                    navigate(.serverDirectoryPicker(purpose: sourceID.map(ServerDirectoryPurpose.updateSource) ?? .createSource))
                }
            }
            Section {
                SettingsToggleRow(LocalizedStringKey(copy[.scanningEnabled]), isOn: $source.enabled)
                SettingsToggleRow(LocalizedStringKey(copy[.ignoreHiddenFiles]), isOn: $source.ignoreHidden)
                SettingsTextInputRow(LocalizedStringKey(copy[.ignorePatterns])) {
                    TextField(LocalizedStringKey(copy[.ignorePatterns]), text: $source.ignorePatterns)
                }
                SettingsTextInputRow(LocalizedStringKey(copy[.minimumFileSize])) {
                    TextField(LocalizedStringKey(copy[.minimumFileSize]), value: $source.minimumFileSizeBytes, format: .number)
                        .keyboardType(.numberPad)
                }
                SettingsTextInputRow(LocalizedStringKey(copy[.sourceDescription])) {
                    TextField(LocalizedStringKey(copy[.sourceDescription]), text: $source.description, axis: .vertical)
                }
            }
            Section(copy[.organizationMode]) {
                SettingsFieldRow(LocalizedStringKey(copy[.organizationMode])) {
                    Picker(LocalizedStringKey(copy[.organizationMode]), selection: $source.organizationMode) {
                        ForEach(LibraryOrganizationMode.allCases, id: \.self) { mode in
                            Text(organizationModeTitle(mode)).tag(mode)
                        }
                    }
                }
            }
            if sourceID != nil {
                Section { SettingsActionRow(LocalizedStringKey(copy[.deleteSource]), role: .destructive) { deleteShown = true } }
            }
        }
        .navigationTitle(sourceID == nil ? copy[.add] : copy[.edit]).navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                AdministrativeToolbarAction(
                    title: copy[.save],
                    working: store.operationInFlight != nil,
                    disabled: source.displayName.isEmpty || source.serverPath.isEmpty,
                    action: save
                )
            }
        }
        .confirmationDialog(copy[.deleteSourceTitle], isPresented: $deleteShown, titleVisibility: .visible) { Button(copy[.deleteSource], role: .destructive, action: delete); Button(copy[.cancel], role: .cancel) {} } message: { Text(copy[.deleteSourceMessage]) }
        .onReceive(store.$directorySelection.compactMap { $0 }) { selection in
            let expected = sourceID.map(ServerDirectoryPurpose.updateSource) ?? .createSource
            if selection.purpose == expected, let path = store.consumeServerDirectorySelection(for: expected) { source.serverPath = path }
        }
        .task { await load() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func load() async { guard let sourceID else { return }; loading = true; defer { loading = false }; if let value = await store.loadValue(scope: "source-\(sourceID)", operation: { try await store.client.loadLibrarySource(id: sourceID) }) { source = value } }
    private func save() { Task { let result = sourceID == nil ? await store.performValue(id: "create-source", operation: { try await store.client.createLibrarySource(source) }) : await store.performValue(id: "update-source", operation: { try await store.client.updateLibrarySource(source) }); if case .success = result { dismiss() } } }
    private func delete() { guard let sourceID else { return }; Task { if await store.perform(id: "delete-source", operation: { try await store.client.deleteLibrarySource(id: sourceID) }) { dismiss() } } }
    private func organizationModeTitle(_ mode: LibraryOrganizationMode) -> String { switch mode { case .flat: copy[.flatLayout]; case .volumes: copy[.volumesLayout]; case .audiobook: copy[.audiobookLayout] } }
}

struct ServerDirectoryPickerView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    let purpose: ServerDirectoryPurpose
    @State private var state: AdministrativeLoadState<ServerDirectoryPage> = .idle
    @State private var currentPath: String?
    @Environment(\.dismiss) private var dismiss
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { page in
            SettingsList {
                Section { SettingsValueRow(LocalizedStringKey(copy[.serverPath]), value: page.currentPath) }
                Section {
                    ForEach(page.directories) { entry in
                        SettingsNavigationRow(
                            verbatim: entry.isParent ? copy[.parentDirectory] : entry.name,
                            status: entry.modifiedAt?.administrativeFormatted(locale: copy.locale),
                            systemImage: entry.isParent ? "arrow.up.doc" : "folder"
                        ) { currentPath = entry.absolutePath; load() }
                    }
                }
            }
            .administrativeNotice(store: store)
            .safeAreaInset(edge: .bottom) { AdministrativeBottomAction(title: purpose == .scanDirectory ? copy[.scanDirectory] : copy[.chooseDirectory], disabled: page.currentPath.isEmpty, action: { select(page.currentPath) }) }
        }
        .navigationTitle(copy[.selectServerDirectory]).navigationBarTitleDisplayMode(.inline)
        .task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }
    }
    private func load() { Task { await loadAsync() } }
    private func loadAsync() async { state = .loading; let path = currentPath; state = await store.load(scope: "directories") { try await store.client.loadServerDirectories(path: path) } }
    private func select(_ path: String) {
        guard purpose == .scanDirectory else { store.selectServerDirectory(path, for: purpose); dismiss(); return }
        Task { if await store.perform(id: "scan-directory", operation: { try await store.client.scanDirectory(path: path) }) { dismiss() } }
    }
}

struct ImportTasksView: View {
    enum Filter: Hashable { case all, active, failed }
    @ObservedObject var store: AdministrativeSettingsStore
    let libraryID: String
    @State private var state: AdministrativeLoadState<[ImportTask]> = .idle
    @State private var filter: Filter = .all
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme
    @Environment(\.administrativeNavigate) private var navigate

    var body: some View {
        VStack(spacing: 0) {
            Picker(copy[.importTasksTitle], selection: $filter) { Text(copy[.all]).tag(Filter.all); Text(copy[.active]).tag(Filter.active); Text(copy[.failed]).tag(Filter.failed) }.pickerStyle(.segmented).padding()
            AdministrativeStateView(state: state, retry: load) { tasks in
                SettingsList {
                    ForEach(filtered(tasks)) { task in
                    VStack(alignment: .leading, spacing: .space1) {
                        Button { navigate(.importTaskDetail(taskID: task.id)) } label: {
                        HStack { Label(task.filename, systemImage: "doc"); Spacer(); Text(status(task.status)).foregroundStyle(task.status == .failed ? .red : theme.textSecondary) }
                        }.buttonStyle(.plain)
                        Text("\(copy[.taskSource]): \(task.sourcePath)").font(.caption).foregroundStyle(theme.textSecondary)
                        Text("\(copy[.taskCreated]): \(task.createdAt.administrativeFormatted(locale: copy.locale))").font(.caption).foregroundStyle(theme.textSecondary)
                        if let progress = task.progress { ProgressView(value: progress).tint(theme.brandAccent) }
                    }.padding(.vertical, .spaceHalf)
                    }
                }.overlay { if filtered(tasks).isEmpty { AdministrativeEmptyView(title: copy[.empty], systemImage: "tray") } }
            }
        }
        .settingsPageSurface()
        .navigationTitle(copy[.importTasksTitle]).navigationBarTitleDisplayMode(.inline)
        .task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func filtered(_ tasks: [ImportTask]) -> [ImportTask] { switch filter { case .all: tasks; case .active: tasks.filter { $0.status == .pending || $0.status == .parsing }; case .failed: tasks.filter { $0.status == .failed } } }
    private func status(_ value: ImportTaskStatus) -> String { switch value { case .pending: copy[.pending]; case .parsing: copy[.parsing]; case .completed: copy[.completed]; case .failed: copy[.failed]; case .cancelled: copy[.cancelled] } }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; state = await store.load(scope: "import-tasks-\(libraryID)") { try await store.client.loadImportTasks(libraryID: libraryID) } }
}

struct ImportTaskDetailView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    let taskID: String
    @State private var state: AdministrativeLoadState<ImportTaskDetail> = .idle
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { detail in
            SettingsList {
                Section {
                    if let libraryName = detail.task.libraryName { LabeledContent(copy[.importLibrary], value: libraryName) }
                    if let bookTitle = detail.task.bookTitle { LabeledContent(copy[.importBook], value: bookTitle) }
                    if let resourceTitle = detail.task.resourceTitle { LabeledContent(copy[.importResource], value: resourceTitle) }
                    if let sourceName = detail.task.sourceName { LabeledContent(copy[.sourceName], value: sourceName) }
                    if let sourceRelativePath = detail.task.sourceRelativePath { LabeledContent(copy[.importSourcePath], value: sourceRelativePath) }
                    LabeledContent(copy[.taskSource], value: detail.task.sourcePath)
                    LabeledContent(copy[.accountStatus], value: importTaskStatus(detail.task.status))
                    LabeledContent(copy[.taskCreated], value: detail.task.createdAt.administrativeFormatted(locale: copy.locale))
                    if let progress = detail.task.progress { ProgressView(value: progress).tint(theme.brandAccent) }
                    if let code = detail.task.errorCode { Text(code).foregroundStyle(.red).textSelection(.enabled) }
                }
                Section(copy[.importTaskLogs]) {
                    ForEach(detail.logs) { log in
                        VStack(alignment: .leading, spacing: .spaceHalf) {
                            HStack { Text(logLevel(log.level)).font(.caption.weight(.semibold)); Spacer(); if let date = log.createdAt { Text(date.administrativeFormatted(locale: copy.locale)).font(.caption).foregroundStyle(theme.textSecondary) } }
                            Text(log.message).textSelection(.enabled)
                        }.padding(.vertical, .spaceHalf)
                    }
                }
            }.overlay { if detail.logs.isEmpty { AdministrativeEmptyView(title: copy[.empty], systemImage: "doc.text") } }
        }
        .navigationTitle(copy[.importTaskDetail]).navigationBarTitleDisplayMode(.inline)
        .task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func load() { Task { await loadAsync() } }
    private func loadAsync() async { state = .loading; state = await store.load(scope: "import-task-\(taskID)") { try await store.client.loadImportTaskDetail(id: taskID) } }
    private func importTaskStatus(_ value: ImportTaskStatus) -> String {
        switch value {
        case .pending: copy[.pending]
        case .parsing: copy[.parsing]
        case .completed: copy[.completed]
        case .failed: copy[.failed]
        case .cancelled: copy[.cancelled]
        }
    }
    private func logLevel(_ value: String) -> String {
        switch value.lowercased() {
        case "info", "information": copy[.information]
        case "warning", "warn": copy[.warning]
        case "error": copy[.error]
        default: copy[.unknown]
        }
    }
}

struct ImportScansView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<[ImportScanJob]> = .idle
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { jobs in
            SettingsList {
                ForEach(jobs) { job in
                VStack(alignment: .leading, spacing: .space1) {
                    HStack { Text(job.path).lineLimit(2); Spacer(); Text(scanStatus(job.status)).foregroundStyle(job.status == .failed ? .red : theme.textSecondary) }
                    if job.isActive { ProgressView().tint(theme.brandAccent) }
                    Grid(alignment: .leading, horizontalSpacing: .space2, verticalSpacing: .spaceHalf) {
                        GridRow { Text(copy[.directoriesScanned]); Text("\(job.directoriesScanned)") }
                        GridRow { Text(copy[.filesScanned]); Text("\(job.filesScanned)") }
                        GridRow { Text(copy[.candidatesFound]); Text("\(job.candidatesFound)") }
                        GridRow { Text(copy[.queuedCount]); Text("\(job.queuedCount)") }
                        GridRow { Text(copy[.errorCount]); Text("\(job.errorCount)") }
                    }.font(.caption).foregroundStyle(theme.textSecondary)
                    if job.isActive { Button(copy[.cancelScan], role: .destructive) { cancel(job) } }
                }.padding(.vertical, .spaceHalf)
                }
            }.overlay { if jobs.isEmpty { AdministrativeEmptyView(title: copy[.empty], systemImage: "magnifyingglass") } }
        }
        .navigationTitle(copy[.scanJobs]).navigationBarTitleDisplayMode(.inline)
        .task { await poll() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func load() { Task { await loadAsync() } }
    private func loadAsync() async { state = .loading; state = await store.load(scope: "import-scans") { try await store.client.loadImportScans() } }
    private func scanStatus(_ value: ImportScanStatus) -> String {
        switch value {
        case .pending: copy[.pending]
        case .running: copy[.running]
        case .completed: copy[.completed]
        case .failed: copy[.failed]
        case .cancelled: copy[.cancelled]
        }
    }
    private func poll() async {
        repeat {
            await loadAsync()
            guard case let .loaded(jobs) = state, jobs.contains(where: \.isActive) else { return }
            do { try await Task.sleep(nanoseconds: 800_000_000) } catch { return }
        } while !Task.isCancelled
    }
    private func cancel(_ job: ImportScanJob) { Task { if await store.perform(id: "cancel-scan-\(job.id)", operation: { try await store.client.cancelImportScan(id: job.id) }) { await poll() } } }
}

struct ImportPreferencesView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<LibraryImportPreferences> = .idle
    @State private var preferences: LibraryImportPreferences?
    @Environment(\.administrativeCopy) private var copy

    private let scanIntervals = [5, 15, 30, 60, 180, 360, 720, 1_440]

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { _ in
            if let binding = Binding($preferences) {
                SettingsForm {
                    Section(header: SettingsSectionHeader(verbatim: copy[.scanning])) {
                        SettingsToggleRow(
                            LocalizedStringKey(copy[.scanningEnabled]),
                            isOn: binding.scan.watchEnabled
                        )
                        SettingsPickerRow(
                            LocalizedStringKey(copy[.scanInterval]),
                            selection: binding.scan.intervalMinutes
                        ) {
                            ForEach(scanIntervals, id: \.self) { minutes in
                                Text(formattedInterval(minutes)).tag(minutes)
                            }
                        }
                    }
                    Section(copy[.fileProcessing]) {
                        SettingsTextInputRow(LocalizedStringKey(copy[.allowedExtensions])) {
                            TextField(
                                LocalizedStringKey(copy[.allowedExtensions]),
                                text: Binding(
                                    get: { binding.wrappedValue.files.allowedExtensions.joined(separator: ", ") },
                                    set: {
                                        binding.wrappedValue.files.allowedExtensions = $0
                                            .split(separator: ",")
                                            .map { $0.trimmingCharacters(in: .whitespaces) }
                                            .filter { !$0.isEmpty }
                                    }
                                )
                            )
                        }
                        SettingsTextInputRow(LocalizedStringKey(copy[.ignorePatterns])) {
                            TextField(LocalizedStringKey(copy[.ignorePatterns]), text: binding.files.ignorePatterns, axis: .vertical)
                        }
                    }
                    Section { Text(copy[.futureTasksHint]).font(.footnote).foregroundStyle(.secondary).listRowInsets(SettingsMetrics.rowInsets) }
                }.administrativeNotice(store: store)
            }
        }
        .navigationTitle(copy[.importPreferencesTitle]).navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if let preferences {
                ToolbarItem(placement: .confirmationAction) {
                    AdministrativeToolbarAction(
                        title: copy[.save],
                        working: store.operationInFlight == "save-library-scan" || store.operationInFlight == "save-import-preferences",
                        disabled: store.operationInFlight != nil
                    ) { save(preferences) }
                }
            }
        }
        .task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }
    }
    private func load() { Task { await loadAsync() } }
    private func loadAsync() async {
        state = .loading
        let loaded = await store.load(scope: "import-preferences") {
            async let scan = store.client.loadLibraryScanSettings()
            async let files = store.client.loadImportPreferences()
            let values = try await (scan, files)
            return LibraryImportPreferences(scan: values.0, files: values.1)
        }
        state = loaded
        if case let .loaded(value) = loaded { preferences = value }
    }
    private func save(_ value: LibraryImportPreferences) {
        Task {
            let scanResult = await store.performValue(id: "save-library-scan") {
                try await store.client.saveLibraryScanSettings(value.scan)
            }
            guard case let .success(updatedScan) = scanResult else { return }
            let filesResult = await store.performValue(id: "save-import-preferences") {
                try await store.client.saveImportPreferences(value.files)
            }
            guard case let .success(updatedFiles) = filesResult else { return }
            let updated = LibraryImportPreferences(scan: updatedScan, files: updatedFiles)
            preferences = updated
            state = .loaded(updated)
        }
    }
    private func formattedInterval(_ minutes: Int) -> String {
        Measurement(value: Double(minutes), unit: UnitDuration.minutes)
            .formatted(.measurement(width: .abbreviated).locale(Locale(identifier: copy.locale.rawValue)))
    }
}
