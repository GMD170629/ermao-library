import SwiftUI

struct LibrarySourcesView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<LibrarySourcesSnapshot> = .idle
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme
    @Environment(\.administrativeNavigate) private var navigate

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { snapshot in
            List {
                if let storage = snapshot.storage {
                    Section {
                        Label {
                            VStack(alignment: .leading, spacing: .spaceHalf) {
                                Text(storage.label)
                                Text(storage.path).appTextStyle(.caption).foregroundStyle(theme.textSecondary)
                                if let free = storage.freeBytes, let total = storage.totalBytes {
                                    Text("\(copy[.availableSpace]) \(free.administrativeByteCount) / \(total.administrativeByteCount)").appTextStyle(.caption).foregroundStyle(theme.textSecondary)
                                }
                            }
                        } icon: { Image(systemName: "externaldrive") }
                    }
                }
                Section(copy[.libraries]) {
                    ForEach(snapshot.sources) { source in
                        Button { navigate(.librarySourceEditor(sourceID: source.id)) } label: { sourceRow(source) }.buttonStyle(.plain)
                    }
                }
                Section {
                    Button { navigate(.serverDirectoryPicker(purpose: .scanDirectory)) } label: {
                        Label(copy[.scanDirectory], systemImage: "magnifyingglass")
                    }
                }
                if let scan = snapshot.activeScan { scanRow(scan) }
            }
            .administrativeListSurface()
        }
        .navigationTitle(copy[.sourcesTitle]).navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Button(copy[.add]) { navigate(.librarySourceEditor(sourceID: nil)) } } }
        .refreshable { await loadAsync() }.task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func sourceRow(_ source: LibrarySource) -> some View {
        Label {
            HStack {
                VStack(alignment: .leading, spacing: .spaceHalf) { Text(source.displayName).appTextStyle(.headline); Text(source.serverPath).appTextStyle(.caption).foregroundStyle(theme.textSecondary) }
                Spacer()
                Text(source.enabled ? copy[.enabled] : copy[.disabled]).foregroundStyle(source.enabled ? .green : theme.textSecondary)
            }
        } icon: { Image(systemName: "folder") }
        .padding(.vertical, .spaceHalf)
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
        Form {
            Section {
                TextField(copy[.sourceName], text: $source.displayName)
                LabeledContent(copy[.serverPath]) { Text(source.serverPath.isEmpty ? "—" : source.serverPath).textSelection(.enabled) }
                Button(copy[.browseDirectory]) { navigate(.serverDirectoryPicker(purpose: sourceID.map(ServerDirectoryPurpose.updateSource) ?? .createSource)) }
            }
            Section {
                Toggle(copy[.monitorEnabled], isOn: $source.enabled)
                Toggle(copy[.ignoreHiddenFiles], isOn: $source.ignoreHidden)
                TextField(copy[.ignorePatterns], text: $source.ignorePatterns)
                TextField(copy[.minimumFileSize], value: $source.minimumFileSizeBytes, format: .number).keyboardType(.numberPad)
                TextField(copy[.sourceDescription], text: $source.description, axis: .vertical)
            }
            Section(copy[.organizationMode]) {
                Picker(copy[.organizationMode], selection: $source.organizationMode) {
                    ForEach(LibraryOrganizationMode.allCases, id: \.self) { mode in
                        Text(organizationModeTitle(mode)).tag(mode)
                    }
                }
            }
            if sourceID != nil { Section { Button(copy[.rescan]) { rescan() } } }
            if sourceID != nil { Section { Button(copy[.deleteSource], role: .destructive) { deleteShown = true } } }
        }
        .administrativeListSurface().navigationTitle(sourceID == nil ? copy[.add] : copy[.edit]).navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Button(copy[.save], action: save).disabled(source.displayName.isEmpty || source.serverPath.isEmpty || store.operationInFlight != nil) } }
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
    private func rescan() { guard let sourceID else { return }; Task { _ = await store.perform(id: "rescan-source") { try await store.client.rescanLibrarySource(id: sourceID) } } }
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
            List {
                Section { Text(page.currentPath).textSelection(.enabled).foregroundStyle(theme.textSecondary) }
                Section {
                    ForEach(page.directories) { entry in
                        Button { currentPath = entry.absolutePath; load() } label: {
                            Label { VStack(alignment: .leading) { Text(entry.isParent ? copy[.parentDirectory] : entry.name); if let modified = entry.modifiedAt { Text(modified.administrativeFormatted(locale: copy.locale)).font(.caption).foregroundStyle(theme.textSecondary) } } } icon: { Image(systemName: entry.isParent ? "arrow.up.doc" : "folder") }
                        }
                    }
                }
            }
            .administrativeListSurface()
            .safeAreaInset(edge: .bottom) { AdministrativeBottomAction(title: purpose == .scanDirectory ? copy[.scanDirectory] : copy[.chooseDirectory], disabled: page.currentPath.isEmpty, action: { select(page.currentPath) }) }
        }
        .navigationTitle(copy[.selectServerDirectory]).navigationBarTitleDisplayMode(.inline)
        .task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
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
    @State private var state: AdministrativeLoadState<[ImportTask]> = .idle
    @State private var filter: Filter = .all
    @State private var deleteTask: ImportTask?
    @State private var clearShown = false
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme
    @Environment(\.administrativeNavigate) private var navigate

    var body: some View {
        VStack(spacing: 0) {
            Picker(copy[.importTasksTitle], selection: $filter) { Text(copy[.all]).tag(Filter.all); Text(copy[.active]).tag(Filter.active); Text(copy[.failed]).tag(Filter.failed) }.pickerStyle(.segmented).padding()
            AdministrativeStateView(state: state, retry: load) { tasks in
                List(filtered(tasks)) { task in
                    VStack(alignment: .leading, spacing: .space1) {
                        Button { navigate(.importTaskDetail(taskID: task.id)) } label: {
                        HStack { Label(task.filename, systemImage: "doc"); Spacer(); Text(status(task.status)).foregroundStyle(task.status == .failed ? .red : theme.textSecondary) }
                        }.buttonStyle(.plain)
                        Text("\(copy[.taskSource]): \(task.sourcePath)").font(.caption).foregroundStyle(theme.textSecondary)
                        Text("\(copy[.taskCreated]): \(task.createdAt.administrativeFormatted(locale: copy.locale))").font(.caption).foregroundStyle(theme.textSecondary)
                        if let progress = task.progress { ProgressView(value: progress).tint(theme.brandAccent) }
                        HStack { Spacer(); if task.status == .failed { Button(copy[.retry]) { mutate("retry-\(task.id)") { try await store.client.retryImportTask(id: task.id) } }; Button(copy[.delete], role: .destructive) { deleteTask = task } } }.buttonStyle(.borderless)
                    }.padding(.vertical, .spaceHalf)
                }.listStyle(.plain).administrativeListSurface().overlay { if filtered(tasks).isEmpty { AdministrativeEmptyView(title: copy[.empty], systemImage: "tray") } }
            }
        }
        .navigationTitle(copy[.importTasksTitle]).navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Menu { Button(copy[.scanJobs]) { navigate(.importScans) }; Button(copy[.rescanAll]) { mutate("rescan-all") { try await store.client.rescanAllLibrarySources() } }; Button(copy[.clearCompleted], role: .destructive) { clearShown = true } } label: { Image(systemName: "ellipsis") } } }
        .confirmationDialog(copy[.deleteImportTitle], isPresented: Binding(get: { deleteTask != nil }, set: { if !$0 { deleteTask = nil } }), titleVisibility: .visible) { if let task = deleteTask { Button(copy[.delete], role: .destructive) { deleteTask = nil; mutate("delete-\(task.id)") { try await store.client.deleteImportTask(id: task.id) } } }; Button(copy[.cancel], role: .cancel) {} } message: { Text(copy[.deleteImportMessage]) }
        .confirmationDialog(copy[.clearCompleted], isPresented: $clearShown, titleVisibility: .visible) { Button(copy[.clearCompleted], role: .destructive) { mutate("clear-imports") { try await store.client.clearCompletedImportTasks() } }; Button(copy[.cancel], role: .cancel) {} }
        .task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func filtered(_ tasks: [ImportTask]) -> [ImportTask] { switch filter { case .all: tasks; case .active: tasks.filter { $0.status == .pending || $0.status == .parsing }; case .failed: tasks.filter { $0.status == .failed } } }
    private func status(_ value: ImportTaskStatus) -> String { switch value { case .pending: copy[.pending]; case .parsing: copy[.parsing]; case .completed: copy[.completed]; case .failed: copy[.failed]; case .cancelled: copy[.cancelled] } }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; state = await store.load(scope: "import-tasks") { try await store.client.loadImportTasks(status: nil) } }
    private func mutate(_ id: String, operation: @escaping @Sendable () async throws -> Void) { Task { if await store.perform(id: id, operation: operation) { await loadAsync() } } }
}

struct ImportTaskDetailView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    let taskID: String
    @State private var state: AdministrativeLoadState<ImportTaskDetail> = .idle
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { detail in
            List {
                Section {
                    LabeledContent(copy[.taskSource], value: detail.task.sourcePath)
                    LabeledContent(copy[.accountStatus], value: detail.task.status.rawValue)
                    LabeledContent(copy[.taskCreated], value: detail.task.createdAt.administrativeFormatted(locale: copy.locale))
                    if let progress = detail.task.progress { ProgressView(value: progress).tint(theme.brandAccent) }
                    if let code = detail.task.errorCode { Text(code).foregroundStyle(.red).textSelection(.enabled) }
                }
                Section(copy[.importTaskLogs]) {
                    ForEach(detail.logs) { log in
                        VStack(alignment: .leading, spacing: .spaceHalf) {
                            HStack { Text(log.level.uppercased()).font(.caption.weight(.semibold)); Spacer(); if let date = log.createdAt { Text(date.administrativeFormatted(locale: copy.locale)).font(.caption).foregroundStyle(theme.textSecondary) } }
                            Text(log.message).textSelection(.enabled)
                        }.padding(.vertical, .spaceHalf)
                    }
                }
            }.administrativeListSurface().overlay { if detail.logs.isEmpty { AdministrativeEmptyView(title: copy[.empty], systemImage: "doc.text") } }
        }
        .navigationTitle(copy[.importTaskDetail]).navigationBarTitleDisplayMode(.inline)
        .task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func load() { Task { await loadAsync() } }
    private func loadAsync() async { state = .loading; state = await store.load(scope: "import-task-\(taskID)") { try await store.client.loadImportTaskDetail(id: taskID) } }
}

struct ImportScansView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<[ImportScanJob]> = .idle
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { jobs in
            List(jobs) { job in
                VStack(alignment: .leading, spacing: .space1) {
                    HStack { Text(job.path).lineLimit(2); Spacer(); Text(job.status.rawValue).foregroundStyle(job.status == .failed ? .red : theme.textSecondary) }
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
            }.administrativeListSurface().overlay { if jobs.isEmpty { AdministrativeEmptyView(title: copy[.empty], systemImage: "magnifyingglass") } }
        }
        .navigationTitle(copy[.scanJobs]).navigationBarTitleDisplayMode(.inline)
        .task { await poll() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func load() { Task { await loadAsync() } }
    private func loadAsync() async { state = .loading; state = await store.load(scope: "import-scans") { try await store.client.loadImportScans() } }
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
    @State private var state: AdministrativeLoadState<ImportPreferences> = .idle
    @State private var preferences: ImportPreferences?
    @Environment(\.administrativeCopy) private var copy

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { _ in
            if let binding = Binding($preferences) {
                Form {
                    Section(copy[.fileProcessing]) {
                        Toggle(copy[.stabilityCheck], isOn: binding.stabilityCheckEnabled)
                        LabeledContent(copy[.stabilitySeconds]) { TextField(copy[.seconds], value: binding.stabilitySeconds, format: .number).keyboardType(.decimalPad).multilineTextAlignment(.trailing) }
                        TextField(copy[.allowedExtensions], text: Binding(get: { binding.wrappedValue.allowedExtensions.joined(separator: ", ") }, set: { binding.wrappedValue.allowedExtensions = $0.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty } }))
                        TextField(copy[.ignorePatterns], text: binding.ignorePatterns, axis: .vertical)
                    }
                    Section { Text(copy[.futureTasksHint]).font(.footnote) }
                }.administrativeListSurface().safeAreaInset(edge: .bottom) { AdministrativeBottomAction(title: copy[.save], working: store.operationInFlight == "save-import-preferences") { save(binding.wrappedValue) } }
            }
        }
        .navigationTitle(copy[.importPreferencesTitle]).navigationBarTitleDisplayMode(.inline).task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; let loaded = await store.load(scope: "import-preferences") { try await store.client.loadImportPreferences() }; state = loaded; if case let .loaded(value) = loaded { preferences = value } }
    private func save(_ value: ImportPreferences) { Task { let result = await store.performValue(id: "save-import-preferences") { try await store.client.saveImportPreferences(value) }; if case let .success(updated) = result { preferences = updated; state = .loaded(updated) } } }
}
