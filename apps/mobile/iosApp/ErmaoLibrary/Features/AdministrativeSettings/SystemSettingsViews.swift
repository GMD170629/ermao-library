import SwiftUI
import UniformTypeIdentifiers
import UIKit

struct OPDSSettingsView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<OPDSConfiguration> = .idle
    @State private var configuration: OPDSConfiguration?
    @State private var initialConfiguration: OPDSConfiguration?
    @State private var disableShown = false
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { _ in
            if let binding = Binding($configuration) {
                SettingsForm {
                    Section(copy[.serviceStatus]) {
                        SettingsToggleRow(
                            LocalizedStringKey(copy[.opdsEnabled]),
                            isOn: Binding(
                                get: { binding.wrappedValue.enabled },
                                set: { enabled in
                                    if !enabled && binding.wrappedValue.enabled { disableShown = true }
                                    else { binding.enabled.wrappedValue = enabled }
                                }
                            )
                        )
                        .disabled(store.operationInFlight != nil)
                        AdministrativeStatusLabel(title: binding.wrappedValue.running ? copy[.running] : copy[.stopped], status: binding.wrappedValue.running ? .good : .neutral)
                    }
                    Section(copy[.publicBaseURL]) {
                        SettingsTextInputRow(LocalizedStringKey(copy[.publicBaseURL])) {
                            TextField(LocalizedStringKey(copy[.publicBaseURL]), text: binding.publicBaseURL)
                                .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                        }
                        if let catalog = binding.wrappedValue.catalogURL {
                            SettingsValueRow(LocalizedStringKey(copy[.catalogURL]), value: catalog)
                            SettingsActionRow(LocalizedStringKey(copy[.copy])) {
                                UIPasteboard.general.string = catalog
                                store.replaceNotice(AdministrativeNotice(style: .success, message: copy[.copied]))
                            }
                        }
                    }
                    Section { Text(copy[.opdsInstructions]).appTextStyle(.callout).foregroundStyle(theme.textSecondary) }
                }.administrativeNotice(store: store)
            }
        }.navigationTitle(copy[.opdsTitle]).navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if let configuration {
                ToolbarItem(placement: .confirmationAction) {
                    AdministrativeToolbarAction(
                        title: copy[.save],
                        working: store.operationInFlight == "save-opds",
                        disabled: saveIsDisabled
                    ) { save(configuration) }
                }
            }
        }
        .confirmationDialog(copy[.disableOPDSTitle], isPresented: $disableShown, titleVisibility: .visible) {
            Button(copy[.disableService], role: .destructive) {
                confirmDisable()
            }
            .disabled(store.operationInFlight != nil)
            Button(copy[.cancel], role: .cancel) {}
        } message: { Text(copy[.disableOPDSMessage]) }
        .task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }
    }
    private var saveIsDisabled: Bool {
        guard let configuration, let initialConfiguration else { return true }
        return store.operationInFlight != nil || configuration == initialConfiguration || configuration.publicBaseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; let loaded = await store.load(scope: "opds") { try await store.client.loadOPDSConfiguration() }; state = loaded; if case let .loaded(value) = loaded { configuration = value; initialConfiguration = value } }
    private func save(_ value: OPDSConfiguration) {
        guard store.operationInFlight == nil else { return }
        Task {
            let result = await store.performValue(id: "save-opds") { try await store.client.saveOPDSConfiguration(value) }
            if case let .success(updated) = result {
                configuration = updated
                initialConfiguration = updated
                state = .loaded(updated)
            }
        }
    }
    private func confirmDisable() {
        guard var value = configuration, store.operationInFlight == nil else { return }
        value.enabled = false
        save(value)
    }
}

struct BackupsView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<[BackupRecord]> = .idle
    @State private var selectedBackup: BackupRecord?
    @State private var restoreBackup: BackupRecord?
    @State private var deleteBackup: BackupRecord?
    @State private var confirmation = ""
    @State private var exportDocument: ActivityFileDocument?
    @State private var exportFilename = "backup.zip"
    @State private var exporting = false
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme
    @Environment(\.administrativeNavigate) private var navigate

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { backups in
            SettingsList {
                ForEach(backups) { backup in
                    VStack(alignment: .leading, spacing: .space1) {
                        HStack {
                            Label(backup.filename, systemImage: "doc.zipper")
                            Spacer()
                            Menu {
                                Button(copy[.downloadFile]) { prepareExport(backup) }
                                    .disabled(store.operationInFlight != nil)
                                Button(copy[.restoreBackup]) { restoreBackup = backup }
                                    .disabled(store.operationInFlight != nil)
                                Button(copy[.deleteBackup], role: .destructive) { deleteBackup = backup }
                                    .disabled(store.operationInFlight != nil)
                            } label: {
                                Image(systemName: "ellipsis")
                            }
                            .disabled(store.operationInFlight != nil)
                        }
                        Text("\(backupKind(backup.kind)) · \(backup.sizeBytes.administrativeByteCount) · \(backup.createdAt.administrativeFormatted(locale: copy.locale))").font(.caption).foregroundStyle(theme.textSecondary)
                        Text("\(backup.bookCount) \(copy[.backupBookCount]) · \(backup.progressCount) \(copy[.backupProgressCount]) · \(backup.libraryCount) \(copy[.backupLibraryCount])").font(.caption).foregroundStyle(theme.textSecondary)
                    }.padding(.vertical, .spaceHalf)
                }
                Section {
                    SettingsNavigationRow(
                        LocalizedStringKey(copy[.workDetailOrder]),
                        systemImage: "arrow.up.arrow.down"
                    ) { navigate(.workDetailOrder) }
                }
            }
            .overlay { if backups.isEmpty { AdministrativeEmptyView(title: copy[.empty], systemImage: "externaldrive") } }
        }.navigationTitle(copy[.backupsTitle]).navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Button(copy[.createBackup], action: create).disabled(store.operationInFlight != nil) } }
        .sheet(item: $restoreBackup) { backup in restoreSheet(backup) }
        .confirmationDialog(copy[.deleteBackupTitle], isPresented: Binding(get: { deleteBackup != nil }, set: { if !$0 { deleteBackup = nil } }), titleVisibility: .visible) {
            if let backup = deleteBackup {
                Button(copy[.deleteBackup], role: .destructive) { delete(backup) }
                    .disabled(store.operationInFlight != nil)
            }
            Button(copy[.cancel], role: .cancel) {}
        } message: { Text(copy[.deleteBackupMessage]) }
        .fileExporter(isPresented: $exporting, document: exportDocument, contentType: .zip, defaultFilename: exportFilename) { _ in exportDocument = nil }
        .task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func restoreSheet(_ backup: BackupRecord) -> some View {
        NavigationStack {
            SettingsForm {
                Section {
                    Text(copy[.restoreWarning]).foregroundStyle(.orange).listRowInsets(SettingsMetrics.rowInsets)
                    SettingsTextInputRow(LocalizedStringKey(copy[.enterRestore])) {
                        TextField(LocalizedStringKey(copy[.enterRestore]), text: $confirmation)
                            .textInputAutocapitalization(.characters)
                    }
                }
            }
                .navigationTitle(copy[.restoreBackup]).navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button(copy[.cancel]) { restoreBackup = nil; confirmation = "" }
                            .disabled(store.operationInFlight != nil)
                    }
                    ToolbarItem(placement: .confirmationAction) {
                        Button(copy[.restore], role: .destructive) { restore(backup) }
                            .disabled(confirmation != "RESTORE" || store.operationInFlight != nil)
                    }
                }
        }.environment(\.administrativeCopy, copy).tint(theme.actionAccent)
    }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; state = await store.load(scope: "backups") { try await store.client.loadBackups() } }
    private func backupKind(_ value: String) -> String {
        switch value.lowercased() {
        case "automatic": copy[.automatic]
        case "manual": copy[.manual]
        default: copy[.unknown]
        }
    }
    private func create() {
        guard store.operationInFlight == nil else { return }
        Task {
            let result = await store.performValue(id: "create-backup") { try await store.client.createBackup() }
            if case .success = result { await loadAsync() }
        }
    }
    private func prepareExport(_ backup: BackupRecord) {
        guard store.operationInFlight == nil else { return }
        Task {
            let result = await store.performValue(id: "download-backup") { try await store.client.prepareBackupExport(id: backup.id) }
            if case let .success(file) = result {
                exportDocument = ActivityFileDocument(data: file.data)
                exportFilename = file.filename
                exporting = true
            }
        }
    }
    private func restore(_ backup: BackupRecord) {
        guard confirmation == "RESTORE", store.operationInFlight == nil else { return }
        Task {
            if await store.perform(id: "restore-backup", operation: { try await store.client.restoreBackup(id: backup.id, confirmation: confirmation) }) {
                restoreBackup = nil
                confirmation = ""
                await loadAsync()
            }
        }
    }
    private func delete(_ backup: BackupRecord) {
        guard store.operationInFlight == nil else { return }
        deleteBackup = nil
        Task { if await store.perform(id: "delete-backup", operation: { try await store.client.deleteBackup(id: backup.id) }) { await loadAsync() } }
    }
}

struct WorkDetailOrderView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<[AdministrativeWorkDetailSection]> = .idle
    @State private var order: [AdministrativeWorkDetailSection] = []
    @Environment(\.administrativeCopy) private var copy

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { _ in
            SettingsList {
                Section { Text(copy[.workOrderHint]).font(.footnote).foregroundStyle(.secondary).listRowInsets(SettingsMetrics.rowInsets) }
                Section {
                    SettingsActionRow(LocalizedStringKey(copy[.restoreDefault])) { order = AdministrativeWorkDetailSection.allCases }
                    ForEach(Array(order.enumerated()), id: \.element) { index, item in
                        HStack {
                            SettingsIcon(systemImage: "line.3.horizontal")
                            Text("\(index + 1)")
                            Text(title(item))
                            Spacer()
                            Button { move(index, -1) } label: { Image(systemName: "chevron.up") }.disabled(index == 0)
                            Button { move(index, 1) } label: { Image(systemName: "chevron.down") }.disabled(index == order.count - 1)
                        }
                        .frame(minHeight: SettingsMetrics.rowContentMinimumHeight)
                        .listRowInsets(SettingsMetrics.rowInsets)
                    }
                }
            }.administrativeNotice(store: store)
        }.navigationTitle(copy[.workOrderTitle]).navigationBarTitleDisplayMode(.inline).task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                AdministrativeToolbarAction(
                    title: copy[.saveOrder],
                    working: store.operationInFlight == "save-work-order",
                    disabled: order.isEmpty || store.operationInFlight != nil,
                    action: save
                )
            }
        }
    }
    private func title(_ value: AdministrativeWorkDetailSection) -> String { switch value { case .ebook: copy[.ebook]; case .comic: copy[.comic]; case .audiobook: copy[.audiobook]; case .chaptersAndContent: copy[.chaptersContent] } }
    private func move(_ index: Int, _ delta: Int) { order.swapAt(index, index + delta) }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; let loaded = await store.load(scope: "work-order") { try await store.client.loadWorkDetailOrder() }; state = loaded; if case let .loaded(value) = loaded { order = value } }
    private func save() {
        guard store.operationInFlight == nil else { return }
        let value = order
        Task {
            let result = await store.performValue(id: "save-work-order") { try await store.client.saveWorkDetailOrder(value) }
            if case let .success(updated) = result {
                order = updated
                state = .loaded(updated)
            }
        }
    }
}

struct SystemHealthView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<SystemHealthSnapshot> = .idle
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { snapshot in
            SettingsList {
                Section {
                    if let checked = snapshot.checkedAt { SettingsValueRow(LocalizedStringKey(copy[.lastChecked]), value: checked.administrativeFormatted(locale: copy.locale)) }
                    SettingsActionRow(LocalizedStringKey(copy[.runHealthCheck])) { runCheck() }
                        .disabled(store.operationInFlight != nil)
                }
                ForEach(groups(snapshot.components), id: \.0) { group, components in Section(copy.healthText(groupTitleCode(group))) { ForEach(components) { component in HStack { VStack(alignment: .leading) { Text(copy.healthText(component.name)); if let detail = component.detail { Text(copy.healthText(detail)).font(.caption).foregroundStyle(theme.textSecondary) } }; Spacer(); AdministrativeStatusLabel(title: status(component.status), status: component.status == .healthy ? .good : component.status == .warning ? .warning : component.status == .failed ? .failed : .neutral) } } } }
            }
        }.navigationTitle(copy[.healthTitle]).navigationBarTitleDisplayMode(.inline)
        .task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func groups(_ values: [HealthComponent]) -> [(String, [HealthComponent])] { Dictionary(grouping: values, by: \.group).sorted { $0.key < $1.key } }
    private func groupTitleCode(_ group: String) -> String {
        switch group {
        case "storage": "health.group.storage"
        case "queues": "health.group.queues"
        case "configuration": "health.group.configuration"
        default: group
        }
    }
    private func status(_ value: HealthStatus) -> String { switch value { case .healthy: copy[.healthy]; case .warning: copy[.warning]; case .failed: copy[.failed]; case .checking: copy[.checking] } }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; state = await store.load(scope: "health") { try await store.client.loadSystemHealth() } }
    private func runCheck() {
        guard store.operationInFlight == nil else { return }
        Task {
            let result = await store.performValue(id: "health-check") { try await store.client.runSystemHealthCheck() }
            if case let .success(updated) = result { state = .loaded(updated) }
        }
    }
}

struct SystemLogsView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<LogPage> = .idle
    @State private var filter = LogFilter(query: "", levels: Set(LogLevel.allCases), source: nil, since: Calendar.current.date(byAdding: .day, value: -7, to: Date()))
    @State private var settings = LogSettings(limitMegabytes: 50)
    @State private var initialSettings: LogSettings?
    @State private var manageShown = false
    @State private var clearShown = false
    @State private var exportDocument: ActivityFileDocument?
    @State private var exporting = false
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { page in
            SettingsList {
                Section {
                    SettingsValueRow(LocalizedStringKey(copy[.logCapacity]), value: "\(page.usedBytes.administrativeByteCount) / \(page.limitBytes.administrativeByteCount)", systemImage: "doc")
                    ProgressView(value: Double(page.usedBytes), total: Double(max(page.limitBytes, 1))).tint(theme.brandAccent)
                    SettingsActionRow(LocalizedStringKey(copy[.manageLogs])) { manageShown = true }
                        .disabled(store.operationInFlight != nil)
                }
                ForEach(page.events) { event in
                    DisclosureGroup { if let correlationID = event.correlationID { LabeledContent(copy[.correlationID], value: correlationID) }; if let target = event.target { LabeledContent(copy[.targetCategory], value: target) } } label: { VStack(alignment: .leading, spacing: .spaceHalf) { HStack { Text(event.timestamp.administrativeFormatted(locale: copy.locale)).font(.caption).foregroundStyle(theme.textSecondary); Text(level(event.level)).font(.caption).foregroundStyle(event.level == .error ? .red : event.level == .warning ? .orange : .blue); Text(event.source).font(.caption) }; Text(event.summary) } }
                }
            }.overlay { if page.events.isEmpty { AdministrativeEmptyView(title: copy[.noResults], systemImage: "doc.text.magnifyingglass") } }
        }.navigationTitle(copy[.logsTitle]).navigationBarTitleDisplayMode(.inline).searchable(text: $filter.query, prompt: copy[.searchLogs]).onSubmit(of: .search, load)
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Menu { ForEach(LogLevel.allCases, id: \.self) { levelValue in Toggle(level(levelValue), isOn: Binding(get: { filter.levels.contains(levelValue) }, set: { enabled in if enabled { filter.levels.insert(levelValue) } else { filter.levels.remove(levelValue) }; load() })) } } label: { Image(systemName: "line.3.horizontal.decrease.circle") } } }
        .sheet(isPresented: $manageShown) { manageSheet }
        .confirmationDialog(copy[.clearLogsTitle], isPresented: $clearShown, titleVisibility: .visible) {
            Button(copy[.clearAllLogs], role: .destructive, action: clear)
                .disabled(store.operationInFlight != nil)
            Button(copy[.cancel], role: .cancel) {}
        } message: { Text(copy[.clearLogsMessage]) }
        .fileExporter(isPresented: $exporting, document: exportDocument, contentType: .commaSeparatedText, defaultFilename: "management-logs.csv") { _ in exportDocument = nil }
        .task { await loadAll() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private var manageSheet: some View {
        NavigationStack {
            SettingsForm {
                Section(copy[.logCapacity]) {
                    SettingsFieldRow(LocalizedStringKey(copy[.capacityMegabytes])) {
                        Stepper(
                            "\(settings.limitMegabytes)",
                            value: $settings.limitMegabytes,
                            in: AdministrativeInputValidation.logMegabytesRange,
                            step: 1
                        )
                    }
                    .disabled(store.operationInFlight != nil)
                }
                Section {
                    SettingsActionRow(LocalizedStringKey(copy[.exportFiltered])) { export() }
                        .disabled(store.operationInFlight != nil)
                    SettingsActionRow(LocalizedStringKey(copy[.clearAllLogs]), role: .destructive) { manageShown = false; clearShown = true }
                        .disabled(store.operationInFlight != nil)
                }
            }
            .navigationTitle(copy[.manageLogs])
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(copy[.close]) { manageShown = false } }
                ToolbarItem(placement: .confirmationAction) {
                    AdministrativeToolbarAction(
                        title: copy[.saveCapacity],
                        working: store.operationInFlight == "save-log-settings",
                        disabled: logSaveIsDisabled,
                        action: saveSettings
                    )
                }
            }
        }
        .environment(\.administrativeCopy, copy)
        .tint(theme.actionAccent)
        .administrativeNotice(store: store)
    }
    private var logSaveIsDisabled: Bool {
        guard let initialSettings else { return true }
        return store.operationInFlight != nil || settings == initialSettings
    }
    private func level(_ value: LogLevel) -> String { switch value { case .information: copy[.information]; case .warning: copy[.warning]; case .error: copy[.failed] } }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { let request = filter; state = .loading; state = await store.load(scope: "logs") { try await store.client.loadLogs(filter: request) } }; private func loadAll() async { async let page: Void = loadAsync(); if let loaded = await store.loadValue(scope: "log-settings", operation: { try await store.client.loadLogSettings() }) { settings = loaded; initialSettings = loaded }; _ = await page }
    private func saveSettings() {
        guard let originalSettings = initialSettings, settings != originalSettings, store.operationInFlight == nil else { return }
        let value = settings
        Task {
            let result = await store.performValue(id: "save-log-settings") { try await store.client.saveLogSettings(value) }
            if case let .success(updated) = result {
                settings = updated
                initialSettings = updated
                await loadAsync()
                manageShown = false
            }
        }
    }
    private func export() {
        guard store.operationInFlight == nil else { return }
        let request = filter
        Task {
            let result = await store.performValue(id: "export-logs") { try await store.client.prepareLogExport(filter: request) }
            if case let .success(file) = result {
                exportDocument = ActivityFileDocument(data: file.data)
                manageShown = false
                exporting = true
            }
        }
    }
    private func clear() {
        guard store.operationInFlight == nil else { return }
        Task { if await store.perform(id: "clear-logs", operation: { try await store.client.clearLogs() }) { await loadAsync() } }
    }
}

struct AdministrativeAboutView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<AdministrativeAbout> = .idle
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { about in
            SettingsList {
                Section {
                    VStack(spacing: .space1) {
                        Image("BrandMark").resizable().scaledToFit().frame(width: 72, height: 72).accessibilityHidden(true)
                        Text(copy[.aboutTitle]).appTextStyle(.title)
                        Text(copy[.selfHosted]).multilineTextAlignment(.center).foregroundStyle(theme.textSecondary)
                    }.frame(maxWidth: .infinity).padding(.vertical, .space2)
                }
                Section {
                    SettingsValueRow(LocalizedStringKey(copy[.appVersion]), value: "\(about.appVersion) (\(about.appBuild))")
                    SettingsValueRow(LocalizedStringKey(copy[.serverVersion]), value: about.serverVersion)
                }
                Section {
                    SettingsValueRow(LocalizedStringKey(copy[.supportedFormats]), value: about.supportedFormats.map(formatName).joined(separator: ", "))
                    SettingsValueRow(LocalizedStringKey(copy[.openSourceLicense]), value: about.license)
                    SettingsValueRow(LocalizedStringKey(copy[.operationMode]), value: copy[.selfHosted])
                }
                Section(copy[.releaseHistory]) {
                    ForEach(about.releases) { release in
                        DisclosureGroup {
                            Text(release.notes)
                        } label: {
                            HStack {
                                Text(release.version)
                                Spacer()
                                if let date = release.date {
                                    Text(date.formatted(.dateTime.year().month().day())).foregroundStyle(theme.textSecondary)
                                }
                            }
                        }
                    }
                }
                if let url = about.repositoryURL {
                    Section(copy[.projectAddress]) {
                        Text(url.absoluteString).textSelection(.enabled)
                        HStack {
                            Button {
                                UIPasteboard.general.string = url.absoluteString
                                store.replaceNotice(AdministrativeNotice(style: .success, message: copy[.copied]))
                            } label: { Label(copy[.copy], systemImage: "doc.on.doc") }
                            Spacer()
                            ShareLink(item: url) { Label(copy[.share], systemImage: "square.and.arrow.up") }
                        }
                    }
                }
            }
        }
        .navigationTitle(copy[.aboutTitle])
        .navigationBarTitleDisplayMode(.inline)
        .task { await loadAsync() }
        .onDisappear { store.cancelPendingRequests() }
        .administrativeNotice(store: store)
    }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; state = await store.load(scope: "administrative-about") { try await store.client.loadAbout() } }
    private func formatName(_ value: String) -> String {
        switch value.lowercased() {
        case "comic": copy[.comic]
        case "text": copy[.plainText]
        case "audiobook": copy[.audiobook]
        default: value
        }
    }
}
