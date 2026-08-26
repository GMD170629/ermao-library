import SwiftUI
import PhotosUI
import UIKit
import UniformTypeIdentifiers
@preconcurrency import ErmaoShared

enum WorkManagementTask: String, Identifiable {
    case addSeries, editWork, recognize, cover, editResource, kindle

    var id: String { rawValue }
}

struct WorkManagementView: View {
    @Environment(\.appTheme) private var theme
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var store: WorkManagementStore
    let task: WorkManagementTask
    let detail: BookDetailContent
    let resource: BookResource?
    let workCover: AnyView
    let downloadForResource: (String) -> ManagedDownloadRecord?

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
    @State private var appliesMetadataToAllResources = true
    @State private var managedResourceID: String?
    @State private var selectedReadingStatus: ErmaoShared.ManagedReadingStatus = .unread
    @State private var selectedKindleAssetID: String?
    @State private var confirmsCoverRegeneration = false
    @State private var selectedCoverPhoto: PhotosPickerItem?
    @State private var importsCoverFile = false
    @State private var coverSelectionErrorKey: String?

    private enum Page { case addSeries, editWork, editResource, metadata, cover, readingStatus, kindle }

    private var activeResource: BookResource? {
        managedResourceID.flatMap { id in detail.resources.first { $0.id == id } }
    }

    private var activeDownload: ManagedDownloadRecord? {
        activeResource.flatMap { downloadForResource($0.id) }
    }

    private var initialPage: Page {
        switch task {
        case .addSeries: .addSeries
        case .editWork: .editWork
        case .recognize: .metadata
        case .cover: .cover
        case .editResource: .editResource
        case .kindle: .kindle
        }
    }

    private var taskTitle: LocalizedStringKey {
        switch task {
        case .addSeries: "work.control.addSeries"
        case .editWork: "management.editWork"
        case .recognize: "management.metadata"
        case .cover: "management.cover"
        case .editResource: "management.editVolume"
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
            case .editResource: editResource
            case .metadata: metadata
            case .cover: coverManagement
            case .readingStatus: readingStatus
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
            managedResourceID = resource?.id
            page = initialPage
            prepareFields()
            if task == .recognize { store.loadMetadata() }
        }
        .onChange(of: store.metadataProviders.map(\.id)) { _, ids in
            if providerID.isEmpty { providerID = ids.first ?? "" }
        }
        .confirmationDialog(
            "management.regenerateCoverConfirmTitle",
            isPresented: $confirmsCoverRegeneration,
            titleVisibility: .visible
        ) {
            Button("management.regenerateCover") {
                if let resource = activeResource ?? detail.resources.first {
                    store.regenerateCover(resourceID: resource.id)
                }
            }
            Button("common.cancel", role: .cancel) {}
        } message: {
            Text("management.regenerateCoverConfirmMessage")
        }
        .fileImporter(
            isPresented: $importsCoverFile,
            allowedContentTypes: [.jpeg, .png, .webP],
            allowsMultipleSelection: false,
            onCompletion: handleCoverFileSelection
        )
        .onChange(of: selectedCoverPhoto) { _, item in
            guard let item else { return }
            loadCoverPhoto(item)
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
                    title: detail.book.title,
                    author: detail.book.author ?? "",
                    description: detail.description ?? "",
                    seriesName: series,
                    seriesIndex: Double(seriesIndex),
                    tags: detail.tags,
                    originalTags: detail.tags
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
                    tags: tags.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) },
                    originalTags: detail.tags
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
            if let resource = activeResource ?? detail.resources.first {
                LabeledContent("management.volume", value: resource.title)
            }
            PhotosPicker(selection: $selectedCoverPhoto, matching: .images) {
                Label("management.chooseCoverPhoto", systemImage: "photo.on.rectangle")
            }
            .disabled(store.isBusy || (activeResource ?? detail.resources.first) == nil)
            Button("management.chooseCoverFile", systemImage: "folder") {
                importsCoverFile = true
            }
            .disabled(store.isBusy || (activeResource ?? detail.resources.first) == nil)
            Button("management.regenerateCover", systemImage: "wand.and.stars") {
                confirmsCoverRegeneration = true
            }
            .disabled(store.isBusy || (activeResource ?? detail.resources.first) == nil)
            if let coverSelectionErrorKey {
                Text(LocalizedStringKey(coverSelectionErrorKey))
                    .foregroundStyle(.red)
                    .accessibilityIdentifier("management.cover.selection.error")
            }
        } footer: {
            Text("management.coverUploadHint")
        }
    }

    private func handleCoverFileSelection(_ result: Result<[URL], Error>) {
        guard case .success(let urls) = result, let url = urls.first else {
            if case .failure = result { coverSelectionErrorKey = "management.coverReadFailed" }
            return
        }
        let access = url.startAccessingSecurityScopedResource()
        defer { if access { url.stopAccessingSecurityScopedResource() } }
        guard let data = try? Data(contentsOf: url) else {
            coverSelectionErrorKey = "management.coverReadFailed"
            return
        }
        guard !data.isEmpty else {
            coverSelectionErrorKey = "management.coverEmpty"
            return
        }
        guard data.count <= CoverImagePreparation.maximumBytes else {
            coverSelectionErrorKey = "management.coverTooLarge"
            return
        }
        let mimeType: String
        switch url.pathExtension.lowercased() {
        case "jpg", "jpeg": mimeType = "image/jpeg"
        case "png": mimeType = "image/png"
        case "webp": mimeType = "image/webp"
        default:
            coverSelectionErrorKey = "management.coverUnsupported"
            return
        }
        submitCover(data: data, mimeType: mimeType, fileName: url.lastPathComponent)
    }

    private func loadCoverPhoto(_ item: PhotosPickerItem) {
        coverSelectionErrorKey = nil
        Task {
            defer { selectedCoverPhoto = nil }
            guard let source = try? await item.loadTransferable(type: Data.self),
                  let jpeg = CoverImagePreparation.jpeg(from: source) else {
                coverSelectionErrorKey = "management.coverReadFailed"
                return
            }
            submitCover(data: jpeg, mimeType: "image/jpeg", fileName: "cover.jpg")
        }
    }

    private func submitCover(data: Data, mimeType: String, fileName: String) {
        guard !data.isEmpty else {
            coverSelectionErrorKey = "management.coverEmpty"
            return
        }
        guard data.count <= CoverImagePreparation.maximumBytes else {
            coverSelectionErrorKey = "management.coverTooLarge"
            return
        }
        guard let resource = activeResource ?? detail.resources.first else {
            coverSelectionErrorKey = "management.noVolume"
            return
        }
        coverSelectionErrorKey = nil
        store.uploadCover(
            data: data,
            mimeType: mimeType,
            fileName: fileName,
            resourceID: resource.id
        )
    }

    @ViewBuilder private var readingStatus: some View {
        if let resource = detail.resources.first(where: \.isSelected) ?? detail.resources.first {
            Section(resource.title) {
                Picker("management.readingStatus", selection: $selectedReadingStatus) {
                    Text("work.status.unread").tag(ErmaoShared.ManagedReadingStatus.unread)
                    Text("work.status.finished").tag(ErmaoShared.ManagedReadingStatus.finished)
                }
                .pickerStyle(.segmented)
                Button("management.save") {
                    store.setReadingStatus(resourceID: resource.id, status: selectedReadingStatus)
                }
            }
        } else {
            Section { Text("management.noVolume") }
        }
    }

    @ViewBuilder private var editResource: some View {
        if let resource = activeResource {
            Section {
                TextField("management.publisher", text: $publisher)
                TextField("management.language", text: $language)
                TextField("management.isbn", text: $isbn)
                TextField("management.identifier", text: $identifier)
                TextField("management.narrator", text: $narrator)
                Button("management.save") {
                    store.updateResource(
                        resource,
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
            Button("management.search") {
                let sourceNodeID = activeResource?.sourceNodeID ?? detail.resources.first?.sourceNodeID ?? ""
                store.searchMetadata(providerID: providerID, sourceNodeID: sourceNodeID, query: query)
            }
                .disabled(providerID.isEmpty || query.isEmpty || (activeResource?.sourceNodeID ?? detail.resources.first?.sourceNodeID ?? "").isEmpty)
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
                Toggle("management.applyAllVolumes", isOn: $appliesMetadataToAllResources)
                Button("management.applyMetadata") {
                    store.applyMetadata(
                        providerID: providerID,
                        candidate: candidate,
                        fields: selectedMetadataFields,
                        resourceID: detail.resources.first(where: \.isSelected)?.id ?? detail.resources.first?.id,
                        sourceNodeID: detail.resources.first(where: \.isSelected)?.sourceNodeID ?? detail.resources.first?.sourceNodeID ?? "",
                        applyToAllResources: appliesMetadataToAllResources
                    )
                }
                .disabled(selectedMetadataFields.isEmpty)
            }
        }
    }

    private var kindle: some View {
        Section {
            if let settings = store.kindleSettings, kindleReady(settings) {
                Label("management.kindleReady", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(theme.actionAccent)
                LabeledContent("management.kindleSender", value: settings.senderEmail)
                LabeledContent("management.kindleRecipient", value: settings.recipientEmail)
            } else {
                Text("management.kindleNotReady")
            }
            ForEach(activeResource.map { [$0] } ?? detail.resources, id: \.id) { resource in
                ForEach(resource.assets.filter(kindleAsset), id: \.id) { asset in
                    Button {
                        selectedKindleAssetID = asset.id
                    } label: {
                        HStack {
                            VStack(alignment: .leading) {
                                Text(asset.path.split(separator: "/").last.map(String.init) ?? asset.path)
                                Text("\(resource.title) · \(asset.displaySize)")
                                    .appTextStyle(.caption)
                                    .foregroundStyle(theme.textSecondary)
                            }
                            Spacer()
                            if selectedKindleAssetID == asset.id { Image(systemName: "checkmark.circle.fill") }
                        }
                    }
                    .disabled(!kindleReady(store.kindleSettings))
                }
            }
            Button("management.addToKindleQueue") {
                guard let selectedKindleAssetID else { return }
                store.sendToKindle(assetID: selectedKindleAssetID)
            }
            .disabled(!kindleReady(store.kindleSettings) || selectedKindleAssetID == nil)
        }
    }

    private var hasActiveDownload: Bool {
        guard let state = activeDownload?.state else { return false }
        return state == .queued || state == .downloading
    }

    private func prepareFields() {
        title = activeResource?.title ?? detail.book.title
        author = detail.book.author ?? ""
        description = detail.description ?? ""
        series = detail.seriesFacet?.name ?? ""
        seriesIndex = detail.seriesIndex.map { String($0) } ?? ""
        tags = detail.tags.joined(separator: ", ")
        publisher = activeResource?.publisher ?? ""
        language = activeResource?.language ?? ""
        isbn = activeResource?.isbn ?? ""
        identifier = activeResource?.identifier ?? ""
        narrator = activeResource?.narrator ?? ""
        query = detail.book.title
        providerID = store.metadataProviders.first?.id ?? ""
    }

    private func kindleAsset(_ asset: ResourceAsset) -> Bool {
        let path = asset.path.lowercased()
        return path.hasSuffix(".epub") || path.hasSuffix(".pdf")
    }

    private func kindleReady(_ settings: ErmaoShared.KindleSettings?) -> Bool {
        guard let settings else { return false }
        return settings.smtpConfigured
            && !settings.senderEmail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !settings.recipientEmail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func availableFields(_ candidate: ErmaoShared.MetadataCandidate) -> Set<ErmaoShared.MetadataField> {
        var fields: Set<ErmaoShared.MetadataField> = []
        if candidate.coverUrl != nil { fields.insert(.cover) }
        if candidate.title != nil { fields.insert(.title) }
        if candidate.author != nil { fields.insert(.author) }
        if candidate.description_ != nil { fields.insert(.description_) }
        if !candidate.tags.isEmpty { fields.insert(.tags) }
        if candidate.seriesName != nil { fields.insert(.seriesname) }
        if candidate.publisher != nil { fields.insert(.publisher) }
        if candidate.publishedAt != nil { fields.insert(.publishedat) }
        if candidate.language != nil { fields.insert(.language) }
        if candidate.isbn != nil { fields.insert(.isbn) }
        return fields
    }

    private func fieldTitle(_ field: ErmaoShared.MetadataField) -> LocalizedStringKey {
        switch field {
        case .cover: "management.cover"
        case .title: "management.title"
        case .author: "management.author"
        case .description_: "management.description"
        case .tags: "management.tagsLabel"
        case .seriesname: "management.series"
        case .publisher: "management.publisher"
        case .publishedat: "management.publishedAt"
        case .language: "management.language"
        case .isbn: "management.isbn"
        default: "management.metadata"
        }
    }
}

private enum CoverImagePreparation {
    static let maximumBytes = 10 * 1024 * 1024

    static func jpeg(from data: Data) -> Data? {
        guard let source = UIImage(data: data) else { return nil }
        for maximumDimension in [4096, 3200, 2400, 1800] {
            let normalized = rendered(source, maximumDimension: CGFloat(maximumDimension))
            for quality in [0.92, 0.82, 0.72, 0.60, 0.48] {
                if let encoded = normalized.jpegData(compressionQuality: quality),
                   encoded.count <= maximumBytes {
                    return encoded
                }
            }
        }
        return nil
    }

    private static func rendered(_ image: UIImage, maximumDimension: CGFloat) -> UIImage {
        let pixelWidth = CGFloat(image.cgImage?.width ?? Int(image.size.width * image.scale))
        let pixelHeight = CGFloat(image.cgImage?.height ?? Int(image.size.height * image.scale))
        let scale = min(1, maximumDimension / max(pixelWidth, pixelHeight))
        let size = CGSize(width: max(1, pixelWidth * scale), height: max(1, pixelHeight * scale))
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        return UIGraphicsImageRenderer(size: size, format: format).image { _ in
            UIColor.white.setFill()
            UIRectFill(CGRect(origin: .zero, size: size))
            image.draw(in: CGRect(origin: .zero, size: size))
        }
    }
}

private extension String {
    var nilIfBlank: String? {
        let value = trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }
}
