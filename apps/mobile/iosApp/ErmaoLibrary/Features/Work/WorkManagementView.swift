import SwiftUI
@preconcurrency import ErmaoShared

enum WorkManagementTask: String, Identifiable {
    case addSeries, editWork, recognize, cover, editVolume, mediaKind, split, transfer, kindle
    case deleteWork, deleteVolume

    var id: String { rawValue }
}

struct WorkManagementView: View {
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var store: WorkManagementStore
    let task: WorkManagementTask
    let detail: WorkDetailContent
    let volume: WorkVolume?
    let downloadAction: (WorkVolume) -> Void
    let removeDownload: (WorkVolume) -> Void
    let chooseCover: () -> Void
    let workCover: AnyView
    let downloadForVolume: (String) -> ManagedDownloadRecord?
    let onManagedVolumeChange: (String?) -> Void

    @State private var page: Page = .editWork
    @State private var title = ""
    @State private var author = ""
    @State private var description = ""
    @State private var series = ""
    @State private var seriesIndex = ""
    @State private var tags = ""
    @State private var volumeIndex = ""
    @State private var sortOrder = "0"
    @State private var publisher = ""
    @State private var language = ""
    @State private var isbn = ""
    @State private var identifier = ""
    @State private var narrator = ""
    @State private var query = ""
    @State private var providerID = ""
    @State private var selectedCandidate: ErmaoShared.MetadataCandidate?
    @State private var selectedMetadataFields: Set<ErmaoShared.MetadataField> = []
    @State private var appliesMetadataToAllVolumes = true
    @State private var managedVolumeID: String?
    @State private var selectedKind: ErmaoShared.ManagedMediaKind = .ebook
    @State private var selectedReadingStatus: ErmaoShared.ManagedReadingStatus = .unread
    @State private var selectedTransferTargetID: String?
    @State private var selectedKindleFileID: String?
    @State private var confirmsDeletion = false
    @State private var confirmsDownloadRemoval = false
    @State private var confirmsCoverRegeneration = false

    private enum Page { case addSeries, editWork, editVolume, metadata, cover, readingStatus, mediaKind, split, transfer, kindle }

    private var activeVolume: WorkVolume? {
        managedVolumeID.flatMap { id in detail.volumes.first { $0.id == id } }
    }

    private var activeDownload: ManagedDownloadRecord? {
        activeVolume.flatMap { downloadForVolume($0.id) }
    }

    private var initialPage: Page {
        switch task {
        case .addSeries: .addSeries
        case .editWork: .editWork
        case .recognize: .metadata
        case .cover: .cover
        case .editVolume: .editVolume
        case .mediaKind: .mediaKind
        case .split: .split
        case .transfer: .transfer
        case .kindle: .kindle
        case .deleteWork, .deleteVolume: volume == nil ? .editWork : .editVolume
        }
    }

    private var taskTitle: LocalizedStringKey {
        switch task {
        case .addSeries: "work.control.addSeries"
        case .editWork: "management.editWork"
        case .recognize: "management.metadata"
        case .cover: "management.cover"
        case .editVolume: "management.editVolume"
        case .mediaKind: "management.mediaKind"
        case .split: "management.split"
        case .transfer: "management.transfer"
        case .kindle: "management.kindle"
        case .deleteWork: "management.deleteWork"
        case .deleteVolume: "management.deleteVolume"
        }
    }

    var body: some View {
        Form {
            if !store.capabilityChecked || store.isBusy { ProgressView() }
            if let code = store.errorCode { Text(String(format: String(localized: "management.failed.format"), code)) }
            if store.capabilityChecked && !store.supported { Text("management.unavailable") }
            switch page {
            case .addSeries: editSeries
            case .editWork: editWork
            case .editVolume: editVolume
            case .metadata: metadata
            case .cover: coverManagement
            case .readingStatus: readingStatus
            case .mediaKind: mediaKind
            case .split: split
            case .transfer: transfer
            case .kindle: kindle
            }
        }
        .navigationTitle(taskTitle)
        .navigationBarTitleDisplayMode(.inline)
        .navigationBarBackButtonHidden(true)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("common.close") { dismiss() }
                    .disabled(store.isBusy)
            }
        }
        .onAppear {
            managedVolumeID = volume?.id
            page = initialPage
            prepareFields()
            if task == .deleteWork || task == .deleteVolume { confirmsDeletion = true }
        }
        .onChange(of: store.metadataProviders.map(\.id)) { ids in
            if providerID.isEmpty { providerID = ids.first ?? "" }
        }
        .onChange(of: store.completedAction) { action in
            guard let action else { return }
            switch action {
            case .volumeReclassified, .volumeSplit, .volumeTransferred, .volumeDeleted:
                managedVolumeID = nil
                onManagedVolumeChange(nil)
            default: break
            }
        }
        .confirmationDialog(
            LocalizedStringKey(activeVolume == nil ? "management.deleteWork" : "management.deleteVolume"),
            isPresented: $confirmsDeletion,
            titleVisibility: .visible
        ) {
            Button(LocalizedStringKey(activeVolume == nil ? "management.deleteWork" : "management.deleteVolume"), role: .destructive) {
                if let activeVolume { store.deleteVolume(activeVolume) } else { store.deleteWork() }
            }
            Button("common.cancel", role: .cancel) {}
        } message: {
            Text(LocalizedStringKey(activeVolume == nil ? "management.confirmDeleteWork" : "management.confirmDeleteVolume"))
        }
        .confirmationDialog(
            "downloads.remove.confirm.title",
            isPresented: $confirmsDownloadRemoval,
            titleVisibility: .visible
        ) {
            Button("downloads.remove.action", role: .destructive) {
                if let activeVolume { removeDownload(activeVolume) }
            }
            Button("common.cancel", role: .cancel) {}
        } message: {
            Text("downloads.remove.confirm.message")
        }
        .confirmationDialog(
            "management.regenerateCoverConfirmTitle",
            isPresented: $confirmsCoverRegeneration,
            titleVisibility: .visible
        ) {
            Button("management.regenerateCover") { store.regenerateCover() }
            Button("common.cancel", role: .cancel) {}
        } message: {
            Text("management.regenerateCoverConfirmMessage")
        }
    }

    @ViewBuilder private var editSeries: some View {
        Section {
            TextField("management.series", text: $series)
            TextField("management.seriesIndex", text: $seriesIndex)
                .keyboardType(.decimalPad)
        }
        Section {
            Button("management.save") {
                store.updateWork(
                    title: detail.work.title,
                    author: detail.work.author,
                    description: detail.description ?? "",
                    seriesName: series,
                    seriesIndex: Double(seriesIndex),
                    tags: detail.tags
                )
            }
            .disabled(series.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ||
                      (!seriesIndex.isEmpty && Double(seriesIndex) == nil))
        }
    }

    private var editWork: some View {
        Section {
            TextField("management.title", text: $title)
            TextField("management.author", text: $author)
            TextField("management.description", text: $description, axis: .vertical)
            TextField("management.series", text: $series)
            TextField("management.seriesIndex", text: $seriesIndex)
            TextField("management.tags", text: $tags)
            Button("management.save") {
                store.updateWork(
                    title: title,
                    author: author,
                    description: description,
                    seriesName: series.nilIfBlank,
                    seriesIndex: Double(seriesIndex),
                    tags: tags.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
                )
            }
            .disabled(title.trimmingCharacters(in: .whitespaces).isEmpty)
        }
    }

    private var coverManagement: some View {
        Section {
            workCover
                .frame(maxWidth: .infinity)
                .frame(height: 240)
            Button("management.uploadCover", systemImage: "photo.badge.plus", action: chooseCover)
            Button("management.regenerateCover", systemImage: "wand.and.stars") {
                confirmsCoverRegeneration = true
            }
        } footer: {
            Text("management.coverUploadHint")
        }
    }

    @ViewBuilder private var readingStatus: some View {
        if let volume = detail.volumes.first(where: \.isSelected) ?? detail.volumes.first {
            Section(volume.title) {
                Picker("management.readingStatus", selection: $selectedReadingStatus) {
                    Text("work.status.unread").tag(ErmaoShared.ManagedReadingStatus.unread)
                    Text("work.status.finished").tag(ErmaoShared.ManagedReadingStatus.finished)
                }
                .pickerStyle(.segmented)
                Button("management.save") {
                    store.setReadingStatus(volumeID: volume.id, status: selectedReadingStatus)
                }
            }
        } else {
            Section { Text("management.noVolume") }
        }
    }

    @ViewBuilder private var editVolume: some View {
        if let volume = activeVolume {
            Section {
                TextField("management.title", text: $title)
                TextField("management.volumeIndex", text: $volumeIndex)
                    .keyboardType(.decimalPad)
                TextField("management.sortOrder", text: $sortOrder)
                    .keyboardType(.numberPad)
                TextField("management.publisher", text: $publisher)
                TextField("management.language", text: $language)
                TextField("management.isbn", text: $isbn)
                TextField("management.identifier", text: $identifier)
                TextField("management.narrator", text: $narrator)
                Button("management.save") {
                    store.updateVolume(
                        volume,
                        title: title,
                        index: Double(volumeIndex),
                        sortOrder: Int32(sortOrder) ?? 0,
                        publisher: publisher.nilIfBlank,
                        language: language.nilIfBlank,
                        isbn: isbn.nilIfBlank,
                        identifier: identifier.nilIfBlank,
                        narrator: narrator.nilIfBlank
                    )
                }
                .disabled(title.trimmingCharacters(in: .whitespaces).isEmpty || Int32(sortOrder) == nil)
            }
        }
    }

    private var metadata: some View {
        Section {
            TextField("management.query", text: $query)
            Picker("management.provider", selection: $providerID) {
                ForEach(store.metadataProviders, id: \.id) { provider in
                    Text(provider.name).tag(provider.id)
                }
            }
            Button("management.search") { store.searchMetadata(providerID: providerID, query: query) }
                .disabled(providerID.isEmpty || query.isEmpty)
            ForEach(store.metadataCandidates, id: \.id) { candidate in
                Button(candidate.title ?? candidate.id) {
                    selectedCandidate = candidate
                    selectedMetadataFields = availableFields(candidate)
                }
            }
            if let candidate = selectedCandidate {
                ForEach(availableFields(candidate).sorted { $0.name < $1.name }, id: \.name) { field in
                    Toggle(fieldTitle(field), isOn: Binding(
                        get: { selectedMetadataFields.contains(field) },
                        set: { enabled in
                            if enabled { selectedMetadataFields.insert(field) }
                            else { selectedMetadataFields.remove(field) }
                        }
                    ))
                }
                Toggle("management.applyAllVolumes", isOn: $appliesMetadataToAllVolumes)
                Button("management.applyMetadata") {
                    store.applyMetadata(
                        providerID: providerID,
                        candidate: candidate,
                        fields: selectedMetadataFields,
                        volumeID: detail.volumes.first(where: \.isSelected)?.id ?? detail.volumes.first?.id,
                        applyToAllVolumes: appliesMetadataToAllVolumes
                    )
                }
                .disabled(selectedMetadataFields.isEmpty)
            }
        }
    }

    @ViewBuilder private var mediaKind: some View {
        if let volume = activeVolume {
            Section {
                Picker("management.mediaKind", selection: $selectedKind) {
                    Text("management.ebook").tag(ErmaoShared.ManagedMediaKind.ebook)
                    Text("management.comic").tag(ErmaoShared.ManagedMediaKind.comic)
                    Text("management.audiobook").tag(ErmaoShared.ManagedMediaKind.audiobook)
                }
                .pickerStyle(.inline)
                Button("management.mediaKind") {
                    store.reclassify(
                        volume,
                        kind: selectedKind,
                        work: detail.work,
                        localKind: localKind(selectedKind)
                    )
                }
                .disabled(hasActiveDownload || selectedKind == sharedKind(activeVolume?.libraryMediaKind ?? .ebook))
                if hasActiveDownload { Text("management.activeDownloadBlocked") }
            }
        }
    }

    @ViewBuilder private var split: some View {
        if let volume = activeVolume {
            Section {
                TextField("management.title", text: $title)
                TextField("management.author", text: $author)
                Button("management.split") {
                    store.split(volume, title: title, author: author.nilIfBlank, mediaKind: volume.libraryMediaKind)
                }
                .disabled(title.isEmpty)
            }
        }
    }

    @ViewBuilder private var transfer: some View {
        if let volume = activeVolume {
            Section {
                TextField("management.query", text: $query)
                Button("management.search") { store.searchTransferTargets(query) }
                ForEach(store.transferTargets, id: \.id) { target in
                    Button {
                        selectedTransferTargetID = target.id
                    } label: {
                        HStack {
                            Text([target.title, target.author].filter { !$0.isEmpty }.joined(separator: " · "))
                            Spacer()
                            if selectedTransferTargetID == target.id { Image(systemName: "checkmark") }
                        }
                    }
                }
                Button("management.moveToSelectedWork") {
                    guard let target = store.transferTargets.first(where: { $0.id == selectedTransferTargetID }) else { return }
                    store.transfer(volume, target: target, mediaKind: volume.libraryMediaKind)
                }
                .disabled(hasActiveDownload || selectedTransferTargetID == nil)
            }
        }
    }

    private var kindle: some View {
        Section {
            if let settings = store.kindleSettings, settings.ready {
                Label("management.kindleReady", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(theme.actionAccent)
                LabeledContent("management.kindleSender", value: settings.senderEmail)
                LabeledContent("management.kindleRecipient", value: settings.recipientEmail)
            } else {
                Text("management.kindleNotReady")
            }
            ForEach(activeVolume.map { [$0] } ?? detail.volumes, id: \.id) { volume in
                ForEach(volume.files.filter(kindleFile), id: \.id) { file in
                    Button {
                        selectedKindleFileID = file.id
                    } label: {
                        HStack {
                            VStack(alignment: .leading) {
                                Text(file.path.split(separator: "/").last.map(String.init) ?? file.path)
                                Text("\(volume.title) · \(file.displaySize)")
                                    .appTextStyle(.caption)
                                    .foregroundStyle(theme.textSecondary)
                            }
                            Spacer()
                            if selectedKindleFileID == file.id { Image(systemName: "checkmark.circle.fill") }
                        }
                    }
                    .disabled(store.kindleSettings?.ready != true)
                }
            }
            Button("management.addToKindleQueue") {
                guard let selectedKindleFileID else { return }
                store.sendToKindle(fileID: selectedKindleFileID)
            }
            .disabled(store.kindleSettings?.ready != true || selectedKindleFileID == nil)
        }
    }

    private var hasActiveDownload: Bool {
        guard let state = activeDownload?.state else { return false }
        return state == .queued || state == .downloading
    }

    private func prepareFields() {
        title = activeVolume?.title ?? detail.work.title
        author = detail.work.author
        description = detail.description ?? ""
        series = detail.seriesFacet?.name ?? ""
        seriesIndex = detail.seriesIndex.map(String.init) ?? ""
        tags = detail.tags.joined(separator: ", ")
        volumeIndex = activeVolume?.volumeIndex.map(String.init) ?? ""
        sortOrder = activeVolume.map { String($0.sortOrder) } ?? "0"
        publisher = activeVolume?.publisher ?? ""
        language = activeVolume?.language ?? ""
        isbn = activeVolume?.isbn ?? ""
        identifier = activeVolume?.identifier ?? ""
        narrator = activeVolume?.narrator ?? ""
        query = detail.work.title
        providerID = store.metadataProviders.first?.id ?? ""
    }

    private func downloadButton(download: ManagedDownloadRecord?, action: @escaping () -> Void) -> some View {
        let title: LocalizedStringKey
        let image: String
        switch download?.state {
        case .queued, .downloading:
            title = "work.volume.download.pause"
            image = "pause.circle"
        case .paused, .failedRetryable, .failedTerminal:
            title = "work.volume.download.retry"
            image = "arrow.clockwise.circle"
        case .completed:
            title = "work.volume.download.completed"
            image = "checkmark.circle"
        case nil:
            title = "work.volume.download.action"
            image = "icloud.and.arrow.down"
        }
        return Button(title, systemImage: image, action: action)
    }

    private func sharedKind(_ kind: LibraryMediaKind) -> ErmaoShared.ManagedMediaKind {
        switch kind { case .ebook: .ebook; case .comic: .comic; case .audiobook: .audiobook }
    }

    private func localKind(_ kind: ErmaoShared.ManagedMediaKind) -> LibraryMediaKind {
        switch kind {
        case .ebook: .ebook
        case .comic: .comic
        case .audiobook: .audiobook
        default: activeVolume?.libraryMediaKind ?? .ebook
        }
    }

    private func volumeSummary(_ volume: WorkVolume) -> String {
        let state: String
        switch downloadForVolume(volume.id)?.state {
        case .queued, .downloading: state = String(localized: "management.downloadActive")
        case .paused: state = String(localized: "management.downloadPaused")
        case .completed: state = String(localized: "work.volume.download.completed")
        case .failedRetryable, .failedTerminal: state = String(localized: "downloads.failed")
        case nil: state = String(localized: "management.notDownloaded")
        }
        return [volume.files.first?.path.split(separator: ".").last.map { String($0).uppercased() }, state]
            .compactMap { $0 }
            .joined(separator: " · ")
    }

    private func kindleFile(_ file: WorkVolumeFile) -> Bool {
        let path = file.path.lowercased()
        return path.hasSuffix(".epub") || path.hasSuffix(".pdf")
    }

    private func availableFields(_ candidate: ErmaoShared.MetadataCandidate) -> Set<ErmaoShared.MetadataField> {
        var fields: Set<ErmaoShared.MetadataField> = []
        if candidate.coverUrl != nil { fields.insert(.cover) }
        if candidate.title != nil { fields.insert(.title) }
        if candidate.author != nil { fields.insert(.author) }
        if candidate.description_ != nil { fields.insert(.description) }
        if !candidate.tags.isEmpty { fields.insert(.tags) }
        if candidate.seriesName != nil { fields.insert(.seriesName) }
        if candidate.publisher != nil { fields.insert(.publisher) }
        if candidate.publishedAt != nil { fields.insert(.publishedAt) }
        if candidate.language != nil { fields.insert(.language) }
        if candidate.isbn != nil { fields.insert(.isbn) }
        return fields
    }

    private func fieldTitle(_ field: ErmaoShared.MetadataField) -> LocalizedStringKey {
        switch field {
        case .cover: "management.cover"
        case .title: "management.title"
        case .author: "management.author"
        case .description: "management.description"
        case .tags: "management.tagsLabel"
        case .seriesName: "management.series"
        case .publisher: "management.publisher"
        case .publishedAt: "management.publishedAt"
        case .language: "management.language"
        case .isbn: "management.isbn"
        default: "management.metadata"
        }
    }
}

private extension String {
    var nilIfBlank: String? {
        let value = trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }
}
