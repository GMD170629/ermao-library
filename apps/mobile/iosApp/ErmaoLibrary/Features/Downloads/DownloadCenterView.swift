import SwiftUI

struct ReaderDownloadTransitionView: View {
    private enum Phase {
        case creating
        case downloading(recordID: String)
        case reader(IosReaderLaunchRequest)
        case unsupported(ReaderHandoff)
        case failure(String)
    }

    let request: ReaderPreparationRequest
    @ObservedObject var store: DownloadCenterStore
    let client: any ContentClient
    let cache: AuthenticatedCoverCache
    let readerComposition: IosReaderComposition?

    @Environment(\.dismiss) private var dismiss
    @Environment(\.appTheme) private var theme
    @State private var phase = Phase.creating
    @State private var accessTask: Task<Void, Never>?
    @State private var cancelled = false
    @State private var didEnterReader = false

    var body: some View {
        Group {
            switch phase {
            case .reader(let launch):
                if let readerComposition {
                    IosReaderBootstrapView(request: launch, composition: readerComposition)
                } else {
                    failureContent("READER_TYPE_UNAVAILABLE")
                }
            case .unsupported(let handoff):
                unsupportedContent(handoff)
            case .creating, .downloading, .failure:
                preparationContent
            }
        }
        .appCanvas()
        .task { beginPreparation() }
        .onChange(of: store.records) { _ in evaluateDownloadState() }
        .onDisappear { accessTask?.cancel() }
    }

    private var preparationContent: some View {
        VStack(spacing: .space3) {
            Spacer(minLength: .space3)
            BookCoverView(
                reference: request.book.cover,
                title: request.book.title,
                context: request.context,
                client: client,
                cache: cache,
                cornerRadius: CGFloat(GeneratedDesignTokens.Radii.coverHero)
            )
            .frame(width: 190, height: 285)

            VStack(spacing: .spaceHalf) {
                Text(request.book.title)
                    .appTextStyle(.title)
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
                Text(request.book.author ?? "—")
                    .appTextStyle(.body)
                    .foregroundStyle(theme.textSecondary)
                    .lineLimit(1)
            }

            statusContent
                .frame(maxWidth: 440)

            Spacer(minLength: .space2)
            Button("reader.download.cancel", role: .cancel) { cancelAndReturn() }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .frame(minHeight: .iosMinimumTouchTarget)
        }
        .padding(.horizontal, .space3)
        .padding(.vertical, .space2)
    }

    @ViewBuilder
    private var statusContent: some View {
        switch phase {
        case .creating:
            VStack(spacing: .space1) {
                ProgressView()
                Text("reader.download.creatingTask")
                    .appTextStyle(.body)
            }
            .accessibilityElement(children: .combine)
        case .downloading(let recordID):
            if let record = store.records.first(where: { $0.id == recordID }) {
                VStack(spacing: .space1) {
                    if let progress = record.progress {
                        ProgressView(value: progress)
                            .tint(theme.brandAccent)
                            .accessibilityValue(Text(progress, format: .percent.precision(.fractionLength(0))))
                    } else {
                        ProgressView()
                            .accessibilityLabel(Text("downloads.progress.indeterminate"))
                    }
                    Text(downloadProgressText(record))
                        .appTextStyle(.label)
                        .monospacedDigit()
                    Text("reader.download.once.message")
                        .appTextStyle(.caption)
                        .foregroundStyle(theme.textSecondary)
                        .multilineTextAlignment(.center)
                }
            } else {
                ProgressView("reader.download.creatingTask")
            }
        case .failure(let code):
            VStack(spacing: .space1) {
                Label("reader.download.failed.title", systemImage: "exclamationmark.triangle")
                    .appTextStyle(.headline)
                    .foregroundStyle(.red)
                Text(downloadErrorMessage(code))
                    .appTextStyle(.body)
                    .multilineTextAlignment(.center)
                Button("common.retry") { retry() }
                    .buttonStyle(.borderedProminent)
            }
        case .reader, .unsupported:
            EmptyView()
        }
    }

    private func unsupportedContent(_ handoff: ReaderHandoff) -> some View {
        VStack(spacing: .space2) {
            Image(systemName: handoff.readerType == .comic ? "rectangle.stack" : "doc.richtext")
                .font(.system(size: 44))
            Text("reader.handoff.unavailable.title").appTextStyle(.headline)
            Text("reader.handoff.streamUnavailable.message")
                .multilineTextAlignment(.center)
                .foregroundStyle(theme.textSecondary)
            Button("common.close") { dismiss() }
                .buttonStyle(.borderedProminent)
        }
        .padding(.space3)
    }

    private func failureContent(_ code: String) -> some View {
        VStack(spacing: .space2) {
            Text("reader.download.failed.title").appTextStyle(.headline)
            Text(downloadErrorMessage(code)).multilineTextAlignment(.center)
            Button("common.close") { dismiss() }
        }
        .padding(.space3)
    }

    private func beginPreparation() {
        guard accessTask == nil, !cancelled else { return }
        phase = .creating
        accessTask = store.requestReaderAccess(
            book: request.book,
            resource: request.resource
        ) { outcome in
            accessTask = nil
            guard !cancelled else {
                if case .needsDownload(let recordID) = outcome,
                   let record = store.records.first(where: { $0.id == recordID }) {
                    store.pause(record)
                }
                return
            }
            switch outcome {
            case .open(let handoff): enterReader(handoff)
            case .needsDownload(let recordID):
                phase = .downloading(recordID: recordID)
                evaluateDownloadState()
            case .unavailable(let code):
                phase = .failure(code)
            }
        }
    }

    private func evaluateDownloadState() {
        guard case .downloading(let recordID) = phase,
              let record = store.records.first(where: { $0.id == recordID }) else { return }
        if ManagedReaderAccessPolicy.completedRecord(
            records: store.records,
            recordID: recordID
        ) != nil {
            enterReader(ReaderHandoff(
                bookID: record.bookID,
                resourceID: record.resourceID,
                assetID: record.assetID,
                title: record.bookTitle,
                resourceTitle: record.resourceTitle,
                format: record.format,
                readerType: record.readerType,
                source: .verifiedLocal(recordID: record.id)
            ))
        } else if record.state == .failedRetryable || record.state == .failedTerminal {
            phase = .failure(record.stableErrorCode ?? "DOWNLOAD_INVALID_RESPONSE")
        }
    }

    private func enterReader(_ handoff: ReaderHandoff) {
        guard !didEnterReader else { return }
        didEnterReader = true
        if ManagedReaderAccessPolicy.supportsNativeReader(
               readerType: handoff.readerType,
               format: handoff.format
           ) {
            guard readerComposition != nil else {
                phase = .failure("READER_TYPE_UNAVAILABLE")
                return
            }
            let recordID: String? = if case .verifiedLocal(let value) = handoff.source { value } else { nil }
            phase = .reader(IosReaderLaunchRequest(
                context: request.context,
                bookID: handoff.bookID,
                resourceID: handoff.resourceID,
                displayTitle: handoff.title,
                managedDownloadRecordID: recordID
            ))
        } else {
            phase = .unsupported(handoff)
        }
    }

    private func retry() {
        didEnterReader = false
        accessTask = nil
        beginPreparation()
    }

    private func cancelAndReturn() {
        cancelled = true
        accessTask?.cancel()
        if case .downloading(let recordID) = phase,
           let record = store.records.first(where: { $0.id == recordID }) {
            store.pause(record)
        }
        dismiss()
    }

    private func downloadProgressText(_ record: ManagedDownloadRecord) -> String {
        let received = ByteCountFormatter.string(fromByteCount: record.receivedBytes, countStyle: .file)
        guard let total = record.expectedBytes, total > 0 else { return received }
        let expected = ByteCountFormatter.string(fromByteCount: total, countStyle: .file)
        let percent = Int((record.progress ?? 0) * 100)
        return String(
            format: String(localized: "reader.download.progress.format"),
            locale: .current,
            received,
            expected,
            percent
        )
    }

    private func downloadErrorMessage(_ code: String) -> LocalizedStringKey {
        switch code {
        case "DOWNLOAD_UNAUTHORIZED": "downloads.error.unauthorized"
        case "DOWNLOAD_CONTENT_UNAVAILABLE": "downloads.error.inaccessible"
        case "DOWNLOAD_INSUFFICIENT_SPACE": "downloads.error.space"
        case "DOWNLOAD_TRANSPORT_UNAVAILABLE": "downloads.error.transportUnavailable"
        case "READER_TYPE_UNAVAILABLE": "reader.handoff.localUnavailable.message"
        default: "downloads.error.invalid"
        }
    }
}

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
                    Text(errorMessage(storageErrorCode))
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
                        Text(errorMessage(record.stableErrorCode))
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

    private func errorMessage(_ code: String?) -> LocalizedStringKey {
        switch code {
        case "DOWNLOAD_UNAUTHORIZED": "downloads.error.unauthorized"
        case "DOWNLOAD_CONTENT_UNAVAILABLE": "downloads.error.inaccessible"
        case "DOWNLOAD_INSUFFICIENT_SPACE": "downloads.error.space"
        case "DOWNLOAD_INVALID_RESPONSE", "DOWNLOAD_LOCAL_FILE_INVALID": "downloads.error.invalid"
        case "DOWNLOAD_TRANSPORT_UNAVAILABLE": "downloads.error.transportUnavailable"
        case "DOWNLOAD_MANIFEST_READ_FAILED", "DOWNLOAD_MANIFEST_WRITE_FAILED": "downloads.error.storage"
        default: "downloads.error.generic"
        }
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
