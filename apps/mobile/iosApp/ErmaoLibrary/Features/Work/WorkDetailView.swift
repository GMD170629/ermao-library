import SwiftUI
import UniformTypeIdentifiers
@preconcurrency import ErmaoShared

struct WorkReaderSelection: Equatable, Sendable {
    let workID: String
    let volumeID: String
    let displayTitle: String
}

private enum WorkControlTarget: Equatable {
    case book
    case volume(String)
}

private struct WorkControlAction: Identifiable {
    let id: String
    let title: LocalizedStringKey
    let systemImage: String
    let enabled: Bool
    let destructive: Bool
    let perform: () -> Void
}

struct WorkDetailView: View {
    let context: ContentRequestContext
    let client: any ContentClient
    let shelfClient: any ShelfClient
    let cache: LibraryCacheStore
    @ObservedObject var downloads: DownloadCenterStore
    let openFacet: (FacetKind, String) -> Void
    let openDownloads: () -> Void
    let openReader: (ReaderHandoff) -> Void
    let prepareReader: (ReaderPreparationRequest) -> Void
    let onWorkDeleted: () -> Void
    let managementRepository: (any ErmaoShared.WorkManagementRepository)?
    let canManageSystem: Bool

    @StateObject private var store: WorkDetailStore
    @State private var showsShelfPicker = false
    @State private var shelves: [ShelfOption] = []
    @State private var selectedShelfIDs: Set<String> = []
    @State private var isLoadingShelves = false
    @State private var isSavingShelves = false
    @State private var shelfError = false
    @State private var isDescriptionExpanded = false
    @State private var unavailableFeature: UnavailableWorkFeature?
    @State private var readerAccessErrorCode: String?
    @State private var managementStore: WorkManagementStore?
    @State private var managedVolumeID: String?
    @State private var managementTask: WorkManagementTask?
    @State private var importsCover = false
    @State private var controlTarget: WorkControlTarget?
    @State private var controlAnchor = CGPoint(x: 260, y: 220)
    @State private var latestPointerLocation = CGPoint(x: 260, y: 220)
    @Environment(\.appTheme) private var theme
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.locale) private var locale

    init(
        context: ContentRequestContext,
        client: any ContentClient,
        shelfClient: any ShelfClient,
        cache: LibraryCacheStore,
        downloads: DownloadCenterStore,
        managementRepository: (any ErmaoShared.WorkManagementRepository)? = nil,
        canManageSystem: Bool = false,
        workID: String,
        onUnauthorized: @escaping @MainActor () -> Void,
        openFacet: @escaping (FacetKind, String) -> Void,
        openDownloads: @escaping () -> Void,
        openReader: @escaping (ReaderHandoff) -> Void,
        prepareReader: @escaping (ReaderPreparationRequest) -> Void,
        onWorkDeleted: @escaping () -> Void = {}
    ) {
        self.context = context
        self.client = client
        self.shelfClient = shelfClient
        self.cache = cache
        self.downloads = downloads
        self.managementRepository = managementRepository
        self.canManageSystem = canManageSystem
        self.openFacet = openFacet
        self.openDownloads = openDownloads
        self.openReader = openReader
        self.prepareReader = prepareReader
        self.onWorkDeleted = onWorkDeleted
        _store = StateObject(
            wrappedValue: WorkDetailStore(
                context: context,
                client: client,
                cache: cache,
                workID: workID,
                onUnauthorized: onUnauthorized
            )
        )
        _managementStore = State(
            initialValue: managementRepository.flatMap { repository in
                WorkManagementStore(repository: repository, context: context, workID: workID)
            }
        )
    }

    var body: some View {
        ScrollView {
            content
                .padding(.horizontal, .space2)
                .padding(.bottom, .space4)
        }
        .navigationTitle("work.detail.title")
        .accessibilityIdentifier("work.detail.screen")
        .navigationBarTitleDisplayMode(.inline)
        .sheet(isPresented: $showsShelfPicker) { shelfPicker }
        .sheet(item: $managementTask) { task in
            NavigationStack { managementPage(task: task) }
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .fileImporter(
            isPresented: $importsCover,
            allowedContentTypes: [.jpeg, .png, .webP],
            allowsMultipleSelection: false
        ) { result in
            guard case .success(let urls) = result, let url = urls.first else { return }
            let access = url.startAccessingSecurityScopedResource()
            defer { if access { url.stopAccessingSecurityScopedResource() } }
            guard let data = try? Data(contentsOf: url), data.count <= 10 * 1024 * 1024 else { return }
            let mime = url.pathExtension.lowercased() == "png" ? "image/png"
                : url.pathExtension.lowercased() == "webp" ? "image/webp" : "image/jpeg"
            managementStore?.uploadCover(data: data, mimeType: mime, fileName: url.lastPathComponent)
        }
        .confirmationDialog(
            "work.unavailable.title",
            isPresented: Binding(
                get: { unavailableFeature != nil },
                set: { if !$0 { unavailableFeature = nil } }
            ),
            titleVisibility: .visible,
            presenting: unavailableFeature
        ) { _ in
            Button("common.done", role: .cancel) { unavailableFeature = nil }
        } message: { feature in
            Text(feature.message)
        }
        .alert(
            "reader.handoff.error.title",
            isPresented: Binding(
                get: { readerAccessErrorCode != nil },
                set: { if !$0 { readerAccessErrorCode = nil } }
            )
        ) {
            Button("common.done", role: .cancel) { readerAccessErrorCode = nil }
        } message: {
            Text(readerAccessErrorMessage)
        }
        .overlay { controlMenuOverlay }
        .appCanvas()
        .task { store.load() }
        .onAppear { store.refreshIfLoaded() }
        .onChange(of: managementStore?.completedAction) { action in
            handleManagementCompletion(action)
        }
    }

    @ViewBuilder
    private var content: some View {
        switch store.state {
        case .loading:
            HStack { Spacer(); ProgressView(); Spacer() }.frame(minHeight: 420)
        case .failure:
            ContentStatusView(
                systemImage: "wifi.exclamationmark",
                title: "work.error.title",
                message: "work.error.message",
                actionTitle: "common.retry",
                action: { store.load() }
            )
        case .inaccessible:
            ContentStatusView(
                systemImage: "eye.slash",
                title: "content.inaccessible.title",
                message: "content.inaccessible.message"
            )
        case .ready(let detail, _):
            readyContent(detail)
        }
    }

    private func readyContent(_ detail: WorkDetailContent) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            hero(detail)
                .padding(.top, .spaceHalf)
                .padding(.bottom, .space2)

            readerAction(detail)
                .padding(.bottom, .space2)

            if hasDescription(detail) {
                aboutSection(detail)
                    .padding(.bottom, .space2)
            }
            Divider().padding(.vertical, .space2)
            mediaSection(detail)
        }
    }

    @ViewBuilder
    private func hero(_ detail: WorkDetailContent) -> some View {
        VStack(alignment: .center, spacing: .space1Half) {
            cover(detail).frame(width: dynamicTypeSize.isAccessibilitySize ? 124 : 132)
            identity(detail)
                .frame(maxWidth: .infinity)
        }
    }

    private func cover(_ detail: WorkDetailContent) -> some View {
        BookCoverView(
            reference: detail.work.cover,
            title: detail.work.title,
            context: context,
            client: client,
            cache: cache,
            cornerRadius: CGFloat(GeneratedDesignTokens.Radii.coverHero)
        )
    }

    private func identity(_ detail: WorkDetailContent) -> some View {
        VStack(alignment: .center, spacing: .spaceHalf) {
            Text(detail.work.title)
                .appTextStyle(.title)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)

            creatorSeriesLine(detail)

            let chips = identityChips(detail)
            if !chips.isEmpty {
                FlowTags(tags: chips)
            }

            Spacer(minLength: .spaceHalf)
            progressSummary(detail)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func identityChips(_ detail: WorkDetailContent) -> [String] {
        detail.tags.reduce(into: []) { result, value in
            guard !result.contains(where: { $0.caseInsensitiveCompare(value) == .orderedSame }) else { return }
            result.append(value)
        }
    }

    private func creatorSeriesLine(_ detail: WorkDetailContent) -> some View {
        HStack(spacing: .spaceHalf) {
            if let author = detail.authorFacets.first {
                facetButton(author, kind: .author)
            } else {
                Text(detail.work.author)
                    .appTextStyle(.body)
                    .foregroundStyle(theme.textSecondary)
            }
            if let series = detail.seriesFacet {
                Text("/").foregroundStyle(theme.textTertiary)
                facetButton(series, kind: .series)
            }
        }
        .lineLimit(1)
        .minimumScaleFactor(0.8)
        .accessibilityElement(children: .contain)
    }

    private func facetButton(_ facet: FacetIdentity, kind: FacetKind) -> some View {
        Button {
            openFacet(kind, facet.id)
        } label: {
            Text(facet.name)
            .frame(
                minHeight: .iosMinimumTouchTarget,
                alignment: .center
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .appTextStyle(.label)
        .foregroundStyle(theme.textSecondary)
        .accessibilityHint(Text(kind == .series ? "work.series.accessibility.hint" : "work.author.accessibility.hint"))
    }

    @ViewBuilder
    private func progressSummary(_ detail: WorkDetailContent) -> some View {
        let progress = detail.work.progress ?? detail.volumes.compactMap(\.progress).max()
        if let progress, progress > 0 {
            VStack(alignment: .leading, spacing: .space1) {
                HStack(alignment: .firstTextBaseline, spacing: .spaceHalf) {
                    Text("work.reading.progress")
                        .appTextStyle(.label)
                        .foregroundStyle(theme.textSecondary)
                    Text("\(Int(progress))%")
                        .appTextStyle(.headline)
                        .monospacedDigit()
                    Spacer()
                    if let current = detail.chapters.first(where: \.isCurrent) {
                        Text(String(format: String(localized: "work.reading.position.format"), current.title))
                            .lineLimit(1)
                            .truncationMode(.tail)
                            .appTextStyle(.label)
                            .foregroundStyle(theme.textSecondary)
                    }
                }
                ProgressView(value: min(100, progress), total: 100)
                    .tint(theme.brandAccent)
                    .accessibilityValue(Text("\(Int(progress))%"))
            }
        }
    }

    private func readerAction(_ detail: WorkDetailContent) -> some View {
        let selected = selectedVolume(detail)
        return VStack(spacing: .space1) {
            PrimaryActionButton(
                detail.readingStatus == .reading ? "work.reader.continue.action" : "work.reader.start.action",
                systemImage: "play.circle",
                isDisabled: selected == nil || selected?.isReadable == false,
                action: { requestReaderAccess(detail: detail) }
            )
            HStack(spacing: 0) {
                quickAction("work.action.download", systemImage: "icloud.and.arrow.down") {
                    enqueueSelectedVolume()
                }
                Menu {
                    ForEach(LibraryReadingStatus.manualChoices, id: \.self) { status in
                        Button(status.title) {
                            if let managementStore,
                               let sharedStatus = status.sharedValue,
                               let volumeID = selected?.id {
                                managementStore.setReadingStatus(volumeID: volumeID, status: sharedStatus)
                            } else {
                                unavailableFeature = .readingStatus
                            }
                        }
                    }
                } label: {
                    quickActionLabel("work.action.readingStatus", systemImage: "chart.pie")
                }
                .frame(maxWidth: .infinity)
                quickAction("work.action.add", systemImage: "books.vertical") { openShelfPicker() }
                anchoredQuickAction("common.more", systemImage: "ellipsis") { anchor in
                    controlAnchor = anchor
                    controlTarget = .book
                }
            }
        }
    }

    private func quickAction(
        _ title: LocalizedStringKey,
        systemImage: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) { quickActionLabel(title, systemImage: systemImage) }
            .buttonStyle(.plain)
            .frame(maxWidth: .infinity)
    }

    private func quickActionLabel(_ title: LocalizedStringKey, systemImage: String) -> some View {
        VStack(spacing: .spaceHalf) {
            Image(systemName: systemImage).font(.body)
            Text(title).appTextStyle(.caption).lineLimit(1).minimumScaleFactor(0.8)
        }
        .foregroundStyle(theme.textSecondary)
        .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget)
        .contentShape(Rectangle())
    }

    private func anchoredQuickAction(
        _ title: LocalizedStringKey,
        systemImage: String,
        action: @escaping (CGPoint) -> Void
    ) -> some View {
        GeometryReader { proxy in
            Button {
                let frame = proxy.frame(in: .global)
                action(CGPoint(x: frame.midX, y: frame.midY))
            } label: {
                quickActionLabel(title, systemImage: systemImage)
            }
            .buttonStyle(.plain)
        }
        .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget)
    }

    @ViewBuilder
    private func aboutSection(_ detail: WorkDetailContent) -> some View {
        if let description = normalizedDescription(detail) {
            VStack(alignment: .leading, spacing: .space1Half) {
                Text("work.description.title").appTextStyle(.sectionTitle)
                Text(description)
                    .appTextStyle(.body)
                    .foregroundStyle(theme.textSecondary)
                    .lineLimit(isDescriptionExpanded ? nil : 4)
                    .fixedSize(horizontal: false, vertical: true)
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        isDescriptionExpanded.toggle()
                    }
                } label: {
                    Image(systemName: isDescriptionExpanded ? "chevron.up" : "chevron.down")
                        .font(.body.weight(.medium))
                        .frame(width: .iosMinimumTouchTarget, height: .iosMinimumTouchTarget)
                }
                .buttonStyle(.plain)
                .foregroundStyle(theme.textPrimary)
                .frame(maxWidth: .infinity, alignment: .center)
                .accessibilityLabel(Text(isDescriptionExpanded ? "work.description.collapse" : "work.description.expand"))
            }
            .padding(.space2)
            .background(
                theme.surface,
                in: RoundedRectangle(cornerRadius: CGFloat(GeneratedDesignTokens.Radii.task), style: .continuous)
            )
            .overlay {
                RoundedRectangle(cornerRadius: CGFloat(GeneratedDesignTokens.Radii.task), style: .continuous)
                    .stroke(theme.divider.opacity(0.75), lineWidth: 0.5)
            }
            .shadow(color: theme.textPrimary.opacity(0.08), radius: 10, x: 0, y: 4)
        }
    }

    private func hasDescription(_ detail: WorkDetailContent) -> Bool {
        normalizedDescription(detail) != nil
    }

    private func normalizedDescription(_ detail: WorkDetailContent) -> String? {
        guard let rawValue = detail.description?.trimmingCharacters(in: .whitespacesAndNewlines),
              !rawValue.isEmpty else { return nil }
        let rendered = rawValue.data(using: .utf8).flatMap { data in
            try? NSAttributedString(
                data: data,
                options: [.documentType: NSAttributedString.DocumentType.html, .characterEncoding: String.Encoding.utf8.rawValue],
                documentAttributes: nil
            ).string
        } ?? rawValue
        let value = rendered
            .replacingOccurrences(of: #"[\t ]+"#, with: " ", options: .regularExpression)
            .replacingOccurrences(of: #"\n{3,}"#, with: "\n\n", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }

    private func mediaSection(_ detail: WorkDetailContent) -> some View {
        VStack(alignment: .leading, spacing: .space2) {
            mediaPicker(detail)
            volumeSection(detail)
            if let selected = selectedVolume(detail) { selectedVolumeMetadata(selected) }
        }
    }

    @ViewBuilder
    private func mediaPicker(_ detail: WorkDetailContent) -> some View {
        if detail.showsVersionPicker {
            HStack(spacing: .space2) {
                Text("work.media.title").appTextStyle(.sectionTitle)
                Spacer(minLength: .space1)
                Picker(
                    "work.media.title",
                    selection: Binding(
                        get: { detail.selectedVersionId ?? detail.versions.first?.id ?? "" },
                        set: { store.load(versionId: $0) }
                    )
                ) {
                    ForEach(detail.versions) { version in
                        Text(version.displayTitle).tag(version.id)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .tint(theme.brandAccent)
                .frame(width: min(CGFloat(detail.versions.count) * 80, 240))
            }
        }
    }

    @ViewBuilder
    private func volumeSection(_ detail: WorkDetailContent) -> some View {
        if detail.volumes.isEmpty {
            ContentStatusView(
                systemImage: "books.vertical",
                title: "work.volumes.empty.title",
                message: "work.volumes.empty.message"
            )
        } else {
            VStack(alignment: .leading, spacing: .space2) {
                ScrollView(.horizontal, showsIndicators: false) {
                    LazyHStack(alignment: .top, spacing: .space1Half) {
                        ForEach(Array(detail.volumes.enumerated()), id: \.element.id) { position, volume in
                            volumeCoverItem(volume, position: position, detail: detail)
                                .frame(width: dynamicTypeSize.isAccessibilitySize ? 160 : 108)
                                .onAppear {
                                    if position >= detail.volumes.count - 3 { store.loadMoreVolumes() }
                                }
                        }
                        if store.isLoadingMoreVolumes || store.hasVolumePaginationError {
                            Button {
                                store.loadMoreVolumes()
                            } label: {
                                Text(store.hasVolumePaginationError
                                     ? "work.volumes.loadMore.failed"
                                     : "work.volumes.loadMore.loading")
                                    .appTextStyle(.caption)
                                    .foregroundStyle(theme.textSecondary)
                                    .multilineTextAlignment(.center)
                                    .frame(width: 108, minHeight: .iosMinimumTouchTarget)
                            }
                            .buttonStyle(.plain)
                            .disabled(!store.hasVolumePaginationError)
                        }
                    }
                }
            }
        }
    }

    private func volumeCoverItem(
        _ volume: WorkVolume,
        position: Int,
        detail: WorkDetailContent
    ) -> some View {
        let index = volume.displayIndex(position: position)
        return VStack(alignment: .leading, spacing: .space1) {
            ZStack(alignment: .topLeading) {
                Button {
                    store.load(versionId: detail.selectedVersionId, volumeID: volume.id)
                } label: {
                    BookCoverView(
                        reference: volume.cover,
                        title: volume.title,
                        context: context,
                        client: client,
                        cache: cache
                    )
                    .opacity(volume.isReadable == false ? 0.5 : 1)
                    .overlay {
                        if volume.isSelected {
                            RoundedRectangle(
                                cornerRadius: CGFloat(GeneratedDesignTokens.Radii.coverCompact),
                                style: .continuous
                            )
                            .stroke(theme.brandAccent, lineWidth: 2)
                        }
                    }
                    .overlay(alignment: .bottom) {
                        if let progress = volume.progress, progress > 0 {
                            VolumeCoverProgressView(progress: progress)
                                .padding(.horizontal, .space1)
                                .padding(.bottom, .spaceHalf)
                        }
                    }
                }
                .buttonStyle(.plain)
                .accessibilityElement(children: .ignore)
                .accessibilityIdentifier("work.volume.\(volume.id)")
                .accessibilityLabel(Text(volumeAccessibilityLabel(volume, index: index)))
                .accessibilityValue(volumeAccessibilityValue(volume))
                .accessibilityAddTraits(volume.isSelected ? .isSelected : [])
                .onLongPressGesture {
                    controlAnchor = latestPointerLocation
                    controlTarget = .volume(volume.id)
                }
                .simultaneousGesture(
                    DragGesture(minimumDistance: 0, coordinateSpace: .global)
                        .onChanged { latestPointerLocation = $0.location }
                )
                .accessibilityAction(named: Text("management.volume")) {
                    controlAnchor = latestPointerLocation
                    controlTarget = .volume(volume.id)
                }

                Text(index)
                    .appTextStyle(.caption)
                    .monospacedDigit()
                    .foregroundStyle(theme.textSecondary)
                    .padding(.horizontal, .space1)
                    .padding(.vertical, .spaceHalf)
                    .background(theme.surfaceRaised.opacity(0.92))
                    .clipShape(RoundedRectangle(
                        cornerRadius: CGFloat(GeneratedDesignTokens.Radii.coverCompact),
                        style: .continuous
                    ))
                    .padding(.space1)
                    .accessibilityHidden(true)

                Button {
                    handleDownload(volume, detail: detail)
                } label: {
                    Image(systemName: downloadSystemImage(volumeID: volume.id))
                        .font(.body.weight(.medium))
                        .foregroundStyle(downloadForeground(volumeID: volume.id))
                        .frame(width: 24, height: 24)
                        .background(theme.surfaceRaised.opacity(0.92))
                        .clipShape(Circle())
                        .frame(width: .iosMinimumTouchTarget, height: .iosMinimumTouchTarget)
                }
                .buttonStyle(.plain)
                .disabled(downloads.record(for: volume.id)?.isVerifiedOfflineCopy == true)
                .accessibilityLabel(Text(downloadAccessibilityLabel(volumeID: volume.id)))
                .frame(maxWidth: .infinity, alignment: .topTrailing)
            }

            Text(volume.title)
                .appTextStyle(.label)
                .foregroundStyle(theme.textPrimary)
                .lineLimit(2)
                .frame(minHeight: 40, alignment: .topLeading)
        }
    }

    private func selectedVolumeMetadata(_ volume: WorkVolume) -> some View {
        let rows: [(LocalizedStringKey, String?)] = [
            ("work.metadata.format", volume.formatLabel),
            ("work.metadata.language", volume.language),
            ("work.metadata.published", formattedMetadataDate(volume.publishedAt)),
            ("work.metadata.pages", volume.pageCount.map(String.init)),
            ("work.metadata.source", volume.metadataSource),
            ("work.metadata.filePath", volume.files.first?.path),
        ]
        return VStack(alignment: .leading, spacing: 0) {
            Text("work.metadata.title").appTextStyle(.sectionTitle)
                .padding(.bottom, .space1)
            ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                HStack(alignment: .firstTextBaseline, spacing: .space2) {
                    Text(row.0).appTextStyle(.body).foregroundStyle(theme.textSecondary)
                    Spacer(minLength: .space1)
                    Text(metadataValue(row.1))
                        .appTextStyle(.body)
                        .multilineTextAlignment(.trailing)
                        .lineLimit(2)
                }
                .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget)
                Divider()
            }
        }
        .accessibilityIdentifier("work.selectedVolume.metadata")
    }

    private func metadataValue(_ rawValue: String?) -> String {
        guard let value = rawValue?.trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty else { return "—" }
        return value
    }

    private func formattedMetadataDate(_ rawValue: String?) -> String? {
        guard let rawValue, rawValue.count >= 10 else { return rawValue }
        let input = DateFormatter()
        input.calendar = Calendar(identifier: .gregorian)
        input.locale = Locale(identifier: "en_US_POSIX")
        input.dateFormat = "yyyy-MM-dd"
        guard let date = input.date(from: String(rawValue.prefix(10))) else { return rawValue }
        let output = DateFormatter()
        output.locale = locale
        output.dateStyle = .medium
        output.timeStyle = .none
        return output.string(from: date)
    }

    private func progressLabel(_ progress: Double) -> String {
        String(
            format: String(localized: "work.progress.format"),
            locale: .current,
            Int(progress)
        )
    }

    private func volumeAccessibilityValue(_ volume: WorkVolume) -> Text {
        if let progress = volume.progress {
            return Text("\(progressLabel(progress))")
        }
        return Text("work.volume.progress.notStarted")
    }

    private func volumeAccessibilityLabel(_ volume: WorkVolume, index: String) -> String {
        String(
            format: String(localized: "work.volume.accessibility.label"),
            locale: .current,
            index,
            volume.title
        )
    }

    private func selectedVolume(_ detail: WorkDetailContent) -> WorkVolume? {
        detail.volumes.first(where: \.isSelected) ?? detail.volumes.first
    }

    private var currentDetail: WorkDetailContent? {
        guard case .ready(let detail, _) = store.state else { return nil }
        return detail
    }

    @ViewBuilder
    private var controlMenuOverlay: some View {
        if let controlTarget, let detail = currentDetail {
            GeometryReader { geometry in
                let menuWidth = min(224, geometry.size.width - 24)
                let estimatedHeight = min(
                    CGFloat(controlActions(target: controlTarget, detail: detail).count * 48 + 72),
                    geometry.size.height - 24
                )
                let overlayFrame = geometry.frame(in: .global)
                let localAnchor = CGPoint(
                    x: controlAnchor.x - overlayFrame.minX,
                    y: controlAnchor.y - overlayFrame.minY
                )
                let proposedX = localAnchor.x + menuWidth <= geometry.size.width - 12
                    ? localAnchor.x : localAnchor.x - menuWidth
                let proposedY = localAnchor.y + estimatedHeight <= geometry.size.height - 12
                    ? localAnchor.y : localAnchor.y - estimatedHeight
                let originX = min(max(12, proposedX), geometry.size.width - menuWidth - 12)
                let originY = min(max(12, proposedY), geometry.size.height - estimatedHeight - 12)
                ZStack(alignment: .topLeading) {
                    Color.black.opacity(0.30)
                        .ignoresSafeArea()
                        .contentShape(Rectangle())
                        .onTapGesture { self.controlTarget = nil }

                    controlMenuCard(target: controlTarget, detail: detail)
                        .frame(width: menuWidth)
                        .frame(maxHeight: estimatedHeight)
                        .offset(x: originX, y: originY)
                }
            }
            .transition(.opacity.combined(with: .scale(scale: 0.96, anchor: .topTrailing)))
            .zIndex(20)
        }
    }

    private func controlMenuCard(target: WorkControlTarget, detail: WorkDetailContent) -> some View {
        let actions = controlActions(target: target, detail: detail)
        let destructive = actions.first(where: \.destructive)
        let regular = actions.filter { !$0.destructive }
        return VStack(spacing: 0) {
            controlMenuHeader(target: target, detail: detail)
                .padding(.horizontal, 14)
                .padding(.vertical, 12)
            Divider().overlay(theme.divider.opacity(0.72))
            ScrollView {
                LazyVStack(spacing: 0) {
                    ForEach(regular) { action in
                        controlMenuRow(action)
                        if action.id != regular.last?.id {
                            Divider().overlay(theme.divider.opacity(0.60))
                        }
                    }
                }
            }
            if let destructive {
                Divider().overlay(theme.divider.opacity(0.72))
                controlMenuRow(destructive)
            }
        }
        .background(.ultraThinMaterial)
        .background(theme.surfaceRaised.opacity(0.88))
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(theme.divider.opacity(0.72), lineWidth: 1)
        }
        .shadow(color: .black.opacity(0.22), radius: 18, x: 0, y: 9)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(target == .book ? "work.book.controlMenu" : "work.volume.controlMenu")
    }

    private func controlMenuRow(_ action: WorkControlAction) -> some View {
        Button(role: action.destructive ? .destructive : nil, action: action.perform) {
            HStack(spacing: .space1) {
                Text(action.title)
                    .appTextStyle(.callout)
                    .foregroundStyle(action.destructive ? Color.red : theme.textPrimary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Image(systemName: action.systemImage)
                    .font(.body.weight(.medium))
                    .foregroundStyle(action.destructive ? Color.red : theme.textSecondary)
                    .frame(width: 20, height: 20)
            }
            .frame(minHeight: .iosMinimumTouchTarget)
            .padding(.horizontal, 14)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!action.enabled)
        .opacity(action.enabled ? 1 : 0.45)
    }

    private func controlMenuHeader(target: WorkControlTarget, detail: WorkDetailContent) -> some View {
        let volume = controlVolume(target: target, detail: detail)
        return HStack(spacing: .space1) {
            Group {
                if let volume {
                    BookCoverView(
                        reference: volume.cover,
                        title: volume.title,
                        context: context,
                        client: client,
                        cache: cache
                    )
                } else {
                    cover(detail)
                }
            }
            .frame(width: 38)
            VStack(alignment: .leading, spacing: .spaceHalf) {
                Text(target == .book ? detail.work.title : (volume?.title ?? detail.work.title))
                    .appTextStyle(.body)
                    .fontWeight(.semibold)
                    .foregroundStyle(theme.textPrimary)
                    .lineLimit(1)
                if let volume {
                    Text("\(volume.title) · \(volume.formatLabel)")
                        .appTextStyle(.caption)
                        .foregroundStyle(theme.textSecondary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 0)
        }
    }

    private func controlActions(
        target: WorkControlTarget,
        detail: WorkDetailContent
    ) -> [WorkControlAction] {
        let volume = controlVolume(target: target, detail: detail)
        let download = volume.flatMap { downloads.record(for: $0.id) }
        let activeDownload = download.map { record in
            [.queued, .downloading].contains(record.state)
        } ?? false
        let downloadTitle: LocalizedStringKey = download?.isVerifiedOfflineCopy == true
            ? "downloads.remove.action"
            : activeDownload ? "work.download.pause" : "work.action.download"
        let downloadIcon = activeDownload ? "pause.circle" : "icloud.and.arrow.down"
        let kindleEligible = volume?.files.contains(where: kindleFile) == true
        func action(
            _ id: String,
            _ title: LocalizedStringKey,
            _ icon: String,
            enabled: Bool = true,
            destructive: Bool = false,
            perform: @escaping () -> Void
        ) -> WorkControlAction {
            WorkControlAction(
                id: id,
                title: title,
                systemImage: icon,
                enabled: enabled,
                destructive: destructive,
                perform: perform
            )
        }
        var actions: [WorkControlAction] = []
        if target == .book {
            if canManageSystem {
                actions.append(action("series", "work.control.addSeries", "square.stack.3d.up") {
                    openManagement(.addSeries, volumeID: nil)
                })
            }
            actions.append(action("shelf", "work.control.addShelf", "books.vertical") {
                controlTarget = nil
                openShelfPicker()
            })
            actions.append(action("unread", "work.control.markUnread", "bookmark", enabled: volume != nil) {
                markUnread(volume)
            })
            actions.append(action("download", downloadTitle, downloadIcon, enabled: volume != nil) {
                handleControlDownload(volume, detail: detail)
            })
            if canManageSystem {
                actions.append(action("edit", "work.control.edit", "pencil") { openManagement(.editWork, volumeID: nil) })
                actions.append(action("recognize", "work.control.recognize", "sparkles") { openManagement(.recognize, volumeID: nil) })
                actions.append(action("uploadCover", "management.uploadCover", "photo.badge.plus") { openManagement(.cover, volumeID: nil) })
                actions.append(action("regenerateCover", "management.regenerateCover", "wand.and.stars") { openManagement(.cover, volumeID: nil) })
                if kindleEligible {
                    actions.append(action("kindle", "management.kindle", "paperplane") { openManagement(.kindle, volumeID: volume?.id) })
                }
                actions.append(action("delete", "work.control.delete", "trash", destructive: true) {
                    openManagement(.deleteWork, volumeID: nil)
                })
            }
        } else if let volume {
            actions.append(action("unread", "work.control.markUnread", "bookmark") { markUnread(volume) })
            actions.append(action("download", downloadTitle, downloadIcon) {
                handleControlDownload(volume, detail: detail)
            })
            if canManageSystem {
                actions.append(action("edit", "work.control.edit", "pencil") { openManagement(.editVolume, volumeID: volume.id) })
                actions.append(action("mediaKind", "work.control.changeMediaType", "square.stack.3d.up", enabled: !activeDownload) { openManagement(.mediaKind, volumeID: volume.id) })
                actions.append(action("split", "work.control.split", "arrow.triangle.branch", enabled: !activeDownload) { openManagement(.split, volumeID: volume.id) })
                actions.append(action("move", "work.control.move", "arrow.right", enabled: !activeDownload) { openManagement(.transfer, volumeID: volume.id) })
                if kindleEligible {
                    actions.append(action("kindle", "management.kindle", "paperplane") { openManagement(.kindle, volumeID: volume.id) })
                }
                actions.append(action("delete", "work.control.delete", "trash", enabled: !activeDownload, destructive: true) { openManagement(.deleteVolume, volumeID: volume.id) })
            }
        }
        return actions
    }

    private func controlVolume(target: WorkControlTarget, detail: WorkDetailContent) -> WorkVolume? {
        switch target {
        case .book: selectedVolume(detail)
        case .volume(let id): detail.volumes.first { $0.id == id }
        }
    }

    private func openManagement(_ task: WorkManagementTask, volumeID: String?) {
        controlTarget = nil
        managedVolumeID = volumeID
        managementTask = task
    }

    private func markUnread(_ volume: WorkVolume?) {
        controlTarget = nil
        guard let volume, let managementStore else {
            unavailableFeature = .readingStatus
            return
        }
        managementStore.setReadingStatus(volumeID: volume.id, status: .unread)
    }

    private func handleControlDownload(_ volume: WorkVolume?, detail: WorkDetailContent) {
        controlTarget = nil
        guard let volume else { return }
        if let record = downloads.record(for: volume.id), record.isVerifiedOfflineCopy {
            downloads.remove(record)
        } else {
            handleDownload(volume, detail: detail)
        }
    }

    @ViewBuilder
    private func managementPage(task: WorkManagementTask) -> some View {
        if let managementStore, let detail = currentDetail {
            let volume = managedVolumeID.flatMap { id in detail.volumes.first { $0.id == id } }
            WorkManagementView(
                store: managementStore,
                task: task,
                detail: detail,
                volume: volume,
                downloadAction: { selectedVolume in
                    handleDownload(selectedVolume, detail: detail)
                    managementTask = nil
                },
                removeDownload: { selectedVolume in
                    if let record = downloads.record(for: selectedVolume.id) {
                        downloads.remove(record)
                    }
                    managementTask = nil
                },
                chooseCover: { importsCover = true },
                workCover: AnyView(cover(detail)),
                downloadForVolume: { downloads.record(for: $0) },
                onManagedVolumeChange: { managedVolumeID = $0 }
            )
        }
    }

    private func handleManagementCompletion(_ action: WorkManagementStore.Action?) {
        guard let action, let managementStore else { return }
        let detail = currentDetail
        switch action {
        case .workDeleted:
            detail?.volumes.forEach { downloads.remove(volumeID: $0.id) }
            onWorkDeleted()
        case .volumeDeleted:
            if let managedVolumeID { downloads.remove(volumeID: managedVolumeID) }
        case .volumeSplit:
            rewriteCompletedDownload(move: .split, store: managementStore)
        case .volumeTransferred:
            rewriteCompletedDownload(move: .transfer, store: managementStore)
        case .volumeReclassified:
            break
        default: break
        }
        managementTask = nil
        if [.volumeReclassified, .volumeSplit, .volumeTransferred, .volumeDeleted].contains(action) {
            managedVolumeID = nil
        }
        managementStore.consumeCompletion()
        if action != .workDeleted { store.load() }
    }

    private func rewriteCompletedDownload(
        move: DownloadStructuralMove,
        store: WorkManagementStore
    ) {
        guard let pending = store.pendingOwnership,
              let outcome = store.lastOutcome,
              let record = downloads.record(for: pending.volumeID),
              record.isVerifiedOfflineCopy,
              let rewrite = DownloadOwnershipRewrite.forMove(
                  move,
                  targetWorkID: outcome.targetWorkId,
                  targetVersionID: outcome.targetVersionId,
                  targetWorkTitle: pending.workTitle,
                  targetWorkAuthor: pending.workAuthor
              )
        else { return }
        downloads.rehomeCompleted(
            volumeID: pending.volumeID,
            targetWorkID: rewrite.targetWorkID,
            targetWorkTitle: rewrite.targetWorkTitle,
            targetWorkAuthor: rewrite.targetWorkAuthor,
            targetVersionID: rewrite.targetVersionID,
            targetVersionSourceKey: rewrite.targetVersionSourceKey,
            targetVersionSourceName: rewrite.targetVersionSourceName,
            targetVersionCompleted: rewrite.targetVersionCompleted
        )
    }

    private func openShelfPicker() {
        showsShelfPicker = true
        isLoadingShelves = true
        shelfError = false
        Task {
            do {
                let loaded = try await shelfClient.fetchShelves(context: context, workID: store.workIDValue)
                shelves = loaded
                selectedShelfIDs = Set(loaded.filter(\.containsWork).map(\.id))
                isLoadingShelves = false
            } catch {
                isLoadingShelves = false
                shelfError = true
            }
        }
    }

    @ViewBuilder
    private var shelfPicker: some View {
        NavigationStack {
            Group {
                if isLoadingShelves {
                    ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if shelfError {
                    ContentStatusView(
                        systemImage: "wifi.exclamationmark",
                        title: "work.shelf.error.title",
                        message: "work.shelf.error.message"
                    )
                } else if shelves.isEmpty {
                    ContentStatusView(
                        systemImage: "rectangle.split.2x1",
                        title: "work.shelf.empty.title",
                        message: "work.shelf.empty.message"
                    )
                } else {
                    List(shelves) { shelf in
                        Button {
                            if !selectedShelfIDs.insert(shelf.id).inserted { selectedShelfIDs.remove(shelf.id) }
                        } label: {
                            HStack {
                                Text(shelf.name).foregroundStyle(theme.textPrimary)
                                Spacer()
                                if selectedShelfIDs.contains(shelf.id) {
                                    Image(systemName: "checkmark").foregroundStyle(theme.actionAccent)
                                }
                            }
                            .frame(minHeight: .iosMinimumTouchTarget)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .disabled(isSavingShelves)
                    }
                }
            }
            .navigationTitle("work.action.shelf")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("common.cancel") { showsShelfPicker = false }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("common.save") { saveShelves() }
                        .disabled(isLoadingShelves || isSavingShelves || shelfError || shelves.isEmpty)
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private func saveShelves() {
        let original = Set(shelves.filter(\.containsWork).map(\.id))
        let additions = selectedShelfIDs.subtracting(original)
        let removals = original.subtracting(selectedShelfIDs)
        isSavingShelves = true
        Task {
            do {
                for shelfID in additions {
                    try await shelfClient.updateShelf(context: context, workID: store.workIDValue, shelfID: shelfID, add: true)
                }
                for shelfID in removals {
                    try await shelfClient.updateShelf(context: context, workID: store.workIDValue, shelfID: shelfID, add: false)
                }
                shelves = shelves.map { ShelfOption(id: $0.id, name: $0.name, containsWork: selectedShelfIDs.contains($0.id)) }
                isSavingShelves = false
                showsShelfPicker = false
            } catch {
                isSavingShelves = false
                shelfError = true
            }
        }
    }

    private func requestReaderAccess(detail: WorkDetailContent) {
        guard let volume = selectedVolume(detail) else { return }
        if let handoff = ManagedReaderAccessPolicy.verifiedLocalHandoff(
            record: downloads.record(for: volume.id),
            volumeID: volume.id
        ) {
            openReader(handoff)
            return
        }
        prepareReader(ReaderPreparationRequest(
            context: context,
            work: detail.work,
            volume: volume,
            mediaKind: volume.libraryMediaKind
        ))
    }

    private func requestReaderAccessForSelectedVolume() {
        guard case .ready(let detail, _) = store.state else { return }
        requestReaderAccess(detail: detail)
    }

    private func enqueueSelectedVolume() {
        guard case .ready(let detail, _) = store.state,
              let volume = selectedVolume(detail) else { return }
        downloads.enqueue(work: detail.work, volume: volume, mediaKind: volume.libraryMediaKind)
    }

    private func handleDownload(_ volume: WorkVolume, detail: WorkDetailContent) {
        if let record = downloads.record(for: volume.id) {
            switch record.state {
            case .downloading, .queued: downloads.pause(record)
            case .paused, .failedRetryable, .failedTerminal: downloads.resume(record)
            case .completed: break
            }
        } else {
            downloads.enqueue(work: detail.work, volume: volume, mediaKind: volume.libraryMediaKind)
        }
    }

    private func downloadSystemImage(volumeID: String) -> String {
        guard let record = downloads.record(for: volumeID) else { return "icloud.and.arrow.down" }
        switch record.state {
        case .queued, .downloading: return "pause.circle"
        case .paused, .failedRetryable, .failedTerminal: return "arrow.clockwise.circle"
        case .completed:
            return record.isVerifiedOfflineCopy ? "checkmark.circle.fill" : "exclamationmark.circle"
        }
    }

    private func downloadForeground(volumeID: String) -> Color {
        downloads.record(for: volumeID)?.isVerifiedOfflineCopy == true
            ? theme.brandAccent
            : theme.textSecondary
    }

    private func downloadAccessibilityLabel(volumeID: String) -> LocalizedStringKey {
        guard let record = downloads.record(for: volumeID) else { return "work.volume.download.action" }
        switch record.state {
        case .queued, .downloading: return "work.volume.download.pause"
        case .paused, .failedRetryable, .failedTerminal: return "work.volume.download.retry"
        case .completed: return "work.volume.download.completed"
        }
    }

    private var readerAccessErrorMessage: LocalizedStringKey {
        switch readerAccessErrorCode {
        case "DOWNLOAD_TRANSPORT_UNAVAILABLE": "downloads.error.transportUnavailable"
        case "DOWNLOAD_UNAUTHORIZED": "downloads.error.unauthorized"
        case "DOWNLOAD_CONTENT_UNAVAILABLE": "downloads.error.inaccessible"
        default: "reader.handoff.error.message"
        }
    }
}

private struct VolumeCoverProgressView: View {
    let progress: Double
    @Environment(\.appTheme) private var theme

    var body: some View {
        GeometryReader { geometry in
            let clamped = min(100, max(0, progress))
            ZStack(alignment: .leading) {
                Capsule().fill(theme.divider.opacity(0.72)).frame(height: 2)
                Capsule()
                    .fill(theme.brandAccent)
                    .frame(width: geometry.size.width * clamped / 100, height: 2)
                if clamped >= 100 {
                    Image(systemName: "checkmark")
                        .font(.system(size: 7, weight: .bold))
                        .foregroundStyle(theme.onAction)
                        .frame(width: 12, height: 12)
                        .background(theme.brandAccent)
                        .clipShape(Circle())
                        .frame(maxWidth: .infinity, alignment: .trailing)
                }
            }
            .frame(maxHeight: .infinity, alignment: .center)
        }
        .frame(height: 12)
        .accessibilityHidden(true)
    }
}

private struct FlowTags: View {
    let tags: [String]
    @Environment(\.appTheme) private var theme

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: .spaceHalf) { tagViews }
            VStack(alignment: .leading, spacing: .spaceHalf) { tagViews }
        }
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private var tagViews: some View {
        ForEach(tags.prefix(3), id: \.self) { tag in
            Text(tag)
                .appTextStyle(.label)
                .foregroundStyle(theme.textSecondary)
                .padding(.horizontal, .space1Half)
                .padding(.vertical, .spaceHalf)
                .background(theme.surfaceRaised, in: RoundedRectangle(cornerRadius: 3))
        }
    }
}

private enum UnavailableWorkFeature: Identifiable {
    case reader
    case editing
    case cover
    case download
    case readingStatus

    var id: Self { self }

    var message: LocalizedStringKey {
        switch self {
        case .reader: "work.reader.unavailable.message"
        case .editing: "work.action.edit.unavailable"
        case .cover: "work.action.setCover.unavailable"
        case .download: "work.action.download.unavailable"
        case .readingStatus: "work.action.readingStatus.unavailable"
        }
    }
}

private extension LibraryMediaKind {
    var title: LocalizedStringKey {
        switch self {
        case .ebook: "library.media.ebook"
        case .comic: "library.media.comic"
        case .audiobook: "library.media.audiobook"
        }
    }

    var workDetailTitle: String {
        switch self {
        case .ebook: String(localized: "library.media.ebook")
        case .comic: String(localized: "library.media.comic")
        case .audiobook: String(localized: "library.media.audiobook")
        }
    }
}

private extension LibraryReadingStatus {
    static let manualChoices: [LibraryReadingStatus] = [.unread, .finished]

    var title: LocalizedStringKey {
        switch self {
        case .unread: "work.status.unread"
        case .reading: "work.status.reading"
        case .finished: "work.status.finished"
        }
    }

    var sharedValue: ErmaoShared.ManagedReadingStatus? {
        switch self {
        case .unread: .unread
        case .reading: nil
        case .finished: .finished
        }
    }
}
