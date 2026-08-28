import SwiftUI

struct DownloadCenterView: View {
    @ObservedObject var store: DownloadCenterStore
    let openReader: (ReaderHandoff) -> Void

    @State private var pendingRemoval: ManagedDownloadRecord?

    @Environment(\.appTheme) private var theme

    var body: some View {
        List {
            storageSection
            if !store.completedSearch.isEmpty {
                completedSection
            } else {
                activeSection
                completedSection
                failedSection
            }
        }
        .listStyle(.plain)
        .settingsListSurface()
        .accessibilityIdentifier("downloads.screen")
        .navigationTitle("downloads.title")
        .searchable(text: $store.completedSearch, prompt: "downloads.search.prompt")
        .overlay { emptyOverlay }
        .task { store.reload() }
        .confirmationDialog(
            "downloads.remove.confirm.title",
            isPresented: Binding(
                get: { pendingRemoval != nil },
                set: { if !$0 { pendingRemoval = nil } }
            ),
            titleVisibility: .visible,
            presenting: pendingRemoval
        ) { record in
            Button("downloads.remove.action", role: .destructive) {
                store.remove(record)
                pendingRemoval = nil
            }
            Button("common.cancel", role: .cancel) { pendingRemoval = nil }
        } message: { _ in
            Text("downloads.remove.confirm.message")
        }
    }

    private var storageSection: some View {
        Section("downloads.storage.section") {
            HStack {
                Label("downloads.storage.used", systemImage: "internaldrive")
                Spacer()
                Text(ByteCountFormatter.string(fromByteCount: store.usedBytes, countStyle: .file))
                    .foregroundStyle(theme.textSecondary)
            }
            if let storageErrorCode = store.storageErrorCode {
                Label {
                    Text(downloadFailureMessage(storageErrorCode))
                } icon: {
                    Image(systemName: "exclamationmark.triangle")
                }
                .foregroundStyle(.red)
                .accessibilityIdentifier("downloads.storage.error")
            }
        }
        .listRowBackground(theme.surface)
    }

    @ViewBuilder
    private var activeSection: some View {
        if !store.activeRecords.isEmpty {
            Section("downloads.active.section") {
                ForEach(store.activeRecords) { record in
                    taskRow(record)
                }
            }
            .listRowBackground(theme.surface)
        }
    }

    @ViewBuilder
    private var completedSection: some View {
        if !store.completedGroups.isEmpty {
            Section("downloads.completed.section") {
                ForEach(store.completedGroups) { group in
                    VStack(alignment: .leading, spacing: .space1) {
                        Text(group.title).appTextStyle(.headline)
                        if let author = group.author, !author.isEmpty {
                            Text(author)
                                .appTextStyle(.caption)
                                .foregroundStyle(theme.textSecondary)
                        }
                        ForEach(group.resources) { resource in
                            Divider()
                            VStack(alignment: .leading, spacing: .spaceHalf) {
                                Label(resource.title, systemImage: "square.stack.3d.up")
                                    .appTextStyle(.label)
                                    .foregroundStyle(theme.textSecondary)
                                ForEach(resource.records) { record in
                                    Button { open(record) } label: {
                                        HStack(spacing: .space1) {
                                            VStack(alignment: .leading, spacing: .spaceHalf) {
                                                Text(record.resourceTitle)
                                                    .foregroundStyle(theme.textPrimary)
                                                Text(completedDetail(record))
                                                    .appTextStyle(.caption)
                                                    .foregroundStyle(theme.textSecondary)
                                            }
                                            Spacer()
                                            Image(systemName: "checkmark.circle.fill")
                                                .foregroundStyle(theme.brandAccent)
                                            Image(systemName: "chevron.forward")
                                                .foregroundStyle(theme.textTertiary)
                                        }
                                        .frame(minHeight: .iosMinimumTouchTarget)
                                        .contentShape(Rectangle())
                                    }
                                    .buttonStyle(.plain)
                                    .accessibilityIdentifier("downloads.open.\(record.resourceID)")
                                    .accessibilityHint(Text("downloads.open.hint"))
                                    .contextMenu {
                                        Button("downloads.remove.action", role: .destructive) {
                                            pendingRemoval = record
                                        }
                                    }
                                }
                            }
                        }
                    }
                    .padding(.vertical, .spaceHalf)
                }
            }
            .listRowBackground(theme.surface)
        }
    }

    @ViewBuilder
    private var failedSection: some View {
        if !store.failedRecords.isEmpty {
            Section("downloads.failed.section") {
                ForEach(store.failedRecords) { record in
                    VStack(alignment: .leading, spacing: .space1) {
                        Text(record.bookTitle).appTextStyle(.headline)
                        Text("\(record.resourceTitle) · \(record.format)")
                            .appTextStyle(.caption)
                            .foregroundStyle(theme.textSecondary)
                        Text(downloadFailureMessage(record.stableErrorCode))
                            .appTextStyle(.caption)
                            .foregroundStyle(.red)
                        HStack {
                            Button("common.retry") { store.retry(record) }
                            Spacer()
                            Button("downloads.remove.action", role: .destructive) {
                                pendingRemoval = record
                            }
                        }
                    }
                    .padding(.vertical, .spaceHalf)
                }
            }
            .listRowBackground(theme.surface)
        }
    }

    private func taskRow(_ record: ManagedDownloadRecord) -> some View {
        VStack(alignment: .leading, spacing: .space1) {
            Text(record.bookTitle).appTextStyle(.headline)
            Text("\(record.resourceTitle) · \(record.format)")
                .appTextStyle(.caption)
                .foregroundStyle(theme.textSecondary)
            if let progress = record.progress {
                ProgressView(value: progress)
                    .tint(theme.brandAccent)
                    .accessibilityValue(Text(progress, format: .percent.precision(.fractionLength(0))))
            } else {
                ProgressView()
                    .accessibilityLabel(Text("downloads.progress.indeterminate"))
            }
            HStack {
                Text(progressDetail(record))
                    .appTextStyle(.caption)
                    .foregroundStyle(theme.textSecondary)
                Spacer()
                if record.state == .paused {
                    Button("downloads.resume.action") { store.resume(record) }
                } else {
                    Button("downloads.pause.action") { store.pause(record) }
                }
            }
        }
        .padding(.vertical, .spaceHalf)
    }

    @ViewBuilder
    private var emptyOverlay: some View {
        let hasVisibleContent = !store.activeRecords.isEmpty || !store.failedRecords.isEmpty || !store.completedGroups.isEmpty
        if !hasVisibleContent {
            ContentStatusView(
                systemImage: "arrow.down.circle",
                title: store.completedSearch.isEmpty ? "downloads.empty.title" : "downloads.search.empty.title",
                message: store.completedSearch.isEmpty ? "downloads.empty.message" : "downloads.search.empty.message"
            )
            .padding(.space3)
        }
    }

    private func open(_ record: ManagedDownloadRecord) {
        openReader(
            ReaderHandoff(
                bookID: record.bookID,
                resourceID: record.resourceID,
                assetID: record.assetID,
                title: record.bookTitle,
                resourceTitle: record.resourceTitle,
                format: record.format,
                readerType: record.readerType,
                source: .verifiedLocal(recordID: record.id)
            )
        )
    }

    private func completedDetail(_ record: ManagedDownloadRecord) -> String {
        let size = ByteCountFormatter.string(fromByteCount: record.receivedBytes, countStyle: .file)
        return String(
            format: String(localized: "downloads.completed.detail.format"),
            locale: .current,
            record.format,
            size
        )
    }

    private func progressDetail(_ record: ManagedDownloadRecord) -> String {
        let received = ByteCountFormatter.string(fromByteCount: record.receivedBytes, countStyle: .file)
        guard let total = record.expectedBytes else { return received }
        let expected = ByteCountFormatter.string(fromByteCount: total, countStyle: .file)
        return "\(received) / \(expected)"
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
    case "DOWNLOAD_MANIFEST_READ_FAILED", "DOWNLOAD_MANIFEST_WRITE_FAILED": "downloads.error.storage"
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
