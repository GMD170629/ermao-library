import SwiftUI

struct OrganizeQueueView: View {
    enum Filter: Hashable { case all, pending, completed }
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<[OrganizeJob]> = .idle
    @State private var filter: Filter = .all
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme
    @Environment(\.administrativeNavigate) private var navigate

    var body: some View {
        VStack(spacing: 0) {
            Picker(copy[.organizeTitle], selection: $filter) { Text(copy[.all]).tag(Filter.all); Text(copy[.pending]).tag(Filter.pending); Text(copy[.completed]).tag(Filter.completed) }.pickerStyle(.segmented).padding()
            AdministrativeStateView(state: state, retry: load) { jobs in
                SettingsList {
                    ForEach(filtered(jobs)) { job in
                    VStack(alignment: .leading, spacing: .space1) {
                        HStack { Text(job.title).appTextStyle(.headline); Spacer(); Text(status(job.status)).foregroundStyle(statusColor(job.status)) }
                        if let subtitle = job.subtitle { Text(subtitle).foregroundStyle(theme.textSecondary) }
                        if let error = job.errorCode { Text(error).font(.caption).foregroundStyle(.red).textSelection(.enabled) }
                        HStack { Spacer(); if job.status == .pendingRecognition { Button(copy[.recognizeNow]) { mutate("recognize-\(job.id)") { try await store.client.recognizeOrganizeJob(id: job.id) } } }; Button(copy[.delete], role: .destructive) { mutate("delete-organize-\(job.id)") { try await store.client.deleteOrganizeJob(id: job.id) } } }.buttonStyle(.borderless)
                    }.padding(.vertical, .spaceHalf)
                    }
                }.overlay { if filtered(jobs).isEmpty { AdministrativeEmptyView(title: copy[.empty], systemImage: "sparkles") } }
            }
        }
        .navigationTitle(copy[.organizeTitle]).navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Button(copy[.candidateTitle]) { navigate(.organizeCandidates) }
                    Button(copy[.organizeRuns]) { navigate(.organizeRuns) }
                    Button(copy[.recognitionPolicyTitle]) { navigate(.recognitionPolicy) }
                    Button(copy[.categoryGovernanceTitle]) { navigate(.categoryGovernance) }
                    Button(copy[.metadataProviders]) { navigate(.metadataProviders) }
                } label: {
                    Image(systemName: "ellipsis")
                }
            }
        }
        .task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
        .settingsPageSurface()
    }
    private func filtered(_ jobs: [OrganizeJob]) -> [OrganizeJob] { switch filter { case .all: jobs; case .pending: jobs.filter { $0.status != .organized && $0.status != .cancelled }; case .completed: jobs.filter { $0.status == .organized } } }
    private func status(_ status: OrganizeJobStatus) -> String { switch status { case .pendingRecognition: copy[.pending]; case .needsConfirmation: copy[.viewCandidates]; case .organized: copy[.completed]; case .failed: copy[.failed]; case .cancelled: copy[.cancelled] } }
    private func statusColor(_ status: OrganizeJobStatus) -> Color { switch status { case .organized: .green; case .failed: .red; case .pendingRecognition, .needsConfirmation: theme.actionAccent; case .cancelled: theme.textSecondary } }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; state = await store.load(scope: "organize-jobs") { try await store.client.loadPendingOrganizeJobs() } }
    private func mutate(_ id: String, operation: @escaping @Sendable () async throws -> Void) { Task { if await store.perform(id: id, operation: operation) { await loadAsync() } } }
}

struct OrganizeRunsView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<[OrganizeRun]> = .idle
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { runs in
            SettingsList {
                ForEach(runs) { run in
                VStack(alignment: .leading, spacing: .space1) {
                    HStack { Text(runStatus(run.status)); Spacer(); if let started = run.startedAt { Text(started.administrativeFormatted(locale: copy.locale)).font(.caption).foregroundStyle(theme.textSecondary) } }
                    HStack { LabeledContent(copy[.queuedCount], value: "\(run.queuedCount)"); LabeledContent(copy[.completed], value: "\(run.completedCount)") }
                    HStack { LabeledContent(copy[.reviewCount], value: "\(run.reviewCount)"); LabeledContent(copy[.failed], value: "\(run.failedCount)") }
                }.padding(.vertical, .spaceHalf)
                }
            }.overlay { if runs.isEmpty { AdministrativeEmptyView(title: copy[.empty], systemImage: "clock.arrow.circlepath") } }
        }.navigationTitle(copy[.organizeRuns]).navigationBarTitleDisplayMode(.inline)
        .task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func load() { Task { await loadAsync() } }
    private func runStatus(_ value: String) -> String {
        switch value.uppercased() {
        case "RUNNING": copy[.running]
        case "COMPLETED": copy[.completed]
        case "WARNING": copy[.warning]
        case "ERROR", "FAILED": copy[.failed]
        case "CANCELLED": copy[.cancelled]
        default: copy[.unknown]
        }
    }
    private func loadAsync() async { state = .loading; state = await store.load(scope: "organize-runs") { try await store.client.loadOrganizeRuns() } }
}

struct RecognitionCandidatesView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<[RecognitionCandidate]> = .idle
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { candidates in
            SettingsList {
                ForEach(candidates) { candidate in
                    HStack {
                        VStack(alignment: .leading) { Text(candidate.title); if let author = candidate.author { Text(author).foregroundStyle(theme.textSecondary) } }
                        Spacer()
                        Text(candidate.confidence, format: .percent.precision(.fractionLength(0))).foregroundStyle(theme.textSecondary)
                    }
                }
            }.overlay { if candidates.isEmpty { AdministrativeEmptyView(title: copy[.empty], systemImage: "sparkles") } }
        }
        .navigationTitle(copy[.candidateTitle]).navigationBarTitleDisplayMode(.inline).task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; state = await store.load(scope: "recognition-candidates") { try await store.client.loadRecognitionCandidates() } }
}

struct RecognitionPolicyView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<RecognitionPolicy> = .idle
    @State private var policy: RecognitionPolicy?
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { _ in
            if let binding = Binding($policy) {
                SettingsForm {
                    Section {
                        SettingsToggleRow(LocalizedStringKey(copy[.scheduledRecognition]), isOn: binding.scheduled)
                        SettingsFieldRow(LocalizedStringKey(copy[.schedule])) {
                            Picker(LocalizedStringKey(copy[.schedule]), selection: binding.schedule) {
                                ForEach(RecognitionSchedule.allCases, id: \.self) { Text(schedule($0)).tag($0) }
                            }
                        }
                        SettingsToggleRow(LocalizedStringKey(copy[.runAfterImport]), isOn: binding.runAfterImport)
                    }
                    Section("OPF") {
                        SettingsToggleRow(LocalizedStringKey(copy[.persistOPF]), isOn: binding.persistToOPF)
                        SettingsValueRow(LocalizedStringKey(copy[.opfQueue]), value: "\(binding.wrappedValue.opfQueueCompleted) / \(binding.wrappedValue.opfQueueTotal)")
                        if binding.wrappedValue.opfQueueTotal > 0 { ProgressView(value: Double(binding.wrappedValue.opfQueueCompleted), total: Double(binding.wrappedValue.opfQueueTotal)).tint(theme.brandAccent) }
                    }
                    Section(copy[.metadataPriority]) {
                        SettingsToggleRow(LocalizedStringKey(copy[.localMetadataFirst]), isOn: binding.localMetadataFirst)
                        ForEach(Array(binding.wrappedValue.priorities.enumerated()), id: \.element) { index, item in
                            HStack {
                                Text("\(index + 1)")
                                Text(priority(item))
                                Spacer()
                                Button { movePriority(index, -1) } label: { Image(systemName: "chevron.up") }.disabled(index == 0)
                                Button { movePriority(index, 1) } label: { Image(systemName: "chevron.down") }.disabled(index == binding.wrappedValue.priorities.count - 1)
                            }
                            .frame(minHeight: SettingsMetrics.rowContentMinimumHeight)
                            .listRowInsets(SettingsMetrics.rowInsets)
                        }
                    }
                    Section(copy[.recognitionScope]) {
                        SettingsToggleRow(LocalizedStringKey(copy[.recognizeUnmatched]), isOn: binding.recognizeUnmatched)
                        SettingsToggleRow(LocalizedStringKey(copy[.recognizeIncomplete]), isOn: binding.recognizeMissingAuthorOrCover)
                        SettingsValueRow(LocalizedStringKey(copy[.eligibleCount]), value: "\(binding.wrappedValue.eligibleCount)")
                        if let next = binding.wrappedValue.nextRunAt { SettingsValueRow(LocalizedStringKey(copy[.nextRun]), value: next.administrativeFormatted(locale: copy.locale)) }
                    }
                }.administrativeNotice(store: store)
            }
        }.navigationTitle(copy[.recognitionPolicyTitle]).navigationBarTitleDisplayMode(.inline).task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }
        .toolbar {
            if let policy {
                ToolbarItem(placement: .confirmationAction) {
                    AdministrativeToolbarAction(
                        title: copy[.save],
                        working: store.operationInFlight == "save-recognition-policy"
                    ) { save(policy) }
                }
            }
        }
    }
    private func schedule(_ value: RecognitionSchedule) -> String {
        let hours: Double
        switch value {
        case .hourly: hours = 1
        case .sixHours: hours = 6
        case .daily: hours = 24
        case .manual: return copy[.disabled]
        }
        return Measurement(value: hours, unit: UnitDuration.hours)
            .formatted(.measurement(width: .abbreviated).locale(Locale(identifier: copy.locale.rawValue)))
    }
    private func priority(_ value: MetadataPriority) -> String { switch value { case .opf: "OPF"; case .embedded: copy[.metadataSection]; case .pathAndFilename: copy[.pathAndFilename] } }
    private func movePriority(_ index: Int, _ delta: Int) { guard var value = policy else { return }; value.priorities.swapAt(index, index + delta); policy = value }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; let loaded = await store.load(scope: "recognition-policy") { try await store.client.loadRecognitionPolicy() }; state = loaded; if case let .loaded(value) = loaded { policy = value } }
    private func save(_ value: RecognitionPolicy) { Task { let result = await store.performValue(id: "save-recognition-policy") { try await store.client.saveRecognitionPolicy(value) }; if case let .success(updated) = result { policy = updated; state = .loaded(updated) } } }
}

struct LibraryOperationsView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<[LibraryOperation]> = .idle
    @State private var operationToUndo: LibraryOperation?
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { operations in
            SettingsList {
                ForEach(operations) { operation in
                VStack(alignment: .leading, spacing: .spaceHalf) {
                    HStack { Text(operationAction(operation.action)); Spacer(); Text(operationStatus(operation.status)).foregroundStyle(theme.textSecondary) }
                    Text(operation.summary)
                    HStack { if let date = operation.createdAt { Text(date.administrativeFormatted(locale: copy.locale)).font(.caption).foregroundStyle(theme.textSecondary) }; Spacer(); if operation.undoAvailable { Button(copy[.undoOperation]) { operationToUndo = operation } } }
                }.padding(.vertical, .spaceHalf)
                }
            }.overlay { if operations.isEmpty { AdministrativeEmptyView(title: copy[.empty], systemImage: "clock") } }
        }.navigationTitle(copy[.operationHistory]).navigationBarTitleDisplayMode(.inline)
        .confirmationDialog(copy[.undoOperation], isPresented: Binding(get: { operationToUndo != nil }, set: { if !$0 { operationToUndo = nil } }), titleVisibility: .visible) { if let operation = operationToUndo { Button(copy[.undoOperation], role: .destructive) { undo(operation) } }; Button(copy[.cancel], role: .cancel) {} } message: { Text(copy[.undoOperationMessage]) }
        .task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func load() { Task { await loadAsync() } }
    private func operationAction(_ value: String) -> String {
        switch value.uppercased() {
        case "MERGE_FACETS": copy[.mergeFacets]
        case "RENAME_FACET": copy[.renameFacet]
        case "DELETE_FACET": copy[.deleteFacet]
        case "BULK_UPDATE_METADATA": copy[.bulkUpdateMetadata]
        case "BULK_FIND_REPLACE": copy[.bulkFindReplace]
        case "BULK_SHELF_MEMBERSHIP": copy[.bulkShelfMembership]
        case "BULK_READING_STATUS": copy[.bulkReadingStatus]
        case "BULK_BOOK_COVERS": copy[.bulkBookCovers]
        default: copy[.otherOperation]
        }
    }
    private func operationStatus(_ value: String) -> String {
        switch value.uppercased() {
        case "COMPLETED": copy[.completed]
        case "FAILED": copy[.failed]
        case "UNDONE": copy[.undone]
        default: copy[.unknown]
        }
    }
    private func loadAsync() async { state = .loading; state = await store.load(scope: "library-operations") { try await store.client.loadLibraryOperations() } }
    private func undo(_ operation: LibraryOperation) { operationToUndo = nil; Task { if await store.perform(id: "undo-\(operation.id)", operation: { try await store.client.undoLibraryOperation(id: operation.id) }) { await loadAsync() } } }
}

struct CategoryGovernanceView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<[GovernedCategory]> = .idle
    @State private var kind = CategoryKind.author
    @State private var query = ""
    @State private var selected = Set<String>()
    @State private var targetID: String?
    @State private var mergeShown = false
    @State private var deleteCategory: GovernedCategory?
    @State private var renameCategory: GovernedCategory?
    @State private var renamedValue = ""
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(spacing: 0) {
            Picker(copy[.categoryGovernanceTitle], selection: $kind) { Text(copy[.author]).tag(CategoryKind.author); Text(copy[.tag]).tag(CategoryKind.tag); Text(copy[.series]).tag(CategoryKind.series) }.pickerStyle(.segmented).padding(.horizontal)
            AdministrativeStateView(state: state, retry: load) { categories in
                SettingsList {
                    ForEach(categories) { category in
                    HStack { Button { if selected.contains(category.id) { selected.remove(category.id) } else { selected.insert(category.id) } } label: { Image(systemName: selected.contains(category.id) ? "checkmark.square.fill" : "square") }; VStack(alignment: .leading) { Text(category.name); if !category.aliases.isEmpty { Text(category.aliases.joined(separator: ", ")).font(.caption).foregroundStyle(theme.textSecondary) } }; Spacer(); Text("\(category.bookCount)").foregroundStyle(theme.textSecondary); Menu { Button(copy[.renameCategory]) { renamedValue = category.name; renameCategory = category }; Button(copy[.deleteCategory], role: .destructive) { deleteCategory = category } } label: { Image(systemName: "ellipsis") } }
                    }
                }.administrativeNotice(store: store).safeAreaInset(edge: .bottom) { if selected.count > 1 { AdministrativeBottomAction(title: "\(copy[.merge]) · \(selected.count)") { targetID = selected.first; mergeShown = true } } }
            }
        }.settingsPageSurface().searchable(text: $query, prompt: copy[.search]).onSubmit(of: .search, load).onChange(of: kind) { _, _ in selected.removeAll(); load() }
        .sheet(isPresented: $mergeShown) { mergeSheet }
        .sheet(item: $renameCategory) { category in renameSheet(category) }
        .confirmationDialog(copy[.deleteCategory], isPresented: Binding(get: { deleteCategory != nil }, set: { if !$0 { deleteCategory = nil } }), titleVisibility: .visible) { if let value = deleteCategory { Button(copy[.delete], role: .destructive) { delete(value) } }; Button(copy[.cancel], role: .cancel) {} }
        .task { await loadAsync() }
    }
    private var categories: [GovernedCategory] { guard case let .loaded(values) = state else { return [] }; return values }
    private var mergeSheet: some View {
        NavigationStack {
            SettingsForm {
                Section(copy[.targetCategory]) {
                    ForEach(categories.filter { selected.contains($0.id) }) { category in
                        SettingsToggleRow(
                            verbatim: category.name,
                            isOn: Binding(
                                get: { targetID == category.id },
                                set: { isTarget in if isTarget { targetID = category.id } }
                            )
                        )
                    }
                }
            }
            .navigationTitle(copy[.mergeCategoriesTitle])
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(copy[.cancel]) { mergeShown = false } }
                ToolbarItem(placement: .confirmationAction) { Button(copy[.confirmMerge], action: merge).disabled(targetID == nil) }
            }
        }
        .environment(\.administrativeCopy, copy)
        .tint(theme.actionAccent)
    }

    private func renameSheet(_ category: GovernedCategory) -> some View {
        NavigationStack {
            SettingsForm {
                SettingsTextInputRow(LocalizedStringKey(copy[.newCategoryName])) {
                    TextField(LocalizedStringKey(copy[.newCategoryName]), text: $renamedValue)
                }
            }
            .navigationTitle(copy[.renameCategory])
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(copy[.cancel]) { renameCategory = nil } }
                ToolbarItem(placement: .confirmationAction) { Button(copy[.confirmRename]) { rename(category) }.disabled(renamedValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty) }
            }
        }
        .environment(\.administrativeCopy, copy)
        .tint(theme.actionAccent)
    }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; let search = query; let selectedKind = kind; state = await store.load(scope: "categories") { try await store.client.loadCategories(kind: selectedKind, query: search) } }
    private func merge() { guard let targetID else { return }; let request = MergeCategoryRequest(kind: kind, sourceIDs: selected.subtracting([targetID]), targetID: targetID); Task { let result = await store.performValue(id: "merge-categories") { try await store.client.mergeCategories(request) }; if case .success = result { mergeShown = false; selected.removeAll(); await loadAsync() } } }
    private func delete(_ category: GovernedCategory) { deleteCategory = nil; Task { if await store.perform(id: "delete-category", operation: { try await store.client.deleteCategory(id: category.id) }) { await loadAsync() } } }
    private func rename(_ category: GovernedCategory) { let name = renamedValue.trimmingCharacters(in: .whitespacesAndNewlines); Task { let result = await store.performValue(id: "rename-category") { try await store.client.renameCategory(id: category.id, name: name) }; if case .success = result { renameCategory = nil; renamedValue = ""; await loadAsync() } } }
}
