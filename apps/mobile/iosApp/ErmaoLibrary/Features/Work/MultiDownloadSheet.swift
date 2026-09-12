import Combine
import SwiftUI
@preconcurrency import ErmaoShared

enum DownloadManagementScope: Hashable, Sendable {
    case book
    case directory(sourceNodeID: String)
    case resource(resourceID: String)
}

@MainActor
final class MultiDownloadTreeStore: ObservableObject {
    struct Row: Identifiable {
        let entry: BookContentEntry
        let depth: Int
        var id: String { entry.id }
    }

    @Published private(set) var rootNodeID: String?
    @Published private(set) var childrenByNodeID: [String: [BookContentEntry]] = [:]
    @Published private(set) var descendantResourceIDsByNodeID: [String: Set<String>] = [:]
    @Published private(set) var resourcesByID: [String: BookResource]
    @Published private(set) var expandedNodeIDs: Set<String> = []
    @Published private(set) var loadingNodeIDs: Set<String> = []
    @Published private(set) var failedNodeIDs: Set<String> = []
    @Published private(set) var isLoading = true
    @Published private(set) var errorCode: String?

    private let context: ContentRequestContext
    private let client: any ContentClient
    private let bookID: String
    private let requestedRootSourceNodeID: String?
    private var generation = UUID()
    private var loadTask: Task<Void, Never>?
    private var nodeTasks: [String: Task<Void, Never>] = [:]

    init(
        context: ContentRequestContext,
        client: any ContentClient,
        bookID: String,
        initialResources: [BookResource],
        rootSourceNodeID: String? = nil
    ) {
        self.context = context
        self.client = client
        self.bookID = bookID
        requestedRootSourceNodeID = rootSourceNodeID
        resourcesByID = Dictionary(uniqueKeysWithValues: initialResources.map { ($0.id, $0) })
    }

    var visibleRows: [Row] {
        guard let rootNodeID else { return [] }
        return flattenedChildren(of: rootNodeID, depth: 0)
    }

    func load(hierarchy: Bool) {
        guard loadTask == nil else { return }
        let currentGeneration = UUID()
        generation = currentGeneration
        isLoading = true
        loadTask = Task { [weak self] in
            guard let self else { return }
            var didFail = false

            do {
                let loadedResources = try await loadAllResources()
                guard isCurrent(currentGeneration) else { return }
                // A successful full pagination is authoritative. Preserve the
                // initial detail snapshot only when the request fails, so a
                // server-side deletion cannot leave a stale selectable row.
                resourcesByID = loadedResources
            } catch is CancellationError {
                return
            } catch {
                didFail = true
            }

            if hierarchy {
                do {
                    let page = try await loadFolder(sourceNodeID: requestedRootSourceNodeID)
                    guard isCurrent(currentGeneration) else { return }
                    apply(page)
                    rootNodeID = page.currentNode.sourceNodeID
                    expandedNodeIDs.insert(page.currentNode.sourceNodeID)
                } catch is CancellationError {
                    return
                } catch {
                    didFail = true
                }
            }

            guard isCurrent(currentGeneration) else { return }
            isLoading = false
            errorCode = didFail ? "MULTI_DOWNLOAD_TREE_LOAD_FAILED" : nil
            loadTask = nil
        }
    }

    func retry(hierarchy: Bool) {
        cancel()
        load(hierarchy: hierarchy)
    }

    func cancel() {
        generation = UUID()
        loadTask?.cancel()
        loadTask = nil
        nodeTasks.values.forEach { $0.cancel() }
        nodeTasks.removeAll()
        loadingNodeIDs.removeAll()
    }

    func toggleExpanded(_ entry: BookContentEntry) {
        guard entry.isSourceFolder else { return }
        if expandedNodeIDs.contains(entry.sourceNodeID) {
            expandedNodeIDs.remove(entry.sourceNodeID)
            return
        }
        expandedNodeIDs.insert(entry.sourceNodeID)
        ensureLoaded(entry)
    }

    func ensureLoaded(_ entry: BookContentEntry, completion: (() -> Void)? = nil) {
        let nodeID = entry.sourceNodeID
        if childrenByNodeID[nodeID] != nil {
            completion?()
            return
        }
        guard !loadingNodeIDs.contains(nodeID) else { return }
        let currentGeneration = generation
        loadingNodeIDs.insert(nodeID)
        failedNodeIDs.remove(nodeID)
        let task = Task { [weak self] in
            guard let self else { return }
            do {
                let page = try await loadFolder(sourceNodeID: nodeID)
                guard isCurrent(currentGeneration), !Task.isCancelled else { return }
                apply(page)
                loadingNodeIDs.remove(nodeID)
                nodeTasks[nodeID] = nil
                completion?()
            } catch is CancellationError {
                guard isCurrent(currentGeneration) else { return }
                loadingNodeIDs.remove(nodeID)
                nodeTasks[nodeID] = nil
            } catch {
                guard isCurrent(currentGeneration) else { return }
                loadingNodeIDs.remove(nodeID)
                failedNodeIDs.insert(nodeID)
                nodeTasks[nodeID] = nil
            }
        }
        nodeTasks[nodeID] = task
    }

    func retryNode(_ entry: BookContentEntry) {
        failedNodeIDs.remove(entry.sourceNodeID)
        childrenByNodeID[entry.sourceNodeID] = nil
        ensureLoaded(entry)
    }

    func resources(for scope: DownloadManagementScope) -> [BookResource] {
        let ids: Set<String>
        switch scope {
        case .book:
            ids = Set(resourcesByID.keys)
        case let .directory(sourceNodeID):
            let knownDescendants = descendantResourceIDsByNodeID[sourceNodeID] ?? []
            ids = knownDescendants.isEmpty
                ? Set(resourcesByID.values.filter { $0.sourceNodeID == sourceNodeID }.map(\.id))
                : knownDescendants
        case let .resource(resourceID):
            ids = [resourceID]
        }
        return ids.compactMap { resourcesByID[$0] }
            .sorted { lhs, rhs in
                if lhs.sortOrder != rhs.sortOrder { return lhs.sortOrder < rhs.sortOrder }
                return lhs.title.localizedStandardCompare(rhs.title) == .orderedAscending
            }
    }

    private func isCurrent(_ candidate: UUID) -> Bool {
        generation == candidate && !Task.isCancelled
    }

    private func loadFolder(sourceNodeID: String?) async throws -> BookContentsPage {
        let first = try await client.fetchBookContents(
            context: context,
            bookID: bookID,
            sourceNodeID: sourceNodeID,
            sort: .nameAscending,
            page: 1,
            pageSize: 200
        )
        guard first.totalPages > 1 else { return first }
        var entries = first.entries
        for pageNumber in 2...first.totalPages {
            try Task.checkCancellation()
            let page = try await client.fetchBookContents(
                context: context,
                bookID: bookID,
                sourceNodeID: sourceNodeID,
                sort: .nameAscending,
                page: pageNumber,
                pageSize: 200
            )
            entries.append(contentsOf: page.entries)
        }
        return BookContentsPage(
            bookID: first.bookID,
            currentSourceNodeID: first.currentSourceNodeID,
            currentResourceID: first.currentResourceID,
            currentNode: first.currentNode,
            currentResourceIDs: first.currentResourceIDs,
            parentSourceNodeID: first.parentSourceNodeID,
            breadcrumbs: first.breadcrumbs,
            entries: entries,
            page: 1,
            pageSize: first.pageSize,
            total: first.total,
            totalPages: first.totalPages
        )
    }

    private func loadAllResources() async throws -> [String: BookResource] {
        var result: [String: BookResource] = [:]
        var pageNumber = 1
        while true {
            try Task.checkCancellation()
            let page = try await client.fetchBookResources(
                context: context,
                bookID: bookID,
                page: pageNumber,
                pageSize: 100
            )
            result.merge(
                Dictionary(uniqueKeysWithValues: page.resources.map { ($0.id, $0) }),
                uniquingKeysWith: { _, latest in latest }
            )
            guard pageNumber < page.totalPages else { return result }
            pageNumber += 1
        }
    }

    private func apply(_ page: BookContentsPage) {
        let nodeID = page.currentNode.sourceNodeID
        childrenByNodeID[nodeID] = page.entries
        descendantResourceIDsByNodeID[nodeID] = Set(page.currentResourceIDs)
    }

    private func flattenedChildren(of nodeID: String, depth: Int) -> [Row] {
        (childrenByNodeID[nodeID] ?? []).flatMap { entry -> [Row] in
            let row = Row(entry: entry, depth: depth)
            guard entry.isSourceFolder, expandedNodeIDs.contains(entry.sourceNodeID) else {
                return [row]
            }
            return [row] + flattenedChildren(of: entry.sourceNodeID, depth: depth + 1)
        }
    }
}

struct MultiDownloadSheet: View {
    private enum Mode { case overview, selection }

    private struct PendingRemoval: Identifiable {
        let ids: Set<String>
        var id: String { ids.sorted().joined(separator: ",") }
    }

    private struct ActionFeedback: Identifiable {
        let id = UUID()
        let text: String
        let failureCode: String?
        let isError: Bool
    }

    let context: ContentRequestContext
    let detail: BookDetailContent
    let scope: DownloadManagementScope
    @ObservedObject var downloads: DownloadCenterStore
    let requestOpenReader: (ReaderHandoff) -> Void
    let onDismiss: () -> Void

    @StateObject private var tree: MultiDownloadTreeStore
    @State private var mode: Mode = .overview
    @State private var bookTitleExpanded = false
    @State private var fullBookTitleHeight: CGFloat = 0
    @State private var collapsedBookTitleHeight: CGFloat = 0
    @State private var selectedResourceIDs: Set<String> = []
    @State private var isActing = false
    @State private var pendingRemoval: PendingRemoval?
    @State private var actionFeedback: ActionFeedback?
    @State private var feedbackEventID: UUID?
    @Environment(\.locale) private var locale
    @Environment(\.appTheme) private var theme
    @StateObject private var feedbackPresenter = OperationFeedbackPresenter()

    init(
        context: ContentRequestContext,
        client: any ContentClient,
        detail: BookDetailContent,
        scope: DownloadManagementScope = .book,
        rootSourceNodeID: String? = nil,
        downloads: DownloadCenterStore,
        requestOpenReader: @escaping (ReaderHandoff) -> Void,
        onDismiss: @escaping () -> Void
    ) {
        self.context = context
        self.detail = detail
        self.scope = scope
        self.downloads = downloads
        self.requestOpenReader = requestOpenReader
        self.onDismiss = onDismiss
        let requestedRoot: String?
        switch scope {
        case .book:
            requestedRoot = rootSourceNodeID ?? detail.rootSourceNodeID
        case let .directory(sourceNodeID):
            requestedRoot = sourceNodeID
        case .resource:
            requestedRoot = nil
        }
        _tree = StateObject(
            wrappedValue: MultiDownloadTreeStore(
                context: context,
                client: client,
                bookID: detail.book.id,
                initialResources: detail.resources,
                rootSourceNodeID: requestedRoot
            )
        )
    }

    private var loadsHierarchy: Bool {
        if case .resource = scope { return false }
        return true
    }

    private var catalogResources: [BookResource] {
        var knownResourceIDs = Set(tree.resourcesByID.keys)
        let knownDirectoryResourceIDs: Set<String>
        if case let .directory(sourceNodeID) = scope {
            let loadedDescendants = tree.descendantResourceIDsByNodeID[sourceNodeID] ?? []
            let resourcesWithNodeIdentity = tree.resourcesByID.values
                .filter { $0.sourceNodeID == sourceNodeID }
                .map(\.id)
            knownDirectoryResourceIDs = loadedDescendants.union(resourcesWithNodeIdentity)
        } else {
            knownDirectoryResourceIDs = []
        }

        return downloads.records.compactMap { record in
            guard !knownResourceIDs.contains(record.resourceID) else { return nil }
            switch scope {
            case .book:
                guard record.bookID == detail.book.id else { return nil }
            case let .resource(resourceID):
                guard record.bookID == detail.book.id, record.resourceID == resourceID else { return nil }
            case .directory:
                // A directory has no persisted source-node identity in the
                // catalog. Include only IDs already proven to belong to this
                // subtree by the current server snapshot.
                guard knownDirectoryResourceIDs.contains(record.resourceID) else { return nil }
            }
            knownResourceIDs.insert(record.resourceID)
            return DownloadManagementAdapter.catalogResource(record)
        }
        .sorted { lhs, rhs in
            lhs.title.localizedStandardCompare(rhs.title) == .orderedAscending
        }
    }

    private var scopedResources: [BookResource] {
        var byID = Dictionary(uniqueKeysWithValues: tree.resources(for: scope).map { ($0.id, $0) })
        for resource in catalogResources where byID[resource.id] == nil {
            byID[resource.id] = resource
        }
        return byID.values.sorted { lhs, rhs in
            if lhs.sortOrder != rhs.sortOrder { return lhs.sortOrder < rhs.sortOrder }
            return lhs.title.localizedStandardCompare(rhs.title) == .orderedAscending
        }
    }

    private var scopedResourceIDs: Set<String> { Set(scopedResources.map(\.id)) }
    private var projectedResources: [DownloadManagementResource] {
        downloads.managementResources(for: scopedResources)
    }

    var body: some View {
        NavigationStack {
            Group {
                if tree.isLoading && scopedResources.isEmpty {
                    ProgressView()
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    List {
                        bookHeader
                        if tree.errorCode != nil { loadErrorRow }
                        if let actionFeedback { actionFeedbackRow(actionFeedback) }
                        if !tree.visibleRows.isEmpty && loadsHierarchy {
                            ForEach(tree.visibleRows) { row in
                                nodeRow(row)
                            }
                            ForEach(catalogResources) { resource in
                                resourceRow(resource, depth: 0)
                            }
                        } else {
                            ForEach(scopedResources) { resource in
                                resourceRow(resource, depth: 0)
                            }
                        }
                        if scopedResources.isEmpty, !tree.isLoading, tree.errorCode == nil {
                            emptyScopeRow
                        }
                    }
                    .listStyle(.plain)
                }
            }
            .overlay(alignment: .bottom) {
                OperationFeedbackOverlay(presenter: feedbackPresenter, clearsOnDisappear: false)
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { toolbarContent }
            .safeAreaInset(edge: .bottom, spacing: 0) {
                if mode == .selection { selectionBar }
            }
        }
        .tint(theme.textSecondary)
        .task {
            tree.load(hierarchy: loadsHierarchy)
            _ = await downloads.reloadAndAwait(expectedNamespace: context.namespaceKey)
        }
        .onDisappear {
            clearOwnedFeedback()
            tree.cancel()
        }
        .onReceive(downloads.$records) { _ in pruneSelection() }
        .onReceive(tree.$resourcesByID) { _ in pruneSelection() }
        .confirmationDialog(
            "work.downloadManagement.remove.confirm.title",
            isPresented: Binding(
                get: { pendingRemoval != nil },
                set: { if !$0 { pendingRemoval = nil } }
            ),
            titleVisibility: .visible,
            presenting: pendingRemoval
        ) { request in
            Button("work.downloadManagement.remove.confirm.action", role: .destructive) {
                pendingRemoval = nil
                perform(action: .remove, resourceIDs: request.ids)
            }
            Button("common.cancel", role: .cancel) { pendingRemoval = nil }
        } message: { _ in
            Text("work.downloadManagement.remove.confirm.message")
        }
    }

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItem(placement: .cancellationAction) {
            Button {
                if mode == .selection { leaveSelectionMode() } else { onDismiss() }
            } label: {
                if mode == .selection {
                    Label("common.cancel", systemImage: "xmark").labelStyle(.titleAndIcon)
                } else {
                    Image(systemName: "xmark")
                        .accessibilityLabel(Text("common.close"))
                }
            }
            .disabled(isActing)
            .accessibilityIdentifier(
                mode == .selection
                    ? "work.downloadManagement.cancel"
                    : "work.downloadManagement.close"
            )
        }
        ToolbarItem(placement: .principal) {
            Text(mode == .selection ? String(format: String(localized: "work.downloadManagement.selectedCount"), selectedResourceIDs.count) : String(localized: "work.downloadManagement.title"))
                .font(.headline)
                .accessibilityIdentifier("work.downloadManagement.title")
        }
        ToolbarItem(placement: .confirmationAction) {
            if mode == .overview {
                Button { mode = .selection } label: {
                    Label("work.downloadManagement.select", systemImage: "checklist").labelStyle(.titleAndIcon)
                }
                    .disabled(isActing || !projectedResources.contains(where: { $0.selectable }))
                    .accessibilityIdentifier("work.downloadManagement.select")
            } else {
                Button { toggleAll() } label: {
                    Label(selectionControlTitle, systemImage: "checkmark.square").labelStyle(.titleAndIcon)
                }
                    .disabled(isActing)
                    .accessibilityIdentifier("work.downloadManagement.selectAll")
            }
        }
    }

    private var bookHeader: some View {
        Section {
            VStack(alignment: .leading, spacing: .spaceHalf) {
                Text(detail.book.title)
                    .appTextStyle(.caption)
                    .foregroundStyle(theme.textSecondary)
                    .lineLimit(bookTitleExpanded ? nil : 2)
                    .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height in
                        if !bookTitleExpanded { collapsedBookTitleHeight = height }
                    }
                    .background(alignment: .topLeading) {
                        Text(detail.book.title)
                            .appTextStyle(.caption)
                            .fixedSize(horizontal: false, vertical: true)
                            .hidden()
                            .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { fullBookTitleHeight = $0 }
                    }
                if bookTitleExpanded || fullBookTitleHeight > collapsedBookTitleHeight {
                Button {
                    bookTitleExpanded.toggle()
                } label: {
                    Label(bookTitleExpanded ? "work.description.collapse" : "work.description.expand",
                          systemImage: bookTitleExpanded ? "chevron.up" : "chevron.down")
                }
                .buttonStyle(.borderless)
                .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget, alignment: .trailing)
                }
            }
            .padding(.vertical, .space1)
            .listRowSeparator(.hidden)
        }
    }

    private var loadErrorRow: some View {
        HStack(spacing: .space1) {
            Image(systemName: "wifi.exclamationmark")
                .foregroundStyle(theme.textTertiary)
            Text("work.downloadManagement.load.error")
                .appTextStyle(.caption)
                .foregroundStyle(theme.textSecondary)
            Spacer()
            Button { tree.retry(hierarchy: loadsHierarchy) } label: {
                Label("common.retry", systemImage: "arrow.clockwise")
            }
                .buttonStyle(.borderless)
                .disabled(isActing)
        }
        .padding(.vertical, .spaceHalf)
        .listRowSeparator(.hidden)
        .accessibilityIdentifier("work.downloadManagement.load.error")
    }

    private var emptyScopeRow: some View {
        HStack {
            Spacer(minLength: 0)
            Text("work.downloadManagement.empty")
                .appTextStyle(.body)
                .foregroundStyle(theme.textSecondary)
                .multilineTextAlignment(.center)
            Spacer(minLength: 0)
        }
        .padding(.vertical, .space3)
        .listRowSeparator(.hidden)
        .accessibilityIdentifier("work.downloadManagement.empty")
    }

    private func actionFeedbackRow(_ feedback: ActionFeedback) -> some View {
        Label {
            VStack(alignment: .leading, spacing: .spaceHalf) {
                Text(feedback.text)
                if let code = feedback.failureCode {
                    Text(downloadFailureMessage(code))
                        .appTextStyle(.caption)
                }
            }
        } icon: {
            Image(systemName: feedback.isError ? "exclamationmark.circle" : "checkmark.circle")
        }
        .appTextStyle(.caption)
        .foregroundStyle(feedback.isError ? .red : theme.textSecondary)
        .padding(.vertical, .spaceHalf)
        .listRowSeparator(.hidden)
        .accessibilityIdentifier("work.downloadManagement.feedback")
    }

    @ViewBuilder
    private func nodeRow(_ row: MultiDownloadTreeStore.Row) -> some View {
        let entry = row.entry
        if entry.isSourceFolder {
            folderRow(entry, depth: row.depth)
        } else if let resourceID = entry.resourceID,
                  let resource = tree.resourcesByID[resourceID],
                  scopedResourceIDs.contains(resourceID) {
            resourceRow(resource, depth: row.depth)
        } else {
            HStack {
                Text(entry.title).foregroundStyle(theme.textSecondary)
                Spacer()
                Text("work.downloadManagement.status.unavailable")
                    .appTextStyle(.caption)
                    .foregroundStyle(theme.textTertiary)
            }
            .padding(.leading, CGFloat(row.depth) * 20)
        }
    }

    private func folderRow(_ entry: BookContentEntry, depth: Int) -> some View {
        let descendantIDs = tree.descendantResourceIDsByNodeID[entry.sourceNodeID] ?? []
        let descendantCount = tree.childrenByNodeID[entry.sourceNodeID] == nil ? nil : descendantIDs.count
        let mark = selectionMark(for: descendantIDs)
        return HStack(spacing: .space1) {
            Button { tree.toggleExpanded(entry) } label: {
                Image(systemName: tree.expandedNodeIDs.contains(entry.sourceNodeID) ? "chevron.down" : "chevron.right")
                    .frame(width: .iosMinimumTouchTarget, height: .iosMinimumTouchTarget)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(Text(tree.expandedNodeIDs.contains(entry.sourceNodeID) ? "work.downloadManagement.folder.collapse" : "work.downloadManagement.folder.expand"))

            if mode == .selection {
                Button {
                    tree.ensureLoaded(entry) { toggleDirectory(entry.sourceNodeID) }
                } label: {
                    if tree.loadingNodeIDs.contains(entry.sourceNodeID) {
                        ProgressView().controlSize(.small).frame(width: .iosMinimumTouchTarget, height: .iosMinimumTouchTarget)
                    } else {
                        Image(systemName: selectionImage(mark))
                            .foregroundStyle(mark == .unselected ? theme.textSecondary : theme.actionAccent)
                            .frame(width: .iosMinimumTouchTarget, height: .iosMinimumTouchTarget)
                    }
                }
                .buttonStyle(.plain)
                .disabled(isActing || tree.loadingNodeIDs.contains(entry.sourceNodeID))
                .accessibilityLabel(Text(entry.title))
                .accessibilityValue(Text(directoryAccessibilityValue(mark, count: descendantCount)))
                .accessibilityIdentifier("work.downloadManagement.checkbox.folder.\(entry.sourceNodeID)")
            }

            Button { tree.toggleExpanded(entry) } label: {
                VStack(alignment: .leading, spacing: .spaceHalf) {
                    Text(entry.title).appTextStyle(.body)
                    if let descendantCount {
                        Text(String(format: String(localized: "work.downloadManagement.volumeCount"), descendantCount))
                            .appTextStyle(.caption)
                            .foregroundStyle(theme.textSecondary)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
        .padding(.leading, CGFloat(depth) * 20)
        .contentShape(Rectangle())
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("work.multiDownload.folder.\(entry.sourceNodeID)")
        .accessibilityValue(Text(directoryAccessibilityValue(mark, count: descendantCount)))
    }

    private func resourceRow(_ resource: BookResource, depth: Int) -> some View {
        let projected = downloads.managementResource(for: resource)
        let selected = selectedResourceIDs.contains(resource.id)
        return HStack(alignment: .center, spacing: .spaceHalf) {
            if mode == .selection {
                Button { toggleResource(resource.id) } label: {
                    Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                        .foregroundStyle(selected ? theme.actionAccent : theme.textSecondary)
                        .frame(width: .iosMinimumTouchTarget, height: .iosMinimumTouchTarget)
                }
                .buttonStyle(.plain)
                .disabled(!projected.selectable || isActing)
                .accessibilityLabel(Text(resource.title))
                .accessibilityValue(Text(selected ? "work.downloadManagement.selection.all" : "work.downloadManagement.selection.none"))
                .accessibilityIdentifier("work.downloadManagement.checkbox.\(resource.id)")
            }

            VStack(alignment: .leading, spacing: .spaceHalf) {
                Text("Ag")
                        .appTextStyle(.body)
                        .hidden()
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .overlay(alignment: .leading) {
                            Text(DownloadManagementPolicy.shared.displayTitle(bookTitle: detail.book.title, resourceTitle: resource.title))
                                .appTextStyle(.body)
                                .lineLimit(1)
                                .fixedSize(horizontal: true, vertical: false)
                                .accessibilityLabel(Text(resource.title))
                        }
                        .clipped()
                        .frame(maxWidth: .infinity, alignment: .leading)

                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .firstTextBaseline, spacing: .spaceHalf) {
                        resourceMetadata(resource).fixedSize()
                        Text("·").appTextStyle(.caption).foregroundStyle(theme.textSecondary)
                        resourceStatus(resource, projected: projected).fixedSize()
                    }
                    VStack(alignment: .leading, spacing: .spaceHalf) {
                        resourceMetadata(resource)
                        resourceStatus(resource, projected: projected)
                    }
                }
                if (projected.status == .downloading || projected.status == .paused),
                   let progress = downloads.record(for: resource.id)?.progress {
                    ProgressView(value: progress).tint(theme.textSecondary)
                }
                if [.failedretryable, .failedterminal, .invalidlocal].contains(projected.status),
                   let code = downloads.record(for: resource.id)?.stableErrorCode {
                    Text(downloadFailureMessage(code)).appTextStyle(.caption).foregroundStyle(.red)
                }
            }
            .frame(maxWidth: .infinity, minHeight: CGFloat.iosMinimumTouchTarget + .spaceHalf, alignment: .leading)
            .contentShape(Rectangle())
            .onTapGesture {
                if mode == .selection {
                    toggleResource(resource.id)
                } else if projected.actions.contains(.open) {
                    perform(action: .open, resourceIDs: [resource.id])
                }
            }
            if mode == .overview {
                HStack(spacing: .spaceHalf) {
                    if let action = projected.primaryAction, action != .open {
                        Button {
                            perform(action: action, resourceIDs: [resource.id])
                        } label: {
                            Image(systemName: actionImage(action))
                                .frame(width: .iosMinimumTouchTarget, height: .iosMinimumTouchTarget)
                        }
                        .buttonStyle(.borderless)
                        .disabled(isActing)
                        .accessibilityLabel(Text(actionLabel(action)))
                        .accessibilityIdentifier("work.downloadManagement.primary.\(resource.id)")
                    }
                    if projected.actions.contains(.remove) {
                        Button {
                            pendingRemoval = PendingRemoval(ids: [resource.id])
                        } label: {
                            Image(systemName: "trash")
                                .frame(width: .iosMinimumTouchTarget, height: .iosMinimumTouchTarget)
                        }
                        .buttonStyle(.borderless)
                        .disabled(isActing)
                        .accessibilityLabel(Text("work.downloadManagement.remove"))
                        .accessibilityIdentifier("work.downloadManagement.remove.\(resource.id)")
                    }
                }
            }
        }
        .padding(.leading, CGFloat(depth) * 20)
        .listRowInsets(EdgeInsets(top: .space1, leading: mode == .selection ? .space1 : .space2,
                                 bottom: .space1, trailing: .space2))
        .alignmentGuide(.listRowSeparatorLeading) { _ in
            CGFloat(depth) * 20 + (mode == .selection ? CGFloat.iosMinimumTouchTarget + .spaceHalf : 0)
        }
        .contentShape(Rectangle())
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("work.multiDownload.resource.\(resource.id)")
        .accessibilityValue(Text(statusText(resource, projected: projected)))
    }

    private func resourceMetadata(_ resource: BookResource) -> some View {
        Text([resource.format, resource.sizeLabel].compactMap { $0 }.joined(separator: " · "))
            .appTextStyle(.caption)
            .foregroundStyle(theme.textSecondary)
    }

    private func resourceStatus(_ resource: BookResource, projected: DownloadManagementResource) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: .spaceHalf) {
            if projected.status == .completed { Image(systemName: "checkmark") }
            Text(statusText(resource, projected: projected))
                .accessibilityIdentifier("work.downloadManagement.status.\(resource.id)")
        }
        .appTextStyle(.caption)
        .foregroundStyle(statusColor(projected.status))
    }

    private var availableBatchActions: [DownloadManagementAction] {
        [.download, .pause, .resume, .retry, .remove].filter { !applicableIDs(for: $0).isEmpty }
    }

    private var selectionBar: some View {
        let actions = availableBatchActions
        let primary = actions.first(where: { $0 != .remove }) ?? actions.first ?? .download
        let ids = applicableIDs(for: primary)
        return VStack(spacing: .space1) {
            Text(selectionSummary)
                .appTextStyle(.caption)
                .foregroundStyle(theme.textSecondary)
                .accessibilityIdentifier("work.downloadManagement.selectedCount")
            HStack(spacing: .space1) {
                Button {
                    executeBatch(primary)
                } label: {
                    Label(actionLabel(primary, count: ids.count), systemImage: actionImage(primary))
                        .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget)
                }
                .buttonStyle(.bordered)
                .buttonBorderShape(.roundedRectangle(radius: CGFloat(GeneratedDesignTokens.Radii.control)))
                .background {
                    if ids.isEmpty || isActing {
                        RoundedRectangle(cornerRadius: CGFloat(GeneratedDesignTokens.Radii.control))
                            .fill(Color(hex: GeneratedDesignTokens.App.navigation))
                    }
                }
                .disabled(ids.isEmpty || isActing)
                .accessibilityIdentifier("work.downloadManagement.batchPrimary")
                if actions.contains(where: { $0 != primary }) {
                    Menu {
                        ForEach(actions.filter { $0 != primary }, id: \.self) { action in
                            Button(role: action == .remove ? .destructive : nil) {
                                executeBatch(action)
                            } label: {
                                Label(actionLabel(action, count: applicableIDs(for: action).count), systemImage: actionImage(action))
                            }
                        }
                    } label: {
                        Image(systemName: "ellipsis")
                            .frame(width: .iosMinimumTouchTarget, height: .iosMinimumTouchTarget)
                    }
                    .disabled(isActing)
                    .accessibilityLabel(Text("work.downloadManagement.actions"))
                    .accessibilityIdentifier("work.downloadManagement.actions")
                }
            }
        }
        .padding(.horizontal, .space2)
        .padding(.vertical, .space1)
        .background(theme.surface)
        .overlay(alignment: .top) { Divider().overlay(theme.divider) }
    }

    private func executeBatch(_ action: DownloadManagementAction) {
        let ids = Set(applicableIDs(for: action))
        guard !ids.isEmpty else { return }
        if action == .remove { pendingRemoval = PendingRemoval(ids: ids) }
        else { perform(action: action, resourceIDs: ids) }
    }

    private var selectionSummary: String {
        guard !selectedResourceIDs.isEmpty else {
            return String(localized: "work.downloadManagement.selection.hint")
        }
        let count = String(format: String(localized: "work.downloadManagement.selectedCount"), selectedResourceIDs.count)
        let selected = scopedResources.filter { selectedResourceIDs.contains($0.id) }
        let sizes = selected.compactMap(\.sizeBytes)
        guard sizes.count == selectedResourceIDs.count, sizes.allSatisfy({ $0 > 0 }) else { return count }
        let size = sizes.reduce(Int64(0), +).formatted(.byteCount(style: .file).locale(locale))
        return "\(count) · \(size)"
    }

    private func actionImage(_ action: DownloadManagementAction) -> String {
        switch action {
        case .download: "arrow.down.to.line"
        case .pause: "pause.circle"
        case .resume: "play.circle"
        case .retry: "arrow.clockwise"
        case .open: "arrow.up.right.square"
        case .remove: "trash"
        default: "ellipsis"
        }
    }
    private var selectionControlTitle: LocalizedStringKey {
        let mark = selectionMark(for: scopedResourceIDs)
        return mark == .selected ? "work.downloadManagement.clearSelection" : "work.downloadManagement.selectAll"
    }

    private func applicableIDs(for action: DownloadManagementAction) -> [String] {
        DownloadManagementPolicy.shared.applicable(
            action: action,
            selectedResourceIds: selectedResourceIDs,
            resources: projectedResources
        )
    }

    private func perform(action: DownloadManagementAction, resourceIDs: Set<String>) {
        guard !resourceIDs.isEmpty, !isActing, downloads.isCurrent(context) else { return }
        isActing = true
        clearOwnedFeedback()
        actionFeedback = nil
        Task { @MainActor in
            guard downloads.isCurrent(context) else {
                isActing = false
                return
            }
            let results = await downloads.executeManagement(
                action: action,
                selectedResourceIDs: resourceIDs,
                resources: scopedResources,
                expectedNamespace: context.namespaceKey
            )
            guard !Task.isCancelled, downloads.isCurrent(context) else {
                isActing = false
                return
            }
            let accepted = results.filter { $0.outcome == .accepted }.count
            let completed = results.filter { $0.outcome == .completed }.count
            let skipped = results.filter { $0.outcome == .skipped }.count
            let failed = results.filter { $0.outcome == .failed }.count
            let failedCode = results.first(where: { $0.outcome == .failed })?.failureCode
            if mode == .selection, action == .remove {
                selectedResourceIDs.subtract(results.filter { $0.outcome == .completed }.map(\.resourceId))
                pruneSelection()
            }

            if action == .open {
                guard let result = results.first,
                      result.outcome == .completed,
                      let handoff = await downloads.verifiedReaderHandoff(
                          resourceID: result.resourceId,
                          expectedNamespace: context.namespaceKey
                      )
                else {
                    actionFeedback = ActionFeedback(
                        text: String(format: localizedAppString("work.downloadManagement.feedback.failed", locale: locale), locale: locale, 1),
                        failureCode: failedCode ?? "DOWNLOAD_LOCAL_FILE_INVALID",
                        isError: true
                    )
                    isActing = false
                    return
                }
                isActing = false
                requestOpenReader(handoff)
                return
            }

            var outcomeSummaries: [String] = []
            if accepted > 0 {
                outcomeSummaries.append(String(format: localizedAppString("work.downloadManagement.feedback.accepted", locale: locale), locale: locale, accepted))
            }
            if completed > 0 {
                outcomeSummaries.append(String(format: localizedAppString("work.downloadManagement.feedback.completed", locale: locale), locale: locale, completed))
            }
            if skipped > 0 {
                outcomeSummaries.append(String(format: localizedAppString("work.downloadManagement.feedback.skipped", locale: locale), locale: locale, skipped))
            }
            if failed > 0 {
                outcomeSummaries.append(String(format: localizedAppString("work.downloadManagement.feedback.failed", locale: locale), locale: locale, failed))
            }
            if !outcomeSummaries.isEmpty {
                let text = outcomeSummaries.joined(separator: " · ")
                if failed > 0 || skipped > 0 {
                    actionFeedback = ActionFeedback(
                        text: text,
                        failureCode: failedCode,
                        isError: true
                    )
                } else {
                    presentSuccessFeedback(text)
                }
            }
            isActing = false
        }
    }

    private func presentSuccessFeedback(_ message: String) {
        guard let eventID = feedbackPresenter.present(
            message: message,
            kind: .success,
            retainedTimeoutMillis: 5_000
        ) else { return }
        feedbackEventID = eventID
    }

    private func clearOwnedFeedback() {
        guard let feedbackEventID else { return }
        feedbackPresenter.dismiss(id: feedbackEventID)
        self.feedbackEventID = nil
    }

    private func leaveSelectionMode() {
        selectedResourceIDs.removeAll()
        mode = .overview
    }

    private func toggleAll() {
        selectedResourceIDs = DownloadManagementPolicy.shared.toggleSelection(
            selected: selectedResourceIDs,
            candidates: scopedResourceIDs,
            resources: projectedResources
        )
    }

    private func toggleResource(_ resourceID: String) {
        guard mode == .selection else { return }
        let candidates: Set<String> = [resourceID]
        selectedResourceIDs = DownloadManagementPolicy.shared.toggleSelection(
            selected: selectedResourceIDs,
            candidates: candidates,
            resources: projectedResources
        )
    }

    private func toggleDirectory(_ nodeID: String) {
        guard mode == .selection else { return }
        let candidates = tree.descendantResourceIDsByNodeID[nodeID] ?? []
        selectedResourceIDs = DownloadManagementPolicy.shared.toggleSelection(
            selected: selectedResourceIDs,
            candidates: candidates,
            resources: projectedResources
        )
    }

    private func pruneSelection() {
        selectedResourceIDs = DownloadManagementPolicy.shared.toggleSelection(
            selected: selectedResourceIDs,
            candidates: [],
            resources: projectedResources
        )
    }

    private func selectionMark(for candidates: Set<String>) -> MultiDownloadSelectionMark {
        DownloadManagementPolicy.shared.selectionMark(
            selected: selectedResourceIDs,
            candidates: candidates,
            resources: projectedResources
        )
    }

    private func selectionImage(_ mark: MultiDownloadSelectionMark) -> String {
        switch mark {
        case .unselected: "square"
        case .selected: "checkmark.square.fill"
        case .mixed: "minus.square.fill"
        default: "square"
        }
    }

    private func directoryAccessibilityValue(_ mark: MultiDownloadSelectionMark, count: Int?) -> String {
        let state: String
        switch mark {
        case .unselected: state = String(localized: "work.downloadManagement.selection.none")
        case .selected: state = String(localized: "work.downloadManagement.selection.all")
        case .mixed: state = String(localized: "work.downloadManagement.selection.mixed")
        default: state = String(localized: "work.downloadManagement.selection.none")
        }
        guard let count else { return state }
        return "\(state), \(String(format: String(localized: "work.downloadManagement.volumeCount"), count))"
    }

    private func statusText(_ resource: BookResource, projected: DownloadManagementResource) -> String {
        let status: String
        switch projected.status {
        case .notdownloaded: status = String(localized: "work.downloadManagement.status.notDownloaded")
        case .queued: status = String(localized: "work.downloadManagement.status.queued")
        case .downloading: status = String(localized: "work.downloadManagement.status.downloading")
        case .paused: status = String(localized: "work.downloadManagement.status.paused")
        case .completed: status = String(localized: "work.downloadManagement.status.completed")
        case .invalidlocal: status = String(localized: "work.downloadManagement.status.invalidLocal")
        case .failedretryable: status = String(localized: "work.downloadManagement.status.failedRetryable")
        case .failedterminal: status = String(localized: "work.downloadManagement.status.failedTerminal")
        case .unavailable: status = String(localized: "work.downloadManagement.status.unavailable")
        default: status = String(localized: "work.downloadManagement.status.unavailable")
        }
        guard (projected.status == .downloading || projected.status == .paused),
              let progress = downloads.record(for: resource.id)?.progress else { return status }
        return "\(status) · \(progress.formatted(.percent.precision(.fractionLength(0)).locale(locale)))"
    }

    private func statusColor(_ status: DownloadManagementStatus) -> Color {
        switch status {
        case .completed: theme.textSecondary
        case .failedretryable, .failedterminal, .invalidlocal: .red
        default: theme.textSecondary
        }
    }

    private func actionLabel(_ action: DownloadManagementAction, count: Int? = nil) -> String {
        let format: String
        switch action {
        case .download: format = count == nil ? String(localized: "work.downloadManagement.download") : String(localized: "work.downloadManagement.download.count")
        case .pause: format = count == nil ? String(localized: "work.downloadManagement.pause") : String(localized: "work.downloadManagement.pause.count")
        case .resume: format = count == nil ? String(localized: "work.downloadManagement.resume") : String(localized: "work.downloadManagement.resume.count")
        case .retry: format = count == nil ? String(localized: "work.downloadManagement.retry") : String(localized: "work.downloadManagement.retry.count")
        case .remove: format = count == nil ? String(localized: "work.downloadManagement.remove") : String(localized: "work.downloadManagement.remove.count")
        case .open: format = String(localized: "work.downloadManagement.open")
        default: format = String(localized: "work.downloadManagement.more")
        }
        guard let count else { return format }
        return String(format: format, count)
    }
}
