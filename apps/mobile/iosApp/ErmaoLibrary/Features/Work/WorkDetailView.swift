import SwiftUI

struct WorkReaderSelection: Equatable, Sendable {
    let workID: String
    let volumeID: String
    let displayTitle: String
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
    @Environment(\.appTheme) private var theme
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(
        context: ContentRequestContext,
        client: any ContentClient,
        shelfClient: any ShelfClient,
        cache: LibraryCacheStore,
        downloads: DownloadCenterStore,
        workID: String,
        onUnauthorized: @escaping @MainActor () -> Void,
        openFacet: @escaping (FacetKind, String) -> Void,
        openDownloads: @escaping () -> Void,
        openReader: @escaping (ReaderHandoff) -> Void,
        prepareReader: @escaping (ReaderPreparationRequest) -> Void
    ) {
        self.context = context
        self.client = client
        self.shelfClient = shelfClient
        self.cache = cache
        self.downloads = downloads
        self.openFacet = openFacet
        self.openDownloads = openDownloads
        self.openReader = openReader
        self.prepareReader = prepareReader
        _store = StateObject(
            wrappedValue: WorkDetailStore(
                context: context,
                client: client,
                cache: cache,
                workID: workID,
                onUnauthorized: onUnauthorized
            )
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
        .toolbar { overflowMenu }
        .sheet(isPresented: $showsShelfPicker) { shelfPicker }
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
        .appCanvas()
        .task { store.load() }
        .onAppear { store.refreshIfLoaded() }
    }

    @ToolbarContentBuilder
    private var overflowMenu: some ToolbarContent {
        ToolbarItem(placement: .topBarTrailing) {
            Menu {
                Button("common.refresh", systemImage: "arrow.clockwise") { store.load() }
                Divider()
                Button("work.reader.continue.action", systemImage: "book") {
                    requestReaderAccessForSelectedVolume()
                }
                Button("work.action.edit", systemImage: "pencil") {
                    unavailableFeature = .editing
                }
                Button("work.action.setCover", systemImage: "photo") {
                    unavailableFeature = .cover
                }
                Button("work.action.download", systemImage: "icloud.and.arrow.down") {
                    enqueueSelectedVolume()
                }
                Menu("work.action.readingStatus", systemImage: "chart.pie") {
                    ForEach(LibraryReadingStatus.allCases, id: \.self) { status in
                        Button(status.title) { unavailableFeature = .readingStatus }
                    }
                }
            } label: {
                Image(systemName: "ellipsis")
            }
            .accessibilityLabel(Text("common.more"))
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
        case .ready(let detail, let cached):
            readyContent(detail, isCached: cached)
        }
    }

    private func readyContent(_ detail: WorkDetailContent, isCached: Bool) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            if isCached {
                Label("library.offline.cached", systemImage: "wifi.slash")
                    .appTextStyle(.caption)
                    .foregroundStyle(theme.textSecondary)
                    .padding(.bottom, .space2)
            }

            hero(detail)
                .padding(.top, .spaceHalf)
                .padding(.bottom, .space2)

            progressSummary(detail)
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
        if dynamicTypeSize.isAccessibilitySize {
            VStack(alignment: .leading, spacing: .space1Half) {
                cover(detail).frame(width: 124)
                identity(detail)
            }
        } else {
            HStack(alignment: .top, spacing: .space2) {
                cover(detail).frame(width: 128)
                identity(detail)
                    .frame(height: 192, alignment: .top)
            }
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
        VStack(alignment: .leading, spacing: .spaceHalf) {
            Text(detail.work.title)
                .appTextStyle(.title)
                .fixedSize(horizontal: false, vertical: true)

            if detail.authorFacets.isEmpty {
                Text(detail.work.author)
                    .appTextStyle(.body)
                    .foregroundStyle(theme.textSecondary)
            } else {
                ForEach(detail.authorFacets, id: \.id) { author in
                    facetButton(author, kind: .author)
                }
            }

            let format = detail.volumes.first?.formatLabel.lowercased()
            let chips = [format].compactMap { $0 } + detail.tags
            if !chips.isEmpty {
                FlowTags(tags: chips)
            }

            if let series = detail.seriesFacet {
                Spacer(minLength: .spaceHalf)
                facetButton(series, kind: .series)
            }
        }
    }

    private func facetButton(_ facet: FacetIdentity, kind: FacetKind) -> some View {
        Button {
            openFacet(kind, facet.id)
        } label: {
            Text(facet.name)
                .underline(kind == .series, color: kind == .series ? theme.actionAccent : nil)
            .frame(
                minHeight: .iosMinimumTouchTarget,
                alignment: kind == .series ? .bottomLeading : .topLeading
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .appTextStyle(.label)
        .foregroundStyle(kind == .series ? theme.actionAccent : theme.textSecondary)
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
        return HStack(spacing: .space1Half) {
            Button { openShelfPicker() } label: {
                Label("work.action.shelf", systemImage: "bookmark")
                    .appTextStyle(.button)
                    .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget)
            }
            .buttonStyle(.borderedProminent)
            .buttonBorderShape(.roundedRectangle(radius: CGFloat(GeneratedDesignTokens.Radii.control)))
            .tint(theme.accentSoft)
            .foregroundStyle(theme.actionAccent)

            PrimaryActionButton(
                detail.readingStatus == .reading ? "work.reader.continue.action" : "work.reader.start.action",
                isDisabled: selected == nil || selected?.isReadable == false,
                action: { requestReaderAccess(detail: detail) }
            )
        }
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
                    Label(
                        isDescriptionExpanded ? "work.description.collapse" : "work.description.expand",
                        systemImage: isDescriptionExpanded ? "chevron.up" : "chevron.down"
                    )
                    .appTextStyle(.label)
                }
                .buttonStyle(.plain)
                .foregroundStyle(theme.actionAccent)
                .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget, alignment: .trailing)
            }
            .padding(.space2)
            .background(theme.surface)
            .clipShape(RoundedRectangle(cornerRadius: CGFloat(GeneratedDesignTokens.Radii.task)))
        }
    }

    private func hasDescription(_ detail: WorkDetailContent) -> Bool {
        normalizedDescription(detail) != nil
    }

    private func normalizedDescription(_ detail: WorkDetailContent) -> String? {
        guard let value = detail.description?.trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty else { return nil }
        return value
    }

    private func mediaSection(_ detail: WorkDetailContent) -> some View {
        VStack(alignment: .leading, spacing: .space2) {
            mediaPicker(detail)
            if usesChapterFallback(detail) {
                chapterSection(detail)
            } else {
                volumeSection(detail)
            }
        }
    }

    @ViewBuilder
    private func mediaPicker(_ detail: WorkDetailContent) -> some View {
        if detail.availableMediaKinds.count > 1 {
            Picker(
                "work.media.title",
                selection: Binding(
                    get: { detail.selectedMediaKind ?? detail.availableMediaKinds.first ?? .ebook },
                    set: { store.load(mediaKind: $0) }
                )
            ) {
                ForEach(detail.availableMediaKinds, id: \.self) { kind in
                    Text(kind.title).tag(kind)
                }
            }
            .pickerStyle(.segmented)
            .tint(theme.brandAccent)
        }
    }

    private func usesChapterFallback(_ detail: WorkDetailContent) -> Bool {
        detail.selectedMediaKind == .ebook && detail.volumes.count == 1 && !detail.chapters.isEmpty
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
                HStack {
                    Text("work.volumes.all").appTextStyle(.sectionTitle)
                    Spacer()
                    Text(String(format: String(localized: "work.volumes.count.format"), detail.volumes.count))
                        .appTextStyle(.label)
                        .foregroundStyle(theme.textSecondary)
                }
                ScrollView(.horizontal, showsIndicators: false) {
                    LazyHStack(alignment: .top, spacing: .space1Half) {
                        ForEach(Array(detail.volumes.enumerated()), id: \.element.id) { position, volume in
                            volumeCoverItem(volume, position: position, detail: detail)
                                .frame(width: dynamicTypeSize.isAccessibilitySize ? 160 : 136)
                        }
                    }
                }
                if !detail.chapters.isEmpty {
                    chapterSection(detail)
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
                    store.load(mediaKind: detail.selectedMediaKind, volumeID: volume.id)
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
                .disabled(volume.isReadable == false)
                .accessibilityElement(children: .ignore)
                .accessibilityIdentifier("work.volume.\(volume.id)")
                .accessibilityLabel(Text(volumeAccessibilityLabel(volume, index: index)))
                .accessibilityValue(volumeAccessibilityValue(volume))
                .accessibilityAddTraits(volume.isSelected ? .isSelected : [])

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
                        .frame(width: 32, height: 32)
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

    private func chapterSection(_ detail: WorkDetailContent) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("work.directory.title").appTextStyle(.sectionTitle)
                Spacer()
                Text(String(format: String(localized: "work.chapters.count.format"), detail.chapters.count))
                    .appTextStyle(.label)
                    .foregroundStyle(theme.textSecondary)
            }
            .padding(.bottom, .space1)

            ForEach(detail.chapters) { chapter in
                Divider()
                HStack(spacing: .space1) {
                    Rectangle()
                        .fill(chapter.isCurrent ? theme.brandAccent : Color.clear)
                        .frame(width: 3)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: .spaceHalf) {
                        Text(chapter.title)
                            .appTextStyle(.headline)
                            .lineLimit(2)
                        if let progress = chapter.progress {
                            Text(progressLabel(progress))
                                .appTextStyle(.caption)
                                .foregroundStyle(theme.textSecondary)
                                .monospacedDigit()
                        }
                    }
                    Spacer(minLength: .space1)
                    if chapter.state != .unread {
                        Group {
                            if chapter.state == .current {
                                Text("work.chapter.current")
                            } else {
                                Text("work.chapter.read")
                            }
                        }
                        .appTextStyle(.label)
                        .foregroundStyle(chapter.state == .current ? theme.actionAccent : theme.textSecondary)
                    } else {
                        Image(systemName: "chevron.forward")
                            .foregroundStyle(theme.textTertiary)
                    }
                }
                .frame(minHeight: 64)
            }
            Divider()
        }
        .padding(.space2)
        .background(theme.surface)
        .clipShape(RoundedRectangle(cornerRadius: CGFloat(GeneratedDesignTokens.Radii.task)))
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
        guard let volume = selectedVolume(detail), let mediaKind = detail.selectedMediaKind else { return }
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
            mediaKind: mediaKind
        ))
    }

    private func requestReaderAccessForSelectedVolume() {
        guard case .ready(let detail, _) = store.state else { return }
        requestReaderAccess(detail: detail)
    }

    private func enqueueSelectedVolume() {
        guard case .ready(let detail, _) = store.state,
              let volume = selectedVolume(detail),
              let mediaKind = detail.selectedMediaKind else { return }
        downloads.enqueue(work: detail.work, volume: volume, mediaKind: mediaKind)
    }

    private func handleDownload(_ volume: WorkVolume, detail: WorkDetailContent) {
        guard let mediaKind = detail.selectedMediaKind else { return }
        if let record = downloads.record(for: volume.id) {
            switch record.state {
            case .downloading, .queued: downloads.pause(record)
            case .paused, .failedRetryable, .failedTerminal: downloads.resume(record)
            case .completed: break
            }
        } else {
            downloads.enqueue(work: detail.work, volume: volume, mediaKind: mediaKind)
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
                .overlay {
                    RoundedRectangle(cornerRadius: 3)
                        .stroke(theme.divider)
                }
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
    static let allCases: [LibraryReadingStatus] = [.unread, .reading, .finished]

    var title: LocalizedStringKey {
        switch self {
        case .unread: "work.status.unread"
        case .reading: "work.status.reading"
        case .finished: "work.status.finished"
        }
    }
}
