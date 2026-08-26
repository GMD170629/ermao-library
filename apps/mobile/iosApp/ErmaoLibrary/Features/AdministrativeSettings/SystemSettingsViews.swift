import SwiftUI
import UniformTypeIdentifiers
import UIKit

struct OPDSSettingsView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<OPDSConfiguration> = .idle
    @State private var configuration: OPDSConfiguration?
    @State private var disableShown = false
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { _ in
            if let binding = Binding($configuration) {
                Form {
                    Section(copy[.serviceStatus]) {
                        Toggle(copy[.opdsEnabled], isOn: Binding(get: { binding.wrappedValue.enabled }, set: { enabled in if !enabled && binding.wrappedValue.enabled { disableShown = true } else { binding.enabled.wrappedValue = enabled } }))
                        AdministrativeStatusLabel(title: binding.wrappedValue.running ? copy[.running] : copy[.stopped], status: binding.wrappedValue.running ? .good : .neutral)
                    }
                    Section(copy[.publicBaseURL]) {
                        TextField(copy[.publicBaseURL], text: binding.publicBaseURL).keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                        if let catalog = binding.wrappedValue.catalogURL {
                            LabeledContent(copy[.catalogURL]) { Text(catalog).multilineTextAlignment(.trailing).textSelection(.enabled) }
                            Button { UIPasteboard.general.string = catalog; store.replaceNotice(AdministrativeNotice(style: .success, message: copy[.copied])) } label: { Label(copy[.copy], systemImage: "doc.on.doc") }.frame(maxWidth: .infinity)
                        }
                    }
                    Section { Text(copy[.opdsInstructions]).appTextStyle(.callout).foregroundStyle(theme.textSecondary) }
                }.administrativeListSurface().safeAreaInset(edge: .bottom) { AdministrativeBottomAction(title: copy[.save], working: store.operationInFlight == "save-opds") { save(binding.wrappedValue) } }
            }
        }.navigationTitle(copy[.opdsTitle]).navigationBarTitleDisplayMode(.inline)
        .confirmationDialog(copy[.disableOPDSTitle], isPresented: $disableShown, titleVisibility: .visible) { Button(copy[.disableService], role: .destructive) { configuration?.enabled = false }; Button(copy[.cancel], role: .cancel) {} } message: { Text(copy[.disableOPDSMessage]) }
        .task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; let loaded = await store.load(scope: "opds") { try await store.client.loadOPDSConfiguration() }; state = loaded; if case let .loaded(value) = loaded { configuration = value } }
    private func save(_ value: OPDSConfiguration) { Task { let result = await store.performValue(id: "save-opds") { try await store.client.saveOPDSConfiguration(value) }; if case let .success(updated) = result { configuration = updated; state = .loaded(updated) } } }
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

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { backups in
            List(backups) { backup in
                VStack(alignment: .leading, spacing: .space1) {
                    HStack { Label(backup.filename, systemImage: "doc.zipper"); Spacer(); Menu { Button(copy[.downloadFile]) { prepareExport(backup) }; Button(copy[.restoreBackup]) { restoreBackup = backup }; Button(copy[.deleteBackup], role: .destructive) { deleteBackup = backup } } label: { Image(systemName: "ellipsis") } }
                    Text("\(backup.kind) · \(backup.sizeBytes.administrativeByteCount) · \(backup.createdAt.administrativeFormatted(locale: copy.locale))").font(.caption).foregroundStyle(theme.textSecondary)
                    Text("\(backup.bookCount) \(copy[.backupBookCount]) · \(backup.progressCount) \(copy[.backupProgressCount]) · \(backup.libraryCount) \(copy[.backupLibraryCount])").font(.caption).foregroundStyle(theme.textSecondary)
                }.padding(.vertical, .spaceHalf)
            }.administrativeListSurface().overlay { if backups.isEmpty { AdministrativeEmptyView(title: copy[.empty], systemImage: "externaldrive") } }
        }.navigationTitle(copy[.backupsTitle]).navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Button(copy[.createBackup], action: create).disabled(store.operationInFlight != nil) } }
        .sheet(item: $restoreBackup) { backup in restoreSheet(backup) }
        .confirmationDialog(copy[.deleteBackupTitle], isPresented: Binding(get: { deleteBackup != nil }, set: { if !$0 { deleteBackup = nil } }), titleVisibility: .visible) { if let backup = deleteBackup { Button(copy[.deleteBackup], role: .destructive) { delete(backup) } }; Button(copy[.cancel], role: .cancel) {} } message: { Text(copy[.deleteBackupMessage]) }
        .fileExporter(isPresented: $exporting, document: exportDocument, contentType: .zip, defaultFilename: exportFilename) { _ in exportDocument = nil }
        .task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func restoreSheet(_ backup: BackupRecord) -> some View {
        NavigationStack {
            Form { Section { Label(copy[.restoreWarning], systemImage: "exclamationmark.triangle").foregroundStyle(.orange); TextField(copy[.enterRestore], text: $confirmation).textInputAutocapitalization(.characters) } }
                .administrativeListSurface().navigationTitle(copy[.restoreBackup]).navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button(copy[.cancel]) { restoreBackup = nil; confirmation = "" } }; ToolbarItem(placement: .confirmationAction) { Button(copy[.restore], role: .destructive) { restore(backup) }.disabled(confirmation != "RESTORE") } }
        }.environment(\.administrativeCopy, copy).tint(theme.actionAccent)
    }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; state = await store.load(scope: "backups") { try await store.client.loadBackups() } }
    private func create() { Task { let result = await store.performValue(id: "create-backup") { try await store.client.createBackup() }; if case .success = result { await loadAsync() } } }
    private func prepareExport(_ backup: BackupRecord) { Task { let result = await store.performValue(id: "download-backup") { try await store.client.prepareBackupExport(id: backup.id) }; if case let .success(file) = result { exportDocument = ActivityFileDocument(data: file.data); exportFilename = file.filename; exporting = true } } }
    private func restore(_ backup: BackupRecord) { Task { if await store.perform(id: "restore-backup", operation: { try await store.client.restoreBackup(id: backup.id, confirmation: confirmation) }) { restoreBackup = nil; confirmation = ""; await loadAsync() } } }
    private func delete(_ backup: BackupRecord) { deleteBackup = nil; Task { if await store.perform(id: "delete-backup", operation: { try await store.client.deleteBackup(id: backup.id) }) { await loadAsync() } } }
}

struct WorkDetailOrderView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<[AdministrativeWorkDetailSection]> = .idle
    @State private var order: [AdministrativeWorkDetailSection] = []
    @Environment(\.administrativeCopy) private var copy

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { _ in
            List {
                Section { Text(copy[.workOrderHint]).font(.footnote) }
                Section { ForEach(Array(order.enumerated()), id: \.element) { index, item in HStack { Image(systemName: "line.3.horizontal"); Text("\(index + 1)"); Text(title(item)); Spacer(); Button { move(index, -1) } label: { Image(systemName: "chevron.up") }.disabled(index == 0); Button { move(index, 1) } label: { Image(systemName: "chevron.down") }.disabled(index == order.count - 1) } } }
            }.administrativeListSurface().safeAreaInset(edge: .bottom) { HStack { Button(copy[.restoreDefault]) { order = AdministrativeWorkDetailSection.allCases }.buttonStyle(.bordered).frame(maxWidth: .infinity); Button(copy[.saveOrder], action: save).buttonStyle(.borderedProminent).frame(maxWidth: .infinity) }.padding() }
        }.navigationTitle(copy[.workOrderTitle]).navigationBarTitleDisplayMode(.inline).task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func title(_ value: AdministrativeWorkDetailSection) -> String { switch value { case .ebook: copy[.ebook]; case .comic: copy[.comic]; case .audiobook: copy[.audiobook]; case .chaptersAndContent: copy[.chaptersContent] } }
    private func move(_ index: Int, _ delta: Int) { order.swapAt(index, index + delta) }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; let loaded = await store.load(scope: "work-order") { try await store.client.loadWorkDetailOrder() }; state = loaded; if case let .loaded(value) = loaded { order = value } }
    private func save() { let value = order; Task { let result = await store.performValue(id: "save-work-order") { try await store.client.saveWorkDetailOrder(value) }; if case let .success(updated) = result { order = updated; state = .loaded(updated) } } }
}

struct SystemHealthView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<SystemHealthSnapshot> = .idle
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { snapshot in
            List {
                Section { if let checked = snapshot.checkedAt { LabeledContent(copy[.lastChecked], value: checked.administrativeFormatted(locale: copy.locale)) }; Button(copy[.runHealthCheck], action: runCheck).frame(maxWidth: .infinity) }
                ForEach(groups(snapshot.components), id: \.0) { group, components in Section(group) { ForEach(components) { component in HStack { VStack(alignment: .leading) { Text(component.name); if let detail = component.detail { Text(detail).font(.caption).foregroundStyle(theme.textSecondary) } }; Spacer(); AdministrativeStatusLabel(title: status(component.status), status: component.status == .healthy ? .good : component.status == .warning ? .warning : component.status == .failed ? .failed : .neutral) } } } }
            }.administrativeListSurface()
        }.navigationTitle(copy[.healthTitle]).navigationBarTitleDisplayMode(.inline)
        .task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func groups(_ values: [HealthComponent]) -> [(String, [HealthComponent])] { Dictionary(grouping: values, by: \.group).sorted { $0.key < $1.key } }
    private func status(_ value: HealthStatus) -> String { switch value { case .healthy: copy[.healthy]; case .warning: copy[.warning]; case .failed: copy[.failed]; case .checking: copy[.checking] } }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; state = await store.load(scope: "health") { try await store.client.loadSystemHealth() } }
    private func runCheck() { Task { let result = await store.performValue(id: "health-check") { try await store.client.runSystemHealthCheck() }; if case let .success(updated) = result { state = .loaded(updated) } } }
}

struct SystemLogsView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<LogPage> = .idle
    @State private var filter = LogFilter(query: "", levels: Set(LogLevel.allCases), source: nil, since: Calendar.current.date(byAdding: .day, value: -7, to: Date()))
    @State private var settings = LogSettings(limitMegabytes: 50)
    @State private var manageShown = false
    @State private var clearShown = false
    @State private var exportDocument: ActivityFileDocument?
    @State private var exporting = false
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { page in
            List {
                Section { HStack { Label(copy[.logCapacity], systemImage: "doc"); Spacer(); Text("\(page.usedBytes.administrativeByteCount) / \(page.limitBytes.administrativeByteCount)") }; ProgressView(value: Double(page.usedBytes), total: Double(max(page.limitBytes, 1))).tint(theme.brandAccent); Button(copy[.manageLogs]) { manageShown = true } }
                ForEach(page.events) { event in
                    DisclosureGroup { if let correlationID = event.correlationID { LabeledContent("ID", value: correlationID) }; if let target = event.target { LabeledContent(copy[.targetCategory], value: target) } } label: { VStack(alignment: .leading, spacing: .spaceHalf) { HStack { Text(event.timestamp.administrativeFormatted(locale: copy.locale)).font(.caption).foregroundStyle(theme.textSecondary); Text(level(event.level)).font(.caption).foregroundStyle(event.level == .error ? .red : event.level == .warning ? .orange : .blue); Text(event.source).font(.caption) }; Text(event.summary) } }
                }
            }.administrativeListSurface().overlay { if page.events.isEmpty { AdministrativeEmptyView(title: copy[.noResults], systemImage: "doc.text.magnifyingglass") } }
        }.navigationTitle(copy[.logsTitle]).navigationBarTitleDisplayMode(.inline).searchable(text: $filter.query, prompt: copy[.searchLogs]).onSubmit(of: .search, load)
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Menu { ForEach(LogLevel.allCases, id: \.self) { levelValue in Toggle(level(levelValue), isOn: Binding(get: { filter.levels.contains(levelValue) }, set: { enabled in if enabled { filter.levels.insert(levelValue) } else { filter.levels.remove(levelValue) }; load() })) } } label: { Image(systemName: "line.3.horizontal.decrease.circle") } } }
        .sheet(isPresented: $manageShown) { manageSheet }
        .confirmationDialog(copy[.clearLogsTitle], isPresented: $clearShown, titleVisibility: .visible) { Button(copy[.clearAllLogs], role: .destructive, action: clear); Button(copy[.cancel], role: .cancel) {} } message: { Text(copy[.clearLogsMessage]) }
        .fileExporter(isPresented: $exporting, document: exportDocument, contentType: .commaSeparatedText, defaultFilename: "management-logs.csv") { _ in exportDocument = nil }
        .task { await loadAll() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private var manageSheet: some View { NavigationStack { Form { Section(copy[.logCapacity]) { Stepper("\(copy[.capacityMegabytes]): \(settings.limitMegabytes)", value: $settings.limitMegabytes, in: 10...1000, step: 10) }; Section { Button(copy[.exportFiltered], action: export); Button(copy[.clearAllLogs], role: .destructive) { manageShown = false; clearShown = true } } }.administrativeListSurface().navigationTitle(copy[.manageLogs]).navigationBarTitleDisplayMode(.inline).toolbar { ToolbarItem(placement: .cancellationAction) { Button(copy[.close]) { manageShown = false } }; ToolbarItem(placement: .confirmationAction) { Button(copy[.saveCapacity], action: saveSettings) } } }.environment(\.administrativeCopy, copy).tint(theme.actionAccent) }
    private func level(_ value: LogLevel) -> String { switch value { case .information: copy[.information]; case .warning: copy[.warning]; case .error: copy[.failed] } }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { let request = filter; state = .loading; state = await store.load(scope: "logs") { try await store.client.loadLogs(filter: request) } }; private func loadAll() async { async let page: Void = loadAsync(); if let loaded = await store.loadValue(scope: "log-settings", operation: { try await store.client.loadLogSettings() }) { settings = loaded }; _ = await page }
    private func saveSettings() { let value = settings; Task { let result = await store.performValue(id: "save-log-settings") { try await store.client.saveLogSettings(value) }; if case let .success(updated) = result { settings = updated; manageShown = false; await loadAsync() } } }
    private func export() { let request = filter; Task { let result = await store.performValue(id: "export-logs") { try await store.client.prepareLogExport(filter: request) }; if case let .success(file) = result { exportDocument = ActivityFileDocument(data: file.data); manageShown = false; exporting = true } } }
    private func clear() { Task { if await store.perform(id: "clear-logs", operation: { try await store.client.clearLogs() }) { await loadAsync() } } }
}

struct AdministrativeAboutView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<AdministrativeAbout> = .idle
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { about in
            List {
                Section {
                    VStack(spacing: .space1) {
                        Image("BrandMark").resizable().scaledToFit().frame(width: 72, height: 72).accessibilityHidden(true)
                        Text(copy[.aboutTitle]).appTextStyle(.title)
                        Text(copy[.selfHosted]).multilineTextAlignment(.center).foregroundStyle(theme.textSecondary)
                    }.frame(maxWidth: .infinity).padding(.vertical, .space2)
                }
                Section {
                    LabeledContent(copy[.appVersion], value: "\(about.appVersion) (\(about.appBuild))")
                    LabeledContent(copy[.serverVersion], value: about.serverVersion)
                }
                Section {
                    LabeledContent(copy[.supportedFormats], value: about.supportedFormats.joined(separator: ", "))
                    LabeledContent(copy[.openSourceLicense], value: about.license)
                    LabeledContent(copy[.operationMode], value: copy[.selfHosted])
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
            .administrativeListSurface()
        }
        .navigationTitle(copy[.aboutTitle])
        .navigationBarTitleDisplayMode(.inline)
        .task { await loadAsync() }
        .onDisappear { store.cancelPendingRequests() }
        .administrativeNotice(store: store)
    }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; state = await store.load(scope: "administrative-about") { try await store.client.loadAbout() } }
}
