@preconcurrency import ErmaoShared
import SwiftUI

struct DownloadCenterView: View {
    var cover: (String?, String) -> AnyView = { _, _ in AnyView(Image(systemName: "book.closed").foregroundStyle(.secondary)) }
    @ObservedObject var store: DownloadCenterStore
    let openAudio: (ManagedDownloadRecord) -> Void
    let openReader: (ReaderHandoff) -> Void
    @Environment(\.appTheme) private var theme
    @Environment(\.locale) private var locale
    @FocusState private var searchFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: .space1) {
                Image(systemName: "magnifyingglass").foregroundStyle(theme.textSecondary)
                TextField("downloads.search.prompt", text: $store.search)
                    .focused($searchFocused)
                    .submitLabel(.search)
                    .accessibilityIdentifier("downloads.search")
                if !store.search.isEmpty {
                    Button { store.search = "" } label: { Image(systemName: "xmark.circle.fill") }
                        .foregroundStyle(theme.textSecondary)
                        .accessibilityLabel(Text("downloads.search.clear"))
                }
            }
            .padding(.horizontal, .space1)
            .frame(minHeight: .iosMinimumTouchTarget)
            .background(Color(hex: GeneratedDesignTokens.App.navigation), in: RoundedRectangle(cornerRadius: CGFloat(GeneratedDesignTokens.Radii.control)))
            .padding(.horizontal, .space2)
            HStack {
                Text("downloads.storage.used")
                Text(ByteCountFormatter.string(fromByteCount: store.usedBytes, countStyle: .file))
                Spacer()
            }
            .appTextStyle(.callout).foregroundStyle(theme.textSecondary)
            .padding(.space2).accessibilityIdentifier("downloads.storage")
            List {
                if let code = store.storageErrorCode {
                    Text(downloadFailureMessage(code)).foregroundStyle(.red)
                    Button("common.retry") { store.reload() }
                }
                ForEach(store.bookGroups) { group in
                    NavigationLink {
                        DownloadedBookView(store: store, bookID: group.bookID, openAudio: openAudio, openReader: openReader)
                    } label: {
                        ContentListRow(title: group.title, cover: {
                            cover(group.resources.flatMap(\.records).compactMap(\.coverPath).first
                                ?? ErmaoShared.PublicKt.bookCoverRequestPath(bookId: group.bookID), group.title)
                        }, actions: { EmptyView() }, description: {
                            let author = AuthorDisplay.shared.label(author: group.author)
                            if !author.isEmpty { Text(author) }
                            Text(bookSummary(group))
                        })
                    }
                    .listRowBackground(theme.canvas)
                    .accessibilityIdentifier("downloads.book.\(group.bookID)")
                    .simultaneousGesture(TapGesture().onEnded { searchFocused = false })
                }
            }
            .listStyle(.plain).scrollContentBackground(.hidden)
            .overlay {
                if store.bookGroups.isEmpty, store.storageErrorCode == nil {
                    ContentStatusView(systemImage: "arrow.down.circle",
                        title: store.search.isEmpty ? "downloads.empty.title" : "downloads.search.empty.title",
                        message: store.search.isEmpty ? "downloads.empty.message" : "downloads.search.empty.message")
                        .padding(.space3)
                }
            }
        }
        .appCanvas().navigationTitle("downloads.title").navigationBarTitleDisplayMode(.inline)
        .accessibilityIdentifier("downloads.screen")
        .task { _ = await store.reloadAndAwait() }
    }

    private func bookSummary(_ book: ManagedDownloadBookGroup) -> String {
        let resources = book.resources.compactMap { $0.records.max { $0.updatedAt < $1.updatedAt } }
        let counts = Dictionary(grouping: resources) { record in
            store.managementResource(for: record).status
        }
        let summary = counts.sorted { $0.key.ordinal < $1.key.ordinal }.map { status, records in
            "\(records.count.formatted(.number.locale(locale))) \(downloadStatusText(status: status, progress: nil, locale: locale))"
        }.joined(separator: " · ")
        return "\(String(format: localizedAppString("downloads.resourceCount", locale: locale), locale: locale, book.resources.count)) · \(summary)"
    }
}

private struct DownloadedBookView: View {
    @ObservedObject var store: DownloadCenterStore
    let bookID: String
    let openAudio: (ManagedDownloadRecord) -> Void
    let openReader: (ReaderHandoff) -> Void
    @Environment(\.appTheme) private var theme
    @Environment(\.locale) private var locale
    @State private var pendingRemoval: ManagedDownloadRecord?
    @State private var operation: Task<Void, Never>?
    @State private var isActing = false
    @State private var failureCode: String?

    private var book: ManagedDownloadBookGroup? {
        ManagedDownloadGrouping.books(records: store.records.filter { $0.bookID == bookID }, query: "").first
    }

    var body: some View {
        List {
            if let code = failureCode ?? store.storageErrorCode {
                Text(downloadFailureMessage(code)).appTextStyle(.caption).foregroundStyle(.red)
                if store.storageErrorCode != nil { Button("common.retry") { store.reload() } }
            }
            if let book {
                Text([AuthorDisplay.shared.label(author: book.author),
                    String(format: localizedAppString("downloads.resourceCount", locale: locale), locale: locale, book.resources.count)]
                    .filter { !$0.isEmpty }.joined(separator: " · "))
                    .appTextStyle(.callout).foregroundStyle(theme.textSecondary)
                    .listRowBackground(theme.canvas)
                ForEach(book.resources) { resource in
                    ForEach(resource.records) { record in resourceRow(record) }
                }
            } else if store.storageErrorCode == nil {
                ContentStatusView(systemImage: "arrow.down.circle", title: "downloads.empty.title", message: "downloads.empty.message")
            }
        }
        .listStyle(.plain).scrollContentBackground(.hidden).appCanvas()
        .navigationTitle(book?.title ?? String(localized: "downloads.title"))
        .navigationBarTitleDisplayMode(.inline).accessibilityIdentifier("downloads.book.screen")
        .task { _ = await store.reloadAndAwait() }
        .onDisappear { operation?.cancel(); operation = nil; isActing = false }
        .confirmationDialog("downloads.remove.confirm.title", isPresented: Binding(
            get: { pendingRemoval != nil }, set: { if !$0 { pendingRemoval = nil } }
        ), titleVisibility: .visible, presenting: pendingRemoval) { record in
            Button("downloads.remove.action", role: .destructive) { pendingRemoval = nil; perform(.remove, record) }
            Button("common.cancel", role: .cancel) { pendingRemoval = nil }
        } message: { _ in Text("downloads.remove.confirm.message") }
    }

    private func resourceRow(_ record: ManagedDownloadRecord) -> some View {
        let resource = DownloadManagementAdapter.catalogResource(record, available: true)
        let projected = store.managementResource(for: record)
        return HStack(spacing: .spaceHalf) {
            Button { perform(.open, record) } label: {
                DownloadResourceContent(title: DownloadManagementPolicy.shared.displayTitle(bookTitle: record.bookTitle, resourceTitle: record.resourceTitle),
                    metadata: [record.format, resource.sizeLabel].compactMap { $0 }.joined(separator: " · "),
                    status: projected.status, progress: record.progress, errorCode: record.stableErrorCode,
                    statusIdentifier: "downloads.status.\(record.id)", accessibilityTitle: record.resourceTitle)
            }
            .buttonStyle(.plain).disabled(isActing || !projected.actions.contains(.open))
            .accessibilityIdentifier("downloads.open.\(record.resourceID)")
            if let action = projected.primaryAction, action != .open {
                Button { perform(action, record) } label: {
                    Image(systemName: downloadActionImage(action)).frame(width: .iosMinimumTouchTarget, height: .iosMinimumTouchTarget)
                }
                .buttonStyle(.borderless).disabled(isActing)
                .accessibilityLabel(Text(downloadActionLabel(action)))
            }
            if projected.actions.contains(.remove) {
                Button { pendingRemoval = record } label: {
                    Image(systemName: "trash").frame(width: .iosMinimumTouchTarget, height: .iosMinimumTouchTarget)
                }
                .buttonStyle(.borderless).disabled(isActing)
                .accessibilityLabel(Text("downloads.remove.action"))
            }
        }
        .foregroundStyle(theme.textSecondary)
        .listRowInsets(EdgeInsets(top: .space1, leading: .space2, bottom: .space1, trailing: .space2))
        .listRowBackground(theme.canvas)
    }

    private func perform(_ action: DownloadManagementAction, _ record: ManagedDownloadRecord) {
        guard !isActing else { return }
        isActing = true
        failureCode = nil
        operation = Task { @MainActor in
            defer { isActing = false; operation = nil }
            if action == .open {
                guard await store.reloadAndAwait(expectedNamespace: record.namespace),
                      let handoff = await store.verifiedReaderHandoff(resourceID: record.resourceID, assetID: record.assetID, expectedNamespace: record.namespace),
                      !Task.isCancelled else {
                    if !Task.isCancelled { failureCode = "DOWNLOAD_LOCAL_FILE_INVALID" }
                    return
                }
                if handoff.readerType == .audio, let latest = store.record(for: record.resourceID, assetID: handoff.assetID) {
                    openAudio(latest)
                } else { openReader(handoff) }
                return
            }
            let results: [DownloadManagementResult]
            if action == .remove {
                results = [await store.removeAndAwait(record)]
            } else {
                results = await store.executeManagement(action: action, selectedResourceIDs: [record.resourceID],
                    resources: [DownloadManagementAdapter.catalogResource(record, available: true)], expectedNamespace: record.namespace)
            }
            guard !Task.isCancelled else { return }
            failureCode = results.first(where: { $0.outcome == .failed })?.failureCode
        }
    }
}

/// Download row typography, metadata and progress shared with the detail download sheet.
struct DownloadResourceContent: View {
    let title: String
    let metadata: String
    let status: DownloadManagementStatus
    let progress: Double?
    let errorCode: String?
    let statusIdentifier: String
    var accessibilityTitle: String? = nil
    @Environment(\.appTheme) private var theme
    @Environment(\.locale) private var locale

    var body: some View {
        VStack(alignment: .leading, spacing: .spaceHalf) {
            Text("Ag").appTextStyle(.body).hidden()
                .frame(maxWidth: .infinity, alignment: .leading)
                .overlay(alignment: .leading) {
                    Text(title).appTextStyle(.body).foregroundStyle(theme.textPrimary).lineLimit(1)
                        .fixedSize(horizontal: true, vertical: false).accessibilityLabel(Text(accessibilityTitle ?? title))
                }.clipped()
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .firstTextBaseline, spacing: .spaceHalf) {
                    Text(metadata).fixedSize()
                    Text("·")
                    statusLabel.fixedSize()
                }
                VStack(alignment: .leading, spacing: .spaceHalf) { Text(metadata); statusLabel }
            }
            .appTextStyle(.caption).foregroundStyle(theme.textSecondary)
            if (status == .downloading || status == .paused), let progress {
                ProgressView(value: progress).tint(theme.actionAccent)
            }
            if [.failedretryable, .failedterminal, .invalidlocal].contains(status), let errorCode {
                Text(downloadFailureMessage(errorCode)).appTextStyle(.caption).foregroundStyle(.red)
            }
        }
        .frame(maxWidth: .infinity, minHeight: CGFloat.iosMinimumTouchTarget + .spaceHalf, alignment: .leading)
    }

    private var statusLabel: some View {
        HStack(alignment: .firstTextBaseline, spacing: .spaceHalf) {
            Text(downloadStatusText(status: status, progress: progress, locale: locale))
            if status == .completed { Image(systemName: "checkmark").foregroundStyle(theme.actionAccent) }
        }.accessibilityIdentifier(statusIdentifier)
    }
}

func downloadStatusText(status: DownloadManagementStatus, progress: Double?, locale: Locale) -> String {
    let key: String
    switch status {
    case .notdownloaded: key = "work.downloadManagement.status.notDownloaded"
    case .queued: key = "work.downloadManagement.status.queued"
    case .downloading: key = "work.downloadManagement.status.downloading"
    case .paused: key = "work.downloadManagement.status.paused"
    case .completed: key = "work.downloadManagement.status.completed"
    case .invalidlocal: key = "work.downloadManagement.status.invalidLocal"
    case .failedretryable: key = "work.downloadManagement.status.failedRetryable"
    case .failedterminal: key = "work.downloadManagement.status.failedTerminal"
    default: key = "work.downloadManagement.status.unavailable"
    }
    let label = localizedAppString(key, locale: locale)
    guard (status == .downloading || status == .paused), let progress else { return label }
    return "\(label) · \(progress.formatted(.percent.precision(.fractionLength(0)).locale(locale)))"
}

func downloadActionImage(_ action: DownloadManagementAction) -> String {
    switch action {
    case .download: "arrow.down.to.line"
    case .pause: "pause.circle"
    case .resume: "play.circle"
    case .retry: "arrow.clockwise"
    case .remove: "trash"
    case .open: "arrow.up.right.square"
    default: "ellipsis"
    }
}

func downloadActionLabel(_ action: DownloadManagementAction) -> LocalizedStringKey {
    switch action {
    case .pause: "work.downloadManagement.pause"
    case .resume: "work.downloadManagement.resume"
    case .retry: "work.downloadManagement.retry"
    case .remove: "work.downloadManagement.remove"
    case .download: "work.downloadManagement.download"
    default: "work.downloadManagement.open"
    }
}

func downloadFailureMessage(_ code: String?) -> LocalizedStringKey {
    switch code {
    case "DOWNLOAD_UNAUTHORIZED": "downloads.error.unauthorized"
    case "DOWNLOAD_CONTENT_UNAVAILABLE": "downloads.error.inaccessible"
    case "DOWNLOAD_INSUFFICIENT_SPACE": "downloads.error.space"
    case "ASSET_VERSION_CHANGED": "reader.error.PUBLICATION_CHANGED"
    case "DOWNLOAD_INVALID_RESPONSE", "DOWNLOAD_LOCAL_FILE_INVALID": "downloads.error.invalid"
    case "DOWNLOAD_TRANSPORT_UNAVAILABLE": "downloads.error.transportUnavailable"
    case "DOWNLOAD_MANIFEST_READ_FAILED", "DOWNLOAD_MANIFEST_WRITE_FAILED", "DOWNLOAD_REMOVE_FAILED": "downloads.error.storage"
    default: "downloads.error.generic"
    }
}

struct ReaderHandoffView: View {
    let handoff: ReaderHandoff

    var body: some View {
        VStack(spacing: .space2) {
            Image(systemName: readerImage)
                .font(.system(size: 44))
                .accessibilityHidden(true)
            Text("reader.handoff.unavailable.title").appTextStyle(.headline)
            VStack(spacing: .space1) {
                Text(handoff.title).appTextStyle(.headline)
                Text(handoff.resourceTitle)
                Text(message)
                    .multilineTextAlignment(.center)
            }
        }
        .padding(.space3)
        .frame(maxWidth: 520)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .navigationTitle("reader.handoff.navigationTitle")
        .navigationBarTitleDisplayMode(.inline)
        .appCanvas()
        .accessibilityIdentifier("reader.handoff.screen")
    }

    private var readerImage: String {
        switch handoff.readerType {
        case .reflowable: "book.pages"
        case .comic: "photo.on.rectangle.angled"
        case .pdf: "doc.richtext"
        case .audio: "headphones"
        }
    }

    private var message: LocalizedStringKey {
        switch handoff.source {
        case .verifiedLocal: "reader.handoff.localUnavailable.message"
        case .remoteStream: "reader.handoff.streamUnavailable.message"
        }
    }
}
