import Combine
import SwiftUI
@preconcurrency import ErmaoShared

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

    init(
        context: ContentRequestContext,
        client: any ContentClient,
        bookID: String,
        initialResources: [BookResource]
    ) {
        self.context = context
        self.client = client
        self.bookID = bookID
        resourcesByID = Dictionary(uniqueKeysWithValues: initialResources.map { ($0.id, $0) })
    }

    var visibleRows: [Row] {
        guard let rootNodeID else { return [] }
        return flattenedChildren(of: rootNodeID, depth: 0)
    }

    func load() {
        guard isLoading else { return }
        Task {
            do {
                async let root = loadFolder(sourceNodeID: nil)
                async let resources = loadAllResources()
                let (page, loadedResources) = try await (root, resources)
                apply(page)
                resourcesByID.merge(loadedResources, uniquingKeysWith: { _, latest in latest })
                rootNodeID = page.currentNode.sourceNodeID
                expandedNodeIDs.insert(page.currentNode.sourceNodeID)
                isLoading = false
                errorCode = nil
            } catch {
                isLoading = false
                errorCode = "MULTI_DOWNLOAD_TREE_LOAD_FAILED"
            }
        }
    }

    func retry() {
        isLoading = true
        errorCode = nil
        load()
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
        loadingNodeIDs.insert(nodeID)
        failedNodeIDs.remove(nodeID)
        Task {
            do {
                let page = try await loadFolder(sourceNodeID: nodeID)
                apply(page)
                loadingNodeIDs.remove(nodeID)
                completion?()
            } catch {
                loadingNodeIDs.remove(nodeID)
                failedNodeIDs.insert(nodeID)
            }
        }
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
        var result = resourcesByID
        var pageNumber = 1
        while true {
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
    let detail: BookDetailContent
    @ObservedObject var downloads: DownloadCenterStore
    let onDismiss: () -> Void
    let onCompleted: (Int, Int) -> Void

    @StateObject private var tree: MultiDownloadTreeStore
    @State private var selectedResourceIDs: Set<String> = []
    @State private var isSubmitting = false
    @State private var pendingRemoval: ManagedDownloadRecord?
    @Environment(\.appTheme) private var theme

    init(
        context: ContentRequestContext,
        client: any ContentClient,
        detail: BookDetailContent,
        downloads: DownloadCenterStore,
        onDismiss: @escaping () -> Void,
        onCompleted: @escaping (Int, Int) -> Void
    ) {
        self.detail = detail
        self.downloads = downloads
        self.onDismiss = onDismiss
        self.onCompleted = onCompleted
        _tree = StateObject(
            wrappedValue: MultiDownloadTreeStore(
                context: context,
                client: client,
                bookID: detail.book.id,
                initialResources: detail.resources
            )
        )
    }

    var body: some View {
        NavigationStack {
            Group {
                if tree.isLoading {
                    ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if tree.errorCode != nil {
                    ContentStatusView(
                        systemImage: "wifi.exclamationmark",
                        title: "work.multiDownload.error.title",
                        message: "work.multiDownload.error.message",
                        actionTitle: "common.retry",
                        action: tree.retry
                    )
                } else {
                    List(tree.visibleRows) { row in
                        nodeRow(row)
                    }
                    .listStyle(.plain)
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    VStack(spacing: 1) {
                        Text("work.multiDownload.title").font(.headline)
                        Text(detail.book.title)
                            .font(.caption)
                            .foregroundStyle(theme.textSecondary)
                            .lineLimit(1)
                    }
                }
                ToolbarItem(placement: .cancellationAction) {
                    Button("common.cancel", action: onDismiss)
                        .disabled(isSubmitting)
                }
            }
            .safeAreaInset(edge: .bottom, spacing: 0) {
                confirmationBar
            }
        }
        .task { tree.load() }
        .alert(
            "downloads.remove.confirm.title",
            isPresented: Binding(
                get: { pendingRemoval != nil },
                set: { if !$0 { pendingRemoval = nil } }
            ),
            presenting: pendingRemoval
        ) { record in
            Button("downloads.remove.action", role: .destructive) {
                downloads.remove(record)
                pendingRemoval = nil
            }
            Button("common.cancel", role: .cancel) { pendingRemoval = nil }
        } message: { record in
            Text("downloads.remove.confirm.message")
        }
    }

    @ViewBuilder
    private func nodeRow(_ row: MultiDownloadTreeStore.Row) -> some View {
        let entry = row.entry
        if entry.isSourceFolder {
            folderRow(entry, depth: row.depth)
        } else if let resourceID = entry.resourceID,
                  let resource = tree.resourcesByID[resourceID] {
            resourceRow(resource, depth: row.depth)
        } else {
            HStack {
                Text(entry.title).foregroundStyle(theme.textSecondary)
                Spacer()
                Text("work.multiDownload.unavailable").appTextStyle(.caption)
                    .foregroundStyle(theme.textTertiary)
            }
            .padding(.leading, CGFloat(row.depth) * 20)
        }
    }

    private func folderRow(_ entry: BookContentEntry, depth: Int) -> some View {
        let descendantIDs = tree.descendantResourceIDsByNodeID[entry.sourceNodeID] ?? []
        let mark = directoryMark(descendantIDs)
        return HStack(spacing: .space1) {
            Button { tree.toggleExpanded(entry) } label: {
                Image(systemName: tree.expandedNodeIDs.contains(entry.sourceNodeID) ? "chevron.down" : "chevron.right")
                    .frame(width: 24, height: 44)
            }
            .buttonStyle(.plain)
            Button {
                tree.ensureLoaded(entry) { toggleDirectory(entry.sourceNodeID) }
            } label: {
                if tree.loadingNodeIDs.contains(entry.sourceNodeID) {
                    ProgressView().controlSize(.small).frame(width: 28, height: 44)
                } else {
                    Image(systemName: selectionImage(mark))
                        .foregroundStyle(mark == .unselected ? theme.textSecondary : theme.actionAccent)
                        .frame(width: 28, height: 44)
                }
            }
            .buttonStyle(.plain)
            VStack(alignment: .leading, spacing: .spaceHalf) {
                Text(entry.title).appTextStyle(.body)
                Text(String(format: String(localized: "work.multiDownload.volumeCount"), descendantIDs.count))
                    .appTextStyle(.caption)
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer()
        }
        .padding(.leading, CGFloat(depth) * 20)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityValue(Text(directoryAccessibilityValue(mark, count: descendantIDs.count)))
    }

    private func resourceRow(_ resource: BookResource, depth: Int) -> some View {
        let state = resourceState(resource.id)
        let selected = selectedResourceIDs.contains(resource.id)
        return HStack(spacing: .space1) {
            Button { toggleResource(resource.id) } label: {
                Image(systemName: selected ? "checkmark.square.fill" : "square")
                    .foregroundStyle(selected ? theme.actionAccent : theme.textSecondary)
                    .frame(width: 28, height: 44)
            }
            .buttonStyle(.plain)
            .disabled(!state.isSelectable || isSubmitting)
            VStack(alignment: .leading, spacing: .spaceHalf) {
                Text(resource.title).appTextStyle(.body).lineLimit(2)
                Text([resource.format, resource.sizeLabel].compactMap { $0 }.joined(separator: " · "))
                    .appTextStyle(.caption)
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer(minLength: .space1)
            Menu {
                statusMenu(record: downloads.record(for: resource.id), resource: resource)
            } label: {
                Text(statusText(resource.id))
                    .appTextStyle(.caption)
                    .foregroundStyle(state == .failedTerminal ? theme.textTertiary : theme.textSecondary)
                    .frame(minHeight: .iosMinimumTouchTarget)
            }
            .disabled(downloads.record(for: resource.id) == nil)
        }
        .padding(.leading, CGFloat(depth) * 20 + 24)
        .contentShape(Rectangle())
        .contextMenu { statusMenu(record: downloads.record(for: resource.id), resource: resource) }
        .accessibilityElement(children: .combine)
        .accessibilityValue(Text(statusText(resource.id)))
    }

    @ViewBuilder
    private func statusMenu(record: ManagedDownloadRecord?, resource: BookResource) -> some View {
        if let record {
            switch record.state {
            case .queued, .downloading:
                Button("downloads.pause.action") { downloads.pause(record) }
                Button("work.multiDownload.cancelTask", role: .destructive) { pendingRemoval = record }
            case .paused:
                Button("downloads.resume.action") { downloads.resume(record) }
                Button("work.multiDownload.cancelTask", role: .destructive) { pendingRemoval = record }
            case .failedRetryable:
                Button("common.retry") { downloads.retry(record) }
                Button("work.multiDownload.deleteTask", role: .destructive) { pendingRemoval = record }
            case .failedTerminal:
                Button("work.multiDownload.deleteTask", role: .destructive) { pendingRemoval = record }
            case .completed:
                Button("downloads.remove.action", role: .destructive) { pendingRemoval = record }
            }
        } else {
            Button("work.action.download") { toggleResource(resource.id) }
        }
    }

    private var confirmationBar: some View {
        let summary = batchSummary
        return VStack(alignment: .leading, spacing: .space1) {
            HStack {
                Text(String(format: String(localized: "work.multiDownload.selectedCount"), summary.selected))
                    .appTextStyle(.headline)
                Spacer()
                Text(String(format: String(localized: "work.multiDownload.summary"), summary.enqueue, summary.resume, summary.retry))
                    .appTextStyle(.caption)
                    .foregroundStyle(theme.textSecondary)
            }
            PrimaryActionButton(
                "work.multiDownload.confirm",
                systemImage: "arrow.down",
                isDisabled: summary.selected == 0 || isSubmitting
            ) {
                submit()
            }
            .frame(height: 52)
        }
        .padding(.horizontal, .space2)
        .padding(.vertical, .space1)
        .background(theme.surface)
        .overlay(alignment: .top) { Divider().overlay(theme.divider) }
    }

    private var batchSummary: (selected: Int, enqueue: Int, resume: Int, retry: Int) {
        var enqueue = 0
        var resume = 0
        var retry = 0
        selectedResourceIDs.forEach { id in
            switch resourceState(id) {
            case .enqueue: enqueue += 1
            case .resume: resume += 1
            case .retry: retry += 1
            default: break
            }
        }
        return (selectedResourceIDs.count, enqueue, resume, retry)
    }

    private enum ResourceState { case enqueue, resume, retry, active, completed, failedTerminal, unavailable
        var isSelectable: Bool { self == .enqueue || self == .resume || self == .retry }
    }

    private func resourceState(_ resourceID: String) -> ResourceState {
        guard tree.resourcesByID[resourceID] != nil else { return .unavailable }
        guard let record = downloads.record(for: resourceID) else { return .enqueue }
        switch record.state {
        case .queued, .downloading: return .active
        case .paused: return .resume
        case .failedRetryable: return .retry
        case .failedTerminal: return .failedTerminal
        case .completed: return record.isVerifiedOfflineCopy ? .completed : .retry
        }
    }

    private func toggleResource(_ resourceID: String) {
        guard resourceState(resourceID).isSelectable else { return }
        if !selectedResourceIDs.insert(resourceID).inserted { selectedResourceIDs.remove(resourceID) }
    }

    private func toggleDirectory(_ nodeID: String) {
        let descendants = tree.descendantResourceIDsByNodeID[nodeID] ?? []
        let selectable = descendants.filter { resourceState($0).isSelectable }
        guard !selectable.isEmpty else { return }
        if selectable.allSatisfy(selectedResourceIDs.contains) {
            selectedResourceIDs.subtract(selectable)
        } else {
            selectedResourceIDs.formUnion(selectable)
        }
    }

    private func directoryMark(_ descendants: Set<String>) -> MultiDownloadSelectionMark {
        let selectable = descendants.filter { resourceState($0).isSelectable }
        guard !selectable.isEmpty, selectable.contains(where: selectedResourceIDs.contains) else { return .unselected }
        return selectable.allSatisfy(selectedResourceIDs.contains) ? .selected : .mixed
    }

    private func selectionImage(_ mark: MultiDownloadSelectionMark) -> String {
        switch mark {
        case .unselected: "square"
        case .selected: "checkmark.square.fill"
        case .mixed: "minus.square.fill"
        default: "square"
        }
    }

    private func statusText(_ resourceID: String) -> String {
        guard let record = downloads.record(for: resourceID) else { return String(localized: "work.multiDownload.notDownloaded") }
        switch record.state {
        case .queued: return String(localized: "work.multiDownload.queued")
        case .downloading:
            return record.progress.map { "\(Int($0 * 100))%" } ?? String(localized: "work.multiDownload.downloading")
        case .paused: return String(localized: "work.multiDownload.paused")
        case .completed: return String(localized: "work.multiDownload.downloaded")
        case .failedRetryable, .failedTerminal: return String(localized: "work.multiDownload.failed")
        }
    }

    private func directoryAccessibilityValue(_ mark: MultiDownloadSelectionMark, count: Int) -> String {
        let state: String
        switch mark {
        case .unselected: state = String(localized: "work.multiDownload.selection.none")
        case .selected: state = String(localized: "work.multiDownload.selection.all")
        case .mixed: state = String(localized: "work.multiDownload.selection.mixed")
        default: state = String(localized: "work.multiDownload.selection.none")
        }
        return "\(state), \(String(format: String(localized: "work.multiDownload.volumeCount"), count))"
    }

    private func submit() {
        let resources = selectedResourceIDs.compactMap { tree.resourcesByID[$0] }
        guard !resources.isEmpty else { return }
        isSubmitting = true
        downloads.performBatch(book: detail.book, resources: resources) { result in
            isSubmitting = false
            selectedResourceIDs = result.failedResourceIDs
            onCompleted(result.succeededCount, result.failedCount)
            if result.failedCount == 0 { onDismiss() }
        }
    }
}
