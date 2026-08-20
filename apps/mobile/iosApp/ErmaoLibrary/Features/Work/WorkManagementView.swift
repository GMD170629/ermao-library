import SwiftUI
@preconcurrency import ErmaoShared

enum WorkManagementTask: String, Identifiable {
    case addSeries, editWork, recognize, cover, editVolume, mediaKind, kindle

    var id: String { rawValue }
}

struct WorkManagementView: View {
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var store: WorkManagementStore
    let task: WorkManagementTask
    let detail: WorkDetailContent
    let volume: WorkVolume?
    let chooseCover: () -> Void
    let workCover: AnyView
    let downloadForVolume: (String) -> ManagedDownloadRecord?

    @State private var page: Page = .editWork
    @State private var title = ""
    @State private var author = ""
    @State private var description = ""
    @State private var series = ""
    @State private var seriesIndex = ""
    @State private var tags = ""
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
    @State private var selectedKindleFileID: String?
    @State private var confirmsCoverRegeneration = false

    private enum Page { case addSeries, editWork, editVolume, metadata, cover, readingStatus, mediaKind, kindle }

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
        case .kindle: .kindle
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
        case .kindle: "management.kindle"
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
        }
        .onChange(of: store.metadataProviders.map(\.id)) { ids in
            if providerID.isEmpty { providerID = ids.first ?? "" }
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
                TextField("management.publisher", text: $publisher)
                TextField("management.language", text: $language)
                TextField("management.isbn", text: $isbn)
                TextField("management.identifier", text: $identifier)
                TextField("management.narrator", text: $narrator)
                Button("management.save") {
                    store.updateVolume(
                        volume,
                        publisher: publisher.nilIfBlank,
                        language: language.nilIfBlank,
                        isbn: isbn.nilIfBlank,
                        identifier: identifier.nilIfBlank,
                        narrator: narrator.nilIfBlank
                    )
                }
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
                        kind: selectedKind
                    )
                }
                .disabled(hasActiveDownload || selectedKind == sharedKind(activeVolume?.libraryMediaKind ?? .ebook))
                if hasActiveDownload { Text("management.activeDownloadBlocked") }
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
        publisher = activeVolume?.publisher ?? ""
        language = activeVolume?.language ?? ""
        isbn = activeVolume?.isbn ?? ""
        identifier = activeVolume?.identifier ?? ""
        narrator = activeVolume?.narrator ?? ""
        query = detail.work.title
        providerID = store.metadataProviders.first?.id ?? ""
    }

    private func sharedKind(_ kind: LibraryMediaKind) -> ErmaoShared.ManagedMediaKind {
        switch kind { case .ebook: .ebook; case .comic: .comic; case .audiobook: .audiobook }
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
