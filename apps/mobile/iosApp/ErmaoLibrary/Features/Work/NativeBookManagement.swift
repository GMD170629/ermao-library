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

enum NativeManagementPresentation: Equatable {
    case none
    case sheet(actionName: String)

    var presentsSheet: Bool {
        if case .sheet = self { return true }
        return false
    }
}

enum NativeManagementInvocationOutcome: Equatable {
    case succeeded
    case failed
}

enum NativeManagementMenuItemStatus: Equatable {
    case idle
    case running
    case failed
}

struct NativeManagementActionKey: Equatable {
    let bookID: String
    let targetID: String
    let actionName: String

    init(target: NativeManagementTarget, action: ErmaoShared.ManagementAction) {
        bookID = target.bookID
        targetID = target.id
        actionName = action.name
    }
}

struct NativeManagementMenuExecution: Equatable {
    let key: NativeManagementActionKey
    let status: NativeManagementMenuItemStatus
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
    @Published private(set) var presentation = NativeManagementPresentation.none
    @Published private(set) var menuExecution: NativeManagementMenuExecution?
    @Published private(set) var change: NativeManagementChange?
    @Published var transportFailed = false
    @Published private(set) var menuRevision = 0
    private var task: Task<Void, Never>?
    private var preparedMenuBookIDs: Set<String> = []
    private var preparingMenuBookIDs: Set<String> = []
    private let context: ContentRequestContext
    private let contentClient: any ContentClient
    private let cache: AuthenticatedCoverCache

    init(
        repository: any ErmaoShared.WorkManagementRepository,
        context: ContentRequestContext,
        contentClient: any ContentClient,
        canManage: Bool,
        cache: AuthenticatedCoverCache
    ) {
        self.context = context; self.contentClient = contentClient; self.cache = cache; self.canManage = canManage
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
    var isPreparingPresentedSheet: Bool {
        presentation.presentsSheet && ["Menu", "Loading"].contains(state.phase.name)
    }
    func menuItemStatus(_ target: NativeManagementTarget, _ action: ErmaoShared.ManagementAction) -> NativeManagementMenuItemStatus {
        nativeManagementMenuItemStatus(execution: menuExecution, target: target, action: action)
    }
    func tagSuggestions(query: String) async throws -> [LibraryTagSuggestion] {
        try await contentClient.fetchTagSuggestions(context: context, query: query, limit: 20)
    }
    func prepareMenu(_ target: NativeManagementTarget) async {
        guard target.kind == .book, target.completed == nil else { return }
        guard !preparedMenuBookIDs.contains(target.bookID) else { return }
        guard preparingMenuBookIDs.insert(target.bookID).inserted else { return }
        defer { preparingMenuBookIDs.remove(target.bookID) }
        do {
            _ = try await session.prepareBookMenu(bookId: target.bookID)
            guard !Task.isCancelled else { return }
            preparedMenuBookIDs.insert(target.bookID)
            menuRevision += 1
        } catch is CancellationError { return }
        catch { transportFailed = true }
    }
    func invoke(
        _ target: NativeManagementTarget,
        _ action: ErmaoShared.ManagementAction,
        completion: ((NativeManagementInvocationOutcome) -> Void)? = nil
    ) {
        guard !running else { return }
        let requestedPresentation = nativeManagementPresentation(for: action)
        let actionKey = NativeManagementActionKey(target: target, action: action)
        presentation = requestedPresentation
        menuExecution = requestedPresentation.presentsSheet
            ? nil
            : NativeManagementMenuExecution(key: actionKey, status: .running)
        session.open(target: target.shared, menuContext: menuContext(target))
        run({ [session] in try await session.select(action: action) }) { [weak self] outcome in
            guard let self else { return }
            if !requestedPresentation.presentsSheet, menuExecution?.key == actionKey {
                menuExecution = outcome == .succeeded
                    ? nil
                    : NativeManagementMenuExecution(key: actionKey, status: .failed)
            }
            completion?(outcome)
        }
    }
    func retry() {
        run { [session] in try await session.retryPreparation() }
    }
    func retryImmediateAction(completion: ((NativeManagementInvocationOutcome) -> Void)? = nil) {
        guard !running, let failedExecution = menuExecution, failedExecution.status == .failed else { return }
        menuExecution = NativeManagementMenuExecution(key: failedExecution.key, status: .running)
        run({ [session] in try await session.retryAction() }) { [weak self] outcome in
            guard let self else { return }
            if menuExecution?.key == failedExecution.key {
                menuExecution = outcome == .succeeded
                    ? nil
                    : NativeManagementMenuExecution(key: failedExecution.key, status: .failed)
            }
            completion?(outcome)
        }
    }
    func edit(_ operation: () -> Void) { operation(); state = session.current }
    func close() {
        task?.cancel()
        task = nil
        session.close()
        state = session.current
        running = false
        presentation = .none
        menuExecution = nil
    }
    func run(
        _ operation: @escaping @MainActor () async throws -> Void,
        completion: ((NativeManagementInvocationOutcome) -> Void)? = nil
    ) {
        guard !running else { return }
        running = true; transportFailed = false
        state = session.current
        task = Task { @MainActor [weak self] in
            guard let self else { return }
            defer {
                if !Task.isCancelled {
                    state = session.current
                    if state.phase.name == "Closed" { presentation = .none }
                    running = false
                    completion?(transportFailed || state.error != nil ? .failed : .succeeded)
                }
            }
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

    func importCover(_ url: URL, expectedInteractionId: Int64) {
        run { [session] in
            guard expectedInteractionId == session.interactionId,
                  session.current.phase.name == "CoverUpload" else { return }
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
            try await session.uploadResourceCover(upload: upload, expectedInteractionId: expectedInteractionId)
        }
    }
}
private enum NativeManagementFileError: Error { case invalid }

struct NativeManagementMenu: View {
    @Environment(\.nativeManagement) private var store
    let target: NativeManagementTarget
    var body: some View {
        if let store {
            NativeManagementMenuItems(store: store, target: target, surface: .system) { action in
                if store.menuItemStatus(target, action) == .failed {
                    store.retryImmediateAction()
                } else {
                    store.invoke(target, action)
                }
            }
        }
    }
}

private enum NativeManagementMenuSurface {
    case system
    case popover
}

private struct NativeManagementMenuItems: View {
    @ObservedObject var store: NativeBookManagementStore
    let target: NativeManagementTarget
    let surface: NativeManagementMenuSurface
    let onSelect: (ErmaoShared.ManagementAction) -> Void

    var body: some View {
        let completed = store.completed(target)
        ForEach(ErmaoShared.PublicKt.managementMenuItems(kind: target.kind, canManage: store.canManage,
            kindleSendAvailable: target.kindleEligible, hasRepresentativeResource: target.hasRepresentative), id: \.action.name) { item in
            let status = store.menuItemStatus(target, item.action)
            Button(role: item.action.name == "Delete" ? .destructive : nil) { onSelect(item.action) } label: {
                NativeManagementMenuRowLabel(surface: surface) {
                    HStack(spacing: .space2) {
                        if item.action.name == "ReadingStatus" && completed == nil {
                            Text("nativeManagement.readingStatus")
                        } else {
                            managementText(managementActionKey(item.action.name, kind: target.kind, completed: completed == true))
                        }
                        if surface == .popover {
                            Spacer(minLength: .space2)
                            NativeManagementMenuStatusView(status: status)
                        }
                    }
                }
            }
            .disabled(!item.enabled || store.running || (item.action.name == "ReadingStatus" && completed == nil))
            .modifier(NativeManagementMenuButtonStyle(surface: surface))
        }
    }
}

private struct NativeManagementMenuRowLabel<Content: View>: View {
    let surface: NativeManagementMenuSurface
    @ViewBuilder let content: () -> Content

    var body: some View {
        if surface == .popover {
            content()
                .padding(.horizontal, .space3)
                .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget, alignment: .leading)
                .contentShape(Rectangle())
        } else {
            content()
        }
    }
}

private struct NativeManagementMenuStatusView: View {
    let status: NativeManagementMenuItemStatus

    var body: some View {
        Group {
            switch status {
            case .running:
                ProgressView()
                    .controlSize(.small)
                    .accessibilityLabel(Text("common.loading"))
            case .failed:
                Image(systemName: "arrow.clockwise")
                    .foregroundStyle(.red)
                    .accessibilityLabel(Text("common.retry"))
            case .idle:
                Color.clear
                    .accessibilityHidden(true)
            }
        }
        .frame(width: 18, height: 18, alignment: .trailing)
    }
}

private struct NativeManagementMenuButtonStyle: ViewModifier {
    let surface: NativeManagementMenuSurface

    @ViewBuilder func body(content: Content) -> some View {
        if surface == .popover {
            content.buttonStyle(.plain)
        } else {
            content
        }
    }
}

struct NativeManagementSupplementalAction: Identifiable {
    let id: String
    let title: LocalizedStringKey
    let systemImage: String
    let accessibilityIdentifier: String
    let perform: () -> Void
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
    @Environment(\.nativeManagement) private var store
    @State private var isPresented = false
    @State private var pendingSheetAction: ErmaoShared.ManagementAction?
    @State private var pendingSupplementalActionID: String?
    let target: NativeManagementTarget
    let supplementalActions: [NativeManagementSupplementalAction]
    @ViewBuilder let label: () -> Label

    init(
        target: NativeManagementTarget,
        supplementalActions: [NativeManagementSupplementalAction] = [],
        @ViewBuilder label: @escaping () -> Label
    ) {
        self.target = target
        self.supplementalActions = supplementalActions
        self.label = label
    }

    var body: some View {
        Button { isPresented = true } label: { label() }
            .buttonStyle(.plain)
            .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget)
            .disabled(store == nil && supplementalActions.isEmpty)
            .popover(isPresented: $isPresented, attachmentAnchor: .rect(.bounds), arrowEdge: .bottom) {
                VStack(spacing: 0) {
                    if let store {
                        NativeManagementMenuItems(store: store, target: target, surface: .popover) { action in
                            select(action, store: store)
                        }
                    }
                    ForEach(supplementalActions) { action in
                        Button {
                            pendingSupplementalActionID = action.id
                            isPresented = false
                        } label: {
                            HStack(spacing: .space2) {
                                SwiftUI.Label(action.title, systemImage: action.systemImage)
                                Spacer(minLength: .space3)
                            }
                            .padding(.horizontal, .space3)
                            .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget, alignment: .leading)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .disabled(store?.running == true)
                        .accessibilityIdentifier(action.accessibilityIdentifier)
                    }
                }
                .padding(.vertical, .space1)
                .frame(width: 240)
                .presentationCompactAdaptation(.popover)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("nativeManagement.popover")
                .onDisappear { dispatchPendingAction(store: store) }
            }
    }

    private func select(_ action: ErmaoShared.ManagementAction, store: NativeBookManagementStore) {
        if nativeManagementPresentation(for: action).presentsSheet {
            pendingSheetAction = action
            isPresented = false
            return
        }
        let completion: (NativeManagementInvocationOutcome) -> Void = { outcome in
            if outcome == .succeeded { isPresented = false }
        }
        if store.menuItemStatus(target, action) == .failed {
            store.retryImmediateAction(completion: completion)
        } else {
            store.invoke(target, action, completion: completion)
        }
    }

    private func dispatchPendingAction(store: NativeBookManagementStore?) {
        if let action = pendingSheetAction, let store {
            pendingSheetAction = nil
            store.invoke(target, action)
            return
        }
        guard let actionID = pendingSupplementalActionID else { return }
        pendingSupplementalActionID = nil
        supplementalActions.first(where: { $0.id == actionID })?.perform()
    }
}

struct NativeBookManagementHost<Content: View>: View {
    @StateObject private var store: NativeBookManagementStore
    let onChange: (NativeManagementChange) -> Void
    let onUnauthorized: () -> Void
    let onSettings: () -> Void
    let onQueue: () -> Void
    let bottomObstruction: CGFloat
    let content: Content
    init(repository: any ErmaoShared.WorkManagementRepository, context: ContentRequestContext,
         contentClient: any ContentClient, canManage: Bool,
         cache: AuthenticatedCoverCache, bottomObstruction: CGFloat = 0,
         onChange: @escaping (NativeManagementChange) -> Void,
         onUnauthorized: @escaping () -> Void, onSettings: @escaping () -> Void, onQueue: @escaping () -> Void,
         @ViewBuilder content: () -> Content) {
        _store = StateObject(wrappedValue: NativeBookManagementStore(
            repository: repository,
            context: context,
            contentClient: contentClient,
            canManage: canManage,
            cache: cache
        ))
        self.bottomObstruction = bottomObstruction
        self.onChange = onChange; self.onUnauthorized = onUnauthorized; self.onSettings = onSettings; self.onQueue = onQueue; self.content = content()
    }
    @Environment(\.locale) private var locale
    @EnvironmentObject private var feedbackPresenter: OperationFeedbackPresenter
    @State private var nativeManagementSheetIsVisible = false
    @State private var presentedFeedbackRevision: Int64 = 0

    var body: some View {
        content.environment(\.nativeManagement, store)
            .environment(\.managementRevision, store.change?.revision ?? 0)
            .environment(\.managementChange, store.change)
            .overlay(alignment: .bottom) {
                if store.state.phase.name == "Executing", store.state.error != nil {
                    HStack {
                        managementText("nativeManagement.failure.General").foregroundStyle(.red)
                        Button("common.retry") { store.retryImmediateAction() }
                        Button("common.close") { store.close() }
                    }
                    .padding(.space2)
                    .padding(.bottom, bottomObstruction)
                    .background(.regularMaterial)
                    .accessibilityElement(children: .contain)
                }
            }
            .sheet(
                isPresented: Binding(get: {
                    store.presentation.presentsSheet
                }, set: { if !$0 { store.close() } }),
                onDismiss: handleNativeManagementSheetDismissal
            ) {
                NativeManagementSheet(store: store, onSettings: onSettings, onQueue: onQueue)
                    .onAppear { nativeManagementSheetIsVisible = true }
            }
            .onChange(of: store.presentation.presentsSheet) { _, isPresented in
                if isPresented { nativeManagementSheetIsVisible = true }
                consumePendingFeedbackIfReady()
            }
            .onChange(of: store.change) { _, change in if let change { onChange(change) } }
            .onChange(of: store.state.feedbackRevision) { _, _ in consumePendingFeedbackIfReady() }
            .onChange(of: store.state.phase.name) { _, _ in consumePendingFeedbackIfReady() }
            .onChange(of: feedbackPresenter.current?.id) { _, _ in consumePendingFeedbackIfReady() }
            .onChange(of: store.state.error?.kind.name) { _, kind in if kind == "Unauthorized" { store.close(); onUnauthorized() } }
            .onDisappear {
                nativeManagementSheetIsVisible = false
                feedbackPresenter.clear()
                store.close()
                store.session.dispose()
            }
    }

    private func handleNativeManagementSheetDismissal() {
        nativeManagementSheetIsVisible = false
        consumePendingFeedbackIfReady()
    }

    private func consumePendingFeedbackIfReady() {
        let state = store.state
        guard state.phase.name == "Closed",
              let notice = state.notice,
              state.feedbackRevision > 0,
              state.feedbackRevision != presentedFeedbackRevision,
              !nativeManagementSheetIsVisible else { return }
        let revision = state.feedbackRevision
        let key = "nativeManagement.notice.\(notice)"
        let message = localizedAppString(key, locale: locale)
        var actions: [OperationFeedbackAction] = []
        if state.feedbackKind != .success {
            actions = [OperationFeedbackAction(
                id: "native-management-feedback-close-\(revision)",
                title: "common.close",
                role: .cancel,
                accessibilityIdentifier: "nativeManagement.feedback.close"
            ) { [weak store] in
                guard let store else { return }
                store.edit { store.session.clearFeedback(revision: revision) }
            }]
        }
        presentedFeedbackRevision = revision
        _ = feedbackPresenter.present(
            message: message,
            kind: state.feedbackKind,
            actions: actions,
            retainedTimeoutMillis: Int64.max,
            onDismiss: { [weak store] in
                guard let store else { return }
                store.edit { store.session.clearFeedback(revision: revision) }
            }
        )
    }
}

private let nativeTagSeparators = CharacterSet(charactersIn: ",，;；\r\n")
private let nativeTagIgnoredCharacters = CharacterSet.whitespacesAndNewlines.union(
    CharacterSet(charactersIn: "_-.[]()（）【】《》:：,，!！?？\"'“”‘’·・、/\\")
)

func nativeManagementTagKey(_ value: String) -> String {
    value
        .precomposedStringWithCompatibilityMapping
        .lowercased()
        .components(separatedBy: nativeTagIgnoredCharacters)
        .joined()
        .trimmingCharacters(in: .whitespacesAndNewlines)
}

func nativeManagementTagValues(_ input: String) -> [String] {
    nativeManagementUniqueTagValues(input.components(separatedBy: nativeTagSeparators))
}

func nativeManagementStoredTagValues(_ value: String) -> [String] {
    nativeManagementUniqueTagValues(value.components(separatedBy: .newlines))
}

private func nativeManagementUniqueTagValues(_ rawValues: [String]) -> [String] {
    var values: [String] = []
    var keys: Set<String> = []
    for rawValue in rawValues {
        let value = rawValue
            .components(separatedBy: .whitespacesAndNewlines)
            .filter { !$0.isEmpty }
            .joined(separator: " ")
        let key = nativeManagementTagKey(value)
        guard !value.isEmpty, !key.isEmpty, keys.insert(key).inserted else { continue }
        values.append(value)
    }
    return values
}

func nativeManagementMergedTagValues(current: [String], input: String) -> [String] {
    nativeManagementUniqueTagValues(current + nativeManagementTagValues(input))
}

private struct NativeManagementTagEditor: View {
    @ObservedObject var store: NativeBookManagementStore
    let value: String
    let disabled: Bool
    let onChange: (String) -> Void

    @State private var query = ""
    @State private var suggestions: [LibraryTagSuggestion] = []
    @State private var suggestionsLoading = false
    @State private var suggestionsFailed = false
    @FocusState private var inputFocused: Bool

    private var tags: [String] { nativeManagementStoredTagValues(value) }
    private var selectedKeys: Set<String> { Set(tags.map(nativeManagementTagKey)) }
    private var availableSuggestions: [LibraryTagSuggestion] {
        suggestions.filter { !selectedKeys.contains(nativeManagementTagKey($0.value)) }
    }
    private var canAddQuery: Bool {
        let key = nativeManagementTagKey(query)
        return !key.isEmpty
            && !selectedKeys.contains(key)
            && !suggestions.contains { nativeManagementTagKey($0.value) == key }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: .space2) {
            NativeTagFlowLayout(spacing: .space1Half) {
                ForEach(tags, id: \.self) { tag in
                    NativeManagementTagChip(tag: tag, disabled: disabled) {
                        remove(tag)
                    }
                }
                TextField("nativeManagement.tags.placeholder", text: $query)
                    .focused($inputFocused)
                    .accessibilityIdentifier("nativeManagement.tags.input")
                    .submitLabel(.done)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .frame(width: 148, alignment: .leading)
                    .frame(minHeight: 32)
                    .disabled(disabled)
                    .onSubmit(commitQuery)
                    .onChange(of: query) { _, value in
                        if value.rangeOfCharacter(from: nativeTagSeparators) != nil { commitQuery() }
                    }
            }
            .padding(.horizontal, .space2)
            .padding(.vertical, .space1Half)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
            .overlay {
                RoundedRectangle(cornerRadius: 12)
                    .stroke(inputFocused ? Color.accentColor.opacity(0.65) : Color.secondary.opacity(0.2), lineWidth: 1)
            }
            .contentShape(Rectangle())
            .onTapGesture { if !disabled { inputFocused = true } }

            if inputFocused {
                suggestionList
            }
        }
        .task(id: "\(inputFocused)|\(query)") {
            await loadSuggestions()
        }
    }

    @ViewBuilder private var suggestionList: some View {
        VStack(spacing: 0) {
            if suggestionsLoading {
                HStack(spacing: .space2) {
                    ProgressView().controlSize(.small)
                    Text("nativeManagement.tags.loading")
                    Spacer()
                }
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.horizontal, .space2)
                .frame(minHeight: 38)
            } else if suggestionsFailed {
                Text("nativeManagement.tags.suggestionsFailed")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, minHeight: 38, alignment: .leading)
                    .padding(.horizontal, .space2)
            }
            if canAddQuery {
                suggestionButton(
                    title: String(format: String(localized: "nativeManagement.tags.add"), normalizedTagDisplayValue(query)),
                    count: nil,
                    action: commitQuery
                )
            }
            ForEach(availableSuggestions.prefix(8)) { suggestion in
                suggestionButton(title: suggestion.label, count: suggestion.count) {
                    setTags(nativeManagementMergedTagValues(current: tags, input: suggestion.value))
                    query = ""
                    inputFocused = true
                }
            }
        }
        .background(Color.secondary.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("nativeManagement.tags.suggestions")
    }

    private func suggestionButton(title: String, count: Int?, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: .space2) {
                Image(systemName: "plus")
                    .font(.caption)
                Text(title).lineLimit(1)
                Spacer()
                if let count { Text(count, format: .number).foregroundStyle(.secondary) }
            }
            .padding(.horizontal, .space2)
            .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(disabled)
    }

    private func commitQuery() {
        let next = nativeManagementMergedTagValues(current: tags, input: query)
        query = ""
        guard next != tags else { return }
        setTags(next)
    }

    private func remove(_ tag: String) {
        setTags(tags.filter { $0 != tag })
        inputFocused = true
    }

    private func setTags(_ tags: [String]) {
        onChange(tags.joined(separator: "\n"))
    }

    private func loadSuggestions() async {
        guard inputFocused, !disabled else {
            suggestionsLoading = false
            suggestionsFailed = false
            return
        }
        suggestionsLoading = true
        suggestionsFailed = false
        do {
            try await Task.sleep(for: .milliseconds(180))
            suggestions = try await store.tagSuggestions(query: query)
            suggestionsLoading = false
        } catch is CancellationError {
            return
        } catch {
            suggestions = []
            suggestionsLoading = false
            suggestionsFailed = true
        }
    }

    private func normalizedTagDisplayValue(_ value: String) -> String {
        nativeManagementTagValues(value).first ?? value.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

private struct NativeManagementTagChip: View {
    let tag: String
    let disabled: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: .space1) {
                Text(tag)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Image(systemName: "xmark.circle.fill")
                    .font(.caption)
            }
            .padding(.leading, .space2)
            .padding(.trailing, .space1)
            .frame(minHeight: 30)
            .foregroundStyle(Color.accentColor)
            .background(Color.accentColor.opacity(0.12), in: Capsule())
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .accessibilityLabel(
            Text(String(format: String(localized: "nativeManagement.tags.remove"), tag))
        )
    }
}

private struct NativeTagFlowLayout: Layout {
    let spacing: CGFloat

    func sizeThatFits(
        proposal: ProposedViewSize,
        subviews: Subviews,
        cache: inout ()
    ) -> CGSize {
        let width = proposal.width ?? 320
        let rows = measuredRows(width: width, subviews: subviews)
        let height = rows.reduce(CGFloat.zero) { $0 + $1.height } + CGFloat(max(0, rows.count - 1)) * spacing
        return CGSize(width: width, height: height)
    }

    func placeSubviews(
        in bounds: CGRect,
        proposal: ProposedViewSize,
        subviews: Subviews,
        cache: inout ()
    ) {
        var y = bounds.minY
        for row in measuredRows(width: bounds.width, subviews: subviews) {
            var x = bounds.minX
            for element in row.elements {
                element.subview.place(
                    at: CGPoint(x: x, y: y),
                    anchor: .topLeading,
                    proposal: ProposedViewSize(element.size)
                )
                x += element.size.width + spacing
            }
            y += row.height + spacing
        }
    }

    private func measuredRows(width: CGFloat, subviews: Subviews) -> [Row] {
        var rows: [Row] = []
        var row = Row()
        for subview in subviews {
            let size = subview.sizeThatFits(ProposedViewSize(width: width, height: nil))
            if !row.elements.isEmpty, row.width + spacing + size.width > width {
                rows.append(row)
                row = Row()
            }
            row.append(subview: subview, size: size, spacing: spacing)
        }
        if !row.elements.isEmpty { rows.append(row) }
        return rows
    }

    private struct Element {
        let subview: LayoutSubview
        let size: CGSize
    }

    private struct Row {
        var elements: [Element] = []
        var width: CGFloat = 0
        var height: CGFloat = 0

        mutating func append(subview: LayoutSubview, size: CGSize, spacing: CGFloat) {
            if !elements.isEmpty { width += spacing }
            elements.append(Element(subview: subview, size: size))
            width += size.width
            height = max(height, size.height)
        }
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
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("common.cancel") {
                        if session.isDirty { discard = true } else { store.close() }
                    }
                    .disabled(store.running && !store.isPreparingPresentedSheet)
                }
                if state.phase.name == "Editing" {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("management.save") { store.run { try await session.save() } }
                            .disabled(store.running)
                    }
                }
            }
            .interactiveDismissDisabled((store.running && !store.isPreparingPresentedSheet) || session.isDirty)
            .fileImporter(isPresented: $importing, allowedContentTypes: [.jpeg, .png, .webP]) { result in
                guard pickerInteraction == session.interactionId, session.current.phase.name == "CoverUpload" else { return }
                switch result { case .success(let url): store.importCover(url, expectedInteractionId: pickerInteraction); case .failure: store.transportFailed = true }
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
                VStack(alignment: .leading, spacing: 8) {
                    managementText("nativeManagement.field.\(field.field.wireName)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    if field.field == .tags {
                        NativeManagementTagEditor(
                            store: store,
                            value: field.value,
                            disabled: store.running,
                            onChange: { value in store.edit { session.setField(field: field.field, value: value) } }
                        )
                    } else {
                        TextField(
                            text: Binding(
                                get: { field.value },
                                set: { value in store.edit { session.setField(field: field.field, value: value) } }
                            ),
                            axis: field.field.wireName == "description" ? .vertical : .horizontal
                        ) {
                            managementText("nativeManagement.field.\(field.field.wireName)")
                        }
                        .disabled(store.running)
                    }
                }
            }
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

func nativeManagementPresentation(for action: ErmaoShared.ManagementAction) -> NativeManagementPresentation {
    ["Regenerate", "ReadingStatus", "Rescan"].contains(action.name)
        ? .none
        : .sheet(actionName: action.name)
}

func nativeManagementMenuItemStatus(
    execution: NativeManagementMenuExecution?,
    target: NativeManagementTarget,
    action: ErmaoShared.ManagementAction
) -> NativeManagementMenuItemStatus {
    guard execution?.key == NativeManagementActionKey(target: target, action: action) else { return .idle }
    return execution?.status ?? .idle
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
