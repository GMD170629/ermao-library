import SwiftUI
import Combine
import UniformTypeIdentifiers
@preconcurrency import ErmaoShared

struct NativeManagementTarget {
    let kind: ErmaoShared.ManagementObject
    let bookID: String
    let id: String
    let title: String
    var kindleEligible = false
    var hasRepresentative = false
    var completed: Bool? = nil

    static func book(_ id: String, _ title: String, completed: Bool? = nil) -> Self { Self(kind: .book, bookID: id, id: id, title: title, completed: completed) }
    var shared: ErmaoShared.ManagementTarget { .init(kind: kind, bookId: bookID, id: id, title: title) }
}

struct NativeManagementChange: Equatable {
    let bookID: String
    let resourceID: String?
    let deleted: Bool
    let readingStatusChanged: Bool
    let revision: Int64
}

private struct NativeManagementStoreKey: EnvironmentKey {
    static let defaultValue: NativeBookManagementStore? = nil
}
private struct NativeManagementRevisionKey: EnvironmentKey { static let defaultValue: Int64 = 0 }
private struct NativeManagementChangeKey: EnvironmentKey { static let defaultValue: NativeManagementChange? = nil }
extension EnvironmentValues {
    var nativeManagement: NativeBookManagementStore? {
        get { self[NativeManagementStoreKey.self] }
        set { self[NativeManagementStoreKey.self] = newValue }
    }
    var managementRevision: Int64 {
        get { self[NativeManagementRevisionKey.self] }
        set { self[NativeManagementRevisionKey.self] = newValue }
    }
    var managementChange: NativeManagementChange? {
        get { self[NativeManagementChangeKey.self] }
        set { self[NativeManagementChangeKey.self] = newValue }
    }
}

@MainActor
final class NativeBookManagementStore: ObservableObject {
    let session: ErmaoShared.BookManagementSession
    let canManage: Bool
    @Published private(set) var state: ErmaoShared.ManagementSessionState
    @Published private(set) var running = false
    @Published private(set) var preparingAction = false
    @Published private(set) var change: NativeManagementChange?
    @Published var transportFailed = false
    @Published private(set) var menuRevision = 0
    private var task: Task<Void, Never>?
    private let context: ContentRequestContext
    private let cache: AuthenticatedCoverCache

    init(repository: any ErmaoShared.WorkManagementRepository, context: ContentRequestContext, canManage: Bool, cache: AuthenticatedCoverCache) {
        self.context = context; self.cache = cache; self.canManage = canManage
        let sharedContext = ErmaoShared.PublicKt.createWorkManagementContext(profileId: context.profileID,
            displayName: context.profileDisplayName, baseUrl: context.baseURL, serverIdentity: context.serverIdentity,
            acceptsInsecureTls: context.acceptsInsecureTLS, userId: context.userID, authorizationVersion: context.authorizationVersion)
        session = ErmaoShared.BookManagementSession(repository: repository, context: sharedContext, canManage: canManage,
            newOperationId: Self.makeOperationID)
        state = session.current
    }

    // KMP may request an operation ID after resuming on a background executor.
    nonisolated private static func makeOperationID() -> String { UUID().uuidString }

    func completed(_ target: NativeManagementTarget) -> Bool? {
        target.completed ?? session.bookCompleted(bookId: target.bookID)?.boolValue
    }
    func menuContext(_ target: NativeManagementTarget) -> ErmaoShared.ManagementMenuContext {
        ErmaoShared.ManagementMenuContext(completed: completed(target).map { KotlinBoolean(bool: $0) },
            kindleSendAvailable: target.kindleEligible, hasRepresentativeResource: target.hasRepresentative)
    }
    func prepareMenu(_ target: NativeManagementTarget) async {
        guard target.kind == .book, target.completed == nil else { return }
        do {
            _ = try await session.prepareBookMenu(bookId: target.bookID)
            guard !Task.isCancelled else { return }
            menuRevision += 1
        } catch is CancellationError { return }
        catch { transportFailed = true }
    }
    func invoke(_ target: NativeManagementTarget, _ action: ErmaoShared.ManagementAction) {
        guard !running else { return }
        preparingAction = true
        session.open(target: target.shared, menuContext: menuContext(target))
        run { [session] in try await session.select(action: action) }
    }
    func retry() {
        run { [session] in try await session.retryPreparation() }
    }
    func edit(_ operation: () -> Void) { operation(); state = session.current }
    func close() { task?.cancel(); task = nil; session.close(); state = session.current; running = false; preparingAction = false }
    func run(_ operation: @escaping @MainActor () async throws -> Void) {
        guard !running else { return }
        running = true; transportFailed = false
        // The menu is already dismissed by the native action dispatch.
        state = session.current
        task = Task { @MainActor [weak self] in
            guard let self else { return }
            defer { if !Task.isCancelled { running = false; preparingAction = false; state = session.current } }
            do {
                try await operation()
                guard !Task.isCancelled else { return }
                state = session.current
                if let result = state.change, change?.revision != state.revision {
                    let paths = [state.snapshot?.book.coverUrl, state.snapshot?.directory?.coverUrl].compactMap { $0 }
                        + (state.snapshot?.resources.map(\.coverUrl) ?? [])
                    for path in Set(paths).filter({ !$0.isEmpty }) {
                        do { try await cache.remove(namespace: context.namespaceKey, key: "cover|\(ErmaoShared.PublicKt.smallCoverRequestPath(apiPath: path))") }
                        catch { session.reportRefreshFailure() }
                    }
                    guard !Task.isCancelled else { return }
                    change = NativeManagementChange(bookID: result.bookId, resourceID: result.resourceId, deleted: result.deleted, readingStatusChanged: result.readingStatusChanged, revision: state.revision)
                }
            } catch is CancellationError {
                return
            } catch {
                if !Task.isCancelled { transportFailed = true }
            }
        }
    }

    func importCover(_ url: URL) {
        run { [session] in
            let secured = url.startAccessingSecurityScopedResource()
            defer { if secured { url.stopAccessingSecurityScopedResource() } }
            let values = try url.resourceValues(forKeys: [.fileSizeKey, .contentTypeKey])
            guard let size = values.fileSize, size > 0, size <= 10 * 1024 * 1024,
                  let type = values.contentType, [UTType.jpeg, .png, .webP].contains(type),
                  let mime = type.preferredMIMEType else { throw NativeManagementFileError.invalid }
            let bytes = try Data(contentsOf: url, options: .mappedIfSafe)
            guard !bytes.isEmpty, bytes.count <= 10 * 1024 * 1024 else { throw NativeManagementFileError.invalid }
            let array = KotlinByteArray(size: Int32(bytes.count))
            for (index, byte) in bytes.enumerated() { array.set(index: Int32(index), value: Int8(bitPattern: byte)) }
            let upload = ErmaoShared.CoverUpload(fileName: url.lastPathComponent, mimeType: mime, bytes: array)
            if session.current.phase.name == "CoverUpload" { try await session.uploadResourceCover(upload: upload) }
            else { session.setCover(edit: .replace, upload: upload) }
        }
    }
}
private enum NativeManagementFileError: Error { case invalid }

struct NativeManagementMenu: View {
    @Environment(\.nativeManagement) private var store
    let target: NativeManagementTarget
    var body: some View {
        if let store { NativeManagementMenuItems(store: store, target: target) }
    }
}

private struct NativeManagementMenuItems: View {
    @ObservedObject var store: NativeBookManagementStore
    let target: NativeManagementTarget
    var body: some View {
        let completed = store.completed(target)
        ForEach(ErmaoShared.PublicKt.managementMenuItems(kind: target.kind, canManage: store.canManage,
            kindleSendAvailable: target.kindleEligible, hasRepresentativeResource: target.hasRepresentative), id: \.action.name) { item in
            Button(role: item.action.name == "Delete" ? .destructive : nil) { store.invoke(target, item.action) } label: {
                if item.action.name == "ReadingStatus" && completed == nil { Text("nativeManagement.readingStatus") }
                else { managementText(managementActionKey(item.action.name, kind: target.kind, completed: completed == true)) }
            }.disabled(!item.enabled || store.running || (item.action.name == "ReadingStatus" && completed == nil))
        }
    }
}

private struct ManagementCoverMenu: ViewModifier {
    @Environment(\.nativeManagement) private var store
    @Environment(\.managementRevision) private var revision
    let target: NativeManagementTarget
    func body(content: Content) -> some View {
        content.contextMenu { NativeManagementMenu(target: target) }
            .task(id: "\(target.bookID)|\(revision)") { await store?.prepareMenu(target) }
    }
}

extension View {
    func bookManagementMenu(_ target: NativeManagementTarget) -> some View {
        modifier(ManagementCoverMenu(target: target))
    }
}

struct NativeManagementMore<Label: View>: View {
    let target: NativeManagementTarget
    @ViewBuilder let label: () -> Label

    var body: some View {
        Menu { NativeManagementMenu(target: target) } label: { label() }
            .buttonStyle(.plain)
            .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget)
    }
}

struct NativeBookManagementHost<Content: View>: View {
    @StateObject private var store: NativeBookManagementStore
    let onChange: (NativeManagementChange) -> Void
    let onUnauthorized: () -> Void
    let onSettings: () -> Void
    let onQueue: () -> Void
    let content: Content
    init(repository: any ErmaoShared.WorkManagementRepository, context: ContentRequestContext, canManage: Bool,
         cache: AuthenticatedCoverCache, onChange: @escaping (NativeManagementChange) -> Void,
         onUnauthorized: @escaping () -> Void, onSettings: @escaping () -> Void, onQueue: @escaping () -> Void,
         @ViewBuilder content: () -> Content) {
        _store = StateObject(wrappedValue: NativeBookManagementStore(repository: repository, context: context, canManage: canManage, cache: cache))
        self.onChange = onChange; self.onUnauthorized = onUnauthorized; self.onSettings = onSettings; self.onQueue = onQueue; self.content = content()
    }
    var body: some View {
        content.environment(\.nativeManagement, store)
            .environment(\.managementRevision, store.change?.revision ?? 0)
            .environment(\.managementChange, store.change)
            .overlay(alignment: .bottom) {

                if let notice = store.state.notice {
                    HStack { managementText("nativeManagement.notice.\(notice)"); Button("common.close") { store.edit { store.session.clearFeedback() } } }
                        .padding(.space2).background(.regularMaterial).accessibilityElement(children: .contain)
                }
            }
            .sheet(isPresented: Binding(get: { store.preparingAction || !["Closed", "Menu"].contains(store.state.phase.name) },
                                        set: { if !$0 { store.close() } })) {
                NativeManagementSheet(store: store, onSettings: onSettings, onQueue: onQueue)
            }
            .onChange(of: store.change) { _, change in if let change { onChange(change) } }
            .onChange(of: store.state.error?.kind.name) { _, kind in if kind == "Unauthorized" { store.close(); onUnauthorized() } }
            .onDisappear { store.close(); store.session.dispose() }
    }
}

private struct NativeManagementSheet: View {
    @ObservedObject var store: NativeBookManagementStore
    let onSettings: () -> Void
    let onQueue: () -> Void
    @State private var importing = false
    @State private var pickerInteraction: Int64 = -1
    @State private var discard = false
    @State private var deleteConfirmation = false
    private var session: ErmaoShared.BookManagementSession { store.session }
    private var state: ErmaoShared.ManagementSessionState { store.state }
    var body: some View {
        NavigationStack {
            Form {
                if store.running { ProgressView() }
                if store.transportFailed || state.error != nil {
                    managementText("nativeManagement.failure.\(state.saveStage?.name ?? "General")").foregroundStyle(.red)
                }
                switch state.phase.name {
                case "Result":
                    if let outcome = state.metadataOutcome {
                        Section("nativeManagement.appliedFields") {
                            ForEach(outcome.appliedFields, id: \.self) { field in managementText("nativeManagement.field.\(field.split(separator: ".").last.map(String.init) ?? "title")") }
                        }
                        Section("nativeManagement.skippedFields") {
                            ForEach(outcome.skippedFields, id: \.self) { field in managementText("nativeManagement.field.\(field.split(separator: ".").last.map(String.init) ?? "title")") }
                        }
                        managementText("nativeManagement.coverResult.\(outcome.coverStatus)")
                    }
                case "Executing":
                    Button("common.retry") { store.run { try await session.retryAction() } }.disabled(store.running)
                case "Editing": editor
                case "Recognizing": recognition
                case "Kindle": kindle
                case "CoverUpload":
                    Text("management.coverUploadHint")
                    Button("management.chooseCoverFile") { pickerInteraction = session.interactionId; importing = true }.disabled(store.running)
                case "DeleteConfirmation":
                    Text(LocalizedStringKey(state.target?.kind == .book ? "nativeManagement.deleteBookWarning" : "nativeManagement.deleteResourceWarning"))
                    Text(state.target?.title ?? "")
                    if let target = state.target, target.kind == .resource,
                       let resource = state.snapshot?.resources.first(where: { $0.id == target.id }) {
                        Text("nativeManagement.sourceCount \(resource.assets.count)")
                    }
                    TextField(state.target?.title ?? "", text: Binding(get: { state.confirmation }, set: { value in store.edit { session.setConfirmation(value: value) } }))
                        .disabled(store.running)
                    Button("nativeManagement.action.Delete", role: .destructive) { deleteConfirmation = true }
                        .disabled(store.running || state.confirmation != state.target?.title)
                case "Loading", "Menu": EmptyView()
                default:
                    Button("common.retry") { store.retry() }.disabled(store.running)
                }
            }
            .navigationTitle(state.target?.title ?? "")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("common.cancel") { if session.isDirty { discard = true } else { store.close() } }.disabled(store.running && !store.preparingAction) } }
            .interactiveDismissDisabled((store.running && !store.preparingAction) || session.isDirty)
            .fileImporter(isPresented: $importing, allowedContentTypes: [.jpeg, .png, .webP]) { result in
                guard pickerInteraction == session.interactionId else { return }
                switch result { case .success(let url): store.importCover(url); case .failure: store.transportFailed = true }
            }
            .confirmationDialog("nativeManagement.discardTitle", isPresented: $discard, titleVisibility: .visible) {
                Button("nativeManagement.discard", role: .destructive) { store.close() }
            }
            .alert("nativeManagement.action.Delete", isPresented: $deleteConfirmation) {
                Button("nativeManagement.action.Delete", role: .destructive) { store.run { try await session.confirmDelete() } }
                Button("common.cancel", role: .cancel) {}
            } message: { Text("nativeManagement.deleteIrreversible") }
        }
    }

    private var editor: some View {
        Group {
            ForEach(state.draft, id: \.field.wireName) { field in
                TextField(text: Binding(get: { field.value }, set: { value in store.edit { session.setField(field: field.field, value: value) } }),
                    axis: ["description", "tags"].contains(field.field.wireName) ? .vertical : .horizontal) {
                    managementText("nativeManagement.field.\(field.field.wireName)")
                }
                    .disabled(store.running)
            }
            if state.target?.kind != .resource {
                if state.target?.kind == .book { Text("nativeManagement.tagsLines") }
                managementText("nativeManagement.cover.\(state.coverEdit.name)")
                if let upload = state.coverUpload { Text(upload.fileName) }
                Button("management.chooseCoverFile") { pickerInteraction = session.interactionId; importing = true }.disabled(store.running)
                Button("nativeManagement.removeCover") { store.edit { session.setCover(edit: .remove, upload: nil) } }.disabled(store.running)
                if state.coverEdit != .keep { Button("nativeManagement.undoCover") { store.edit { session.setCover(edit: .keep, upload: nil) } }.disabled(store.running) }
            }
            Button("management.save") { store.run { try await session.save() } }.disabled(store.running)
        }
    }

    private var recognition: some View {
        Group {
            Picker("management.provider", selection: Binding(get: { state.providerId }, set: { value in store.edit { session.setProvider(value: value) } })) {
                ForEach(state.providers.filter(\.enabled), id: \.id) { Text($0.name).tag($0.id) }
            }.disabled(store.running)
            if state.providers.isEmpty { Button("common.retry") { store.run { try await session.loadProviders() } }.disabled(store.running) }
            TextField("management.query", text: Binding(get: { state.query }, set: { value in store.edit { session.setQuery(value: value) } })).disabled(store.running)
            Button("management.search") { store.run { try await session.search() } }.disabled(store.running || state.query.isEmpty || state.providerId.isEmpty)
            ForEach(state.candidates, id: \.id) { candidate in
                Button { store.edit { session.selectCandidate(candidate: candidate) } } label: {
                    HStack { Text(candidate.title ?? candidate.id); Spacer(); if candidate == state.selectedCandidate { Image(systemName: "checkmark") } }
                }.disabled(store.running)
            }
            if state.candidates.isEmpty { Text("nativeManagement.noCandidates") }
            if let candidate = state.selectedCandidate {
                if state.target?.kind == .directory { Text(candidate.description_ ?? "") }
                else {
                    ForEach(session.recognitionFields, id: \.wireValue) { field in
                        Toggle(isOn: Binding(get: { state.selectedFields.contains(field) }, set: { selected in store.edit { session.setRecognizedField(field: field, selected: selected) } })) {
                            VStack(alignment: .leading) {
                                managementText("nativeManagement.field.\(field.field.wireName)")
                                Text("nativeManagement.current \(session.currentValue(field: field))")
                                Text("nativeManagement.candidate \(ErmaoShared.PublicKt.managementCandidateValue(candidate: candidate, field: field.field))")
                            }
                        }.disabled(store.running)
                    }
                }
                Button("management.applyMetadata") { store.run { try await session.applyRecognition() } }
                    .disabled(store.running || (state.target?.kind != .directory && state.selectedFields.isEmpty))
            }
        }
    }

    private var kindle: some View {
        Group {
            Text(state.kindleSettings?.recipientEmail ?? "")
            if state.kindleSettings?.ready != true {
                Text("management.kindleNotReady")
                Button("common.retry") { store.run { try await session.loadKindle() } }.disabled(store.running)
            }
            ForEach(session.kindleOptions(), id: \.id) { resource in
                ForEach(resource.assets.filter { $0.role == "PRIMARY" }, id: \.id) { asset in
                    Button { store.edit { session.setAsset(value: asset.id) } } label: {
                        HStack { Text("\(resource.title) · \(resource.format) · \(asset.size)"); if asset.id == state.selectedAssetId { Image(systemName: "checkmark") } }
                    }.disabled(store.running)
                }
            }
            Button("nativeManagement.kindleSettings") { store.close(); onSettings() }.disabled(store.running)
            Button("nativeManagement.kindleQueue") { store.close(); onQueue() }.disabled(store.running)
            Button("management.addToKindleQueue") { store.run { try await session.sendKindle() } }
                .disabled(store.running || state.kindleSettings?.ready != true || state.selectedAssetId.isEmpty)
        }
    }
}

private func managementText(_ key: String) -> Text {
    // Resolve the complete runtime key, not a LocalizedStringKey interpolation pattern.
    Text(LocalizedStringKey(key))
}

func managementActionKey(_ action: String, kind: ErmaoShared.ManagementObject, completed: Bool) -> String {
    if action == "ReadingStatus" { return completed ? "nativeManagement.markUnread" : "nativeManagement.markRead" }
    if action == "Regenerate" { return kind == .book ? "nativeManagement.regenerateImages" : "management.regenerateCover" }
    return "nativeManagement.action.\(action)"
}

struct OptionalManagementCover: ViewModifier {
    let target: NativeManagementTarget?
    @ViewBuilder func body(content: Content) -> some View {
        if let target { content.bookManagementMenu(target) } else { content }
    }
}
