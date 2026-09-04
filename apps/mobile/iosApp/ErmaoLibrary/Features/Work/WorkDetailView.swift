import SwiftUI
@preconcurrency import ErmaoShared

enum WorkDescriptionPlainText {
    private static let blockTags: Set<String> = [
        "article", "blockquote", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6",
        "li", "ol", "p", "section", "table", "tr", "ul",
    ]
    private static let suppressedTags: Set<String> = ["script", "style"]

    static func normalize(_ rawValue: String?) -> String? {
        guard let rawValue = rawValue?.trimmingCharacters(in: .whitespacesAndNewlines),
              !rawValue.isEmpty else { return nil }
        let value = decodeEntities(in: textOutsideMarkup(rawValue))
            .replacingOccurrences(of: "\0", with: "")
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
            .replacingOccurrences(of: #"[\t ]+"#, with: " ", options: .regularExpression)
            .replacingOccurrences(of: #"\n{3,}"#, with: "\n\n", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }

    private static func textOutsideMarkup(_ input: String) -> String {
        var result = ""
        var cursor = input.startIndex
        var suppressedTag: String?
        while cursor < input.endIndex {
            guard input[cursor] == "<",
                  let close = input[cursor...].firstIndex(of: ">"),
                  input.distance(from: cursor, to: close) <= 4_096
            else {
                if suppressedTag == nil { result.append(input[cursor]) }
                cursor = input.index(after: cursor)
                continue
            }
            let tagBody = input[input.index(after: cursor) ..< close]
                .trimmingCharacters(in: .whitespacesAndNewlines)
            let isClosing = tagBody.hasPrefix("/")
            let nameStart = isClosing ? tagBody.dropFirst() : tagBody[...]
            let name = nameStart.prefix { $0.isLetter || $0.isNumber }.lowercased()
            if suppressedTags.contains(name) {
                if isClosing {
                    if suppressedTag == name { suppressedTag = nil }
                } else if !tagBody.hasSuffix("/") {
                    suppressedTag = name
                }
            } else if suppressedTag == nil, blockTags.contains(name) {
                result.append("\n")
            }
            cursor = input.index(after: close)
        }
        return result
    }

    private static func decodeEntities(in input: String) -> String {
        var result = ""
        var cursor = input.startIndex
        while cursor < input.endIndex {
            guard input[cursor] == "&" else {
                result.append(input[cursor])
                cursor = input.index(after: cursor)
                continue
            }
            let searchEnd = input.index(cursor, offsetBy: 18, limitedBy: input.endIndex) ?? input.endIndex
            guard let semicolon = input[cursor ..< searchEnd].firstIndex(of: ";") else {
                result.append("&")
                cursor = input.index(after: cursor)
                continue
            }
            let name = String(input[input.index(after: cursor) ..< semicolon])
            guard let decoded = decodeEntity(name) else {
                result.append(contentsOf: input[cursor ... semicolon])
                cursor = input.index(after: semicolon)
                continue
            }
            result.append(decoded)
            cursor = input.index(after: semicolon)
        }
        return result
    }

    private static func decodeEntity(_ name: String) -> Character? {
        let named: [String: Character] = [
            "amp": "&", "apos": "'", "gt": ">", "lt": "<", "nbsp": " ", "quot": "\"",
        ]
        if let value = named[name.lowercased()] { return value }
        let numericValue: UInt32?
        if name.lowercased().hasPrefix("#x") {
            numericValue = UInt32(name.dropFirst(2), radix: 16)
        } else if name.hasPrefix("#") {
            numericValue = UInt32(name.dropFirst())
        } else {
            numericValue = nil
        }
        guard let numericValue, let scalar = Unicode.Scalar(numericValue) else { return nil }
        return Character(scalar)
    }
}

struct WorkReaderSelection: Equatable, Sendable {
    let bookID: String
    let resourceID: String
    let displayTitle: String
}

private enum WorkControlTarget: Equatable {
    case book
    case resource(String)
}

private struct WorkControlAction: Identifiable {
    let id: String
    let title: LocalizedStringKey
    let systemImage: String
    let enabled: Bool
    let destructive: Bool
    let perform: () -> Void
}

private enum WorkDetailSheet: Identifiable {
    case shelves
    case downloads

    var id: String {
        switch self {
        case .shelves: "shelves"
        case .downloads: "downloads"
        }
    }
}

private struct WorkDetailFeedback: Identifiable, Equatable {
    let id = UUID()
    let message: String
    let isError: Bool
}

// Keep the existing chapter, page, and track preview implementation available
// while the product surface is temporarily hidden.
private let resourcePreviewIsVisible = false

struct WorkDetailView: View {
    let context: ContentRequestContext
    let client: any ContentClient
    let shelfClient: any ShelfClient
    let cache: AuthenticatedCoverCache
    @ObservedObject var downloads: DownloadCenterStore
    let openFacet: (FacetKind, String) -> Void
    let openDownloads: () -> Void
    let openReader: (ReaderHandoff) -> Void
    let managementRepository: (any ErmaoShared.WorkManagementRepository)?
    let canManageSystem: Bool
    let openContent: (BookContentDestination) -> Void

    @StateObject private var store: BookDetailStore
    @State private var activeSheet: WorkDetailSheet?
    @State private var shelves: [ShelfOption] = []
    @State private var selectedShelfIDs: Set<String> = []
    @State private var shelfRequestGeneration = UUID()
    @State private var isLoadingShelves = false
    @State private var isSavingShelves = false
    @State private var shelfError = false
    @SceneStorage private var isDescriptionExpanded: Bool
    @SceneStorage private var savedScrollOffset: Double
    @SceneStorage private var savedAnchorID: String
    @SceneStorage private var savedAnchorOffset: Double
    @State private var contentAnchorFrames: [String: CGRect] = [:]
    @SceneStorage private var savedPageState: String
    @State private var unavailableFeature: UnavailableWorkFeature?
    @State private var readerAccessErrorCode: String?
    @StateObject private var managementHolder: WorkManagementStoreHolder
    @State private var pendingReadingStatusTarget: WorkControlTarget?
    @State private var feedback: WorkDetailFeedback?
    @State private var coverRefreshToken = 0
    @State private var downloadMenuRecord: ManagedDownloadRecord?
    @State private var pendingDownloadRemoval: ManagedDownloadRecord?
    @State private var fullMetadataPath: String?
    @Environment(\.managementRevision) private var managementRevision
    @Environment(\.managementChange) private var managementChange
    @Environment(\.appTheme) private var theme
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.locale) private var locale
    @Environment(\.dismiss) private var dismiss
    @Environment(\.audioPlaybackRuntime) private var audioPlaybackRuntime

    init(
        context: ContentRequestContext,
        client: any ContentClient,
        shelfClient: any ShelfClient,
        cache: AuthenticatedCoverCache,
        downloads: DownloadCenterStore,
        managementRepository: (any ErmaoShared.WorkManagementRepository)? = nil,
        canManageSystem: Bool = false,
        bookID: String,
        destination: BookContentDestination = .root,
        openContent: @escaping (BookContentDestination) -> Void,
        onUnauthorized: @escaping @MainActor () -> Void,
        openFacet: @escaping (FacetKind, String) -> Void,
        openDownloads: @escaping () -> Void,
        openReader: @escaping (ReaderHandoff) -> Void
    ) {
        self.context = context
        self.client = client
        self.shelfClient = shelfClient
        self.cache = cache
        self.downloads = downloads
        self.managementRepository = managementRepository
        self.canManageSystem = canManageSystem
        let restorationKey = "book-content.\(context.namespaceKey).\(bookID).\(destination.restorationKey)"
        _isDescriptionExpanded = SceneStorage(wrappedValue: false, restorationKey + ".description")
        _savedScrollOffset = SceneStorage(wrappedValue: 0, restorationKey + ".scroll")
        _savedAnchorID = SceneStorage(wrappedValue: "", restorationKey + ".anchor")
        _savedAnchorOffset = SceneStorage(wrappedValue: 0, restorationKey + ".anchorOffset")
        _savedPageState = SceneStorage(wrappedValue: "", restorationKey + ".state")
        self.openFacet = openFacet
        self.openDownloads = openDownloads
        self.openReader = openReader
        self.openContent = openContent
        _store = StateObject(
            wrappedValue: BookDetailStore(
                context: context,
                client: client,
                bookID: bookID,
                destination: destination,
                onUnauthorized: onUnauthorized
            )
        )
        _managementHolder = StateObject(
            wrappedValue: WorkManagementStoreHolder(
                store: managementRepository.map { repository in
                WorkManagementStore(repository: repository, context: context, bookID: bookID)
                }
            )
        )
    }

    private var managementStore: WorkManagementStore? { managementHolder.store }

    var body: some View {
        observedScreen
    }

    private var baseScreen: some View {
        BookDetailScrollView(offset: $savedScrollOffset, anchorID: $savedAnchorID, anchorOffset: $savedAnchorOffset, anchors: contentAnchorFrames, ready: currentDetail != nil && !store.isLoadingContentBrowser) {
            AnyView(content)
                .padding(.horizontal, .space2)
                .padding(.bottom, .space4)
                .environment(\.appTheme, theme)
                .environment(\.locale, locale)
                .environment(\.dynamicTypeSize, dynamicTypeSize)
                .coordinateSpace(name: "book-content-scroll")
                .onPreferenceChange(BookContentAnchorFrames.self) { contentAnchorFrames = $0 }
        }
        .accessibilityIdentifier("work.detail.screen")
        .safeAreaInset(edge: .bottom, spacing: 0) {
            Color.clear.frame(height: .space2)
        }
        .navigationTitle(currentDetail.map { pageDetail($0).book.title } ?? String(localized: "work.detail.title"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.hidden, for: .navigationBar)
        .toolbar {
            if currentDetail != nil, !store.isBookRoot, store.selectedResourceID == nil, store.contentsPage != nil {
                ToolbarItem(placement: .topBarTrailing) {
                    directoryControlMenu()
                }
            }
        }
    }

    private var sheetScreen: some View {
        baseScreen
        .sheet(item: $activeSheet) { sheet in
            switch sheet {
            case .shelves:
                shelfPicker
                    .interactiveDismissDisabled(isLoadingShelves || isSavingShelves)
            case .downloads:
                if let detail = currentDetail {
                    MultiDownloadSheet(
                        context: context,
                        client: client,
                        detail: detail,
                        rootSourceNodeID: store.contentsPage?.currentSourceNodeID,
                        downloads: downloads,
                        openReader: openReader,
                        onDismiss: { activeSheet = nil },
                        onCompleted: { succeeded, failed in
                            if failed == 0 {
                                showFeedback(
                                    String(format: String(localized: "work.multiDownload.completed"), succeeded),
                                    isError: false
                                )
                            } else {
                                showFeedback(
                                    String(format: String(localized: "work.multiDownload.partial"), succeeded, failed),
                                    isError: true
                                )
                            }
                        }
                    )
                    .presentationDetents([.large])
                    .presentationDragIndicator(.visible)
                }
            }
        }
    }

    private var availabilityDialogScreen: some View {
        sheetScreen
        .confirmationDialog(
            "work.unavailable.title",
            isPresented: unavailableFeatureIsPresented,
            titleVisibility: .visible,
            presenting: unavailableFeature
        ) { _ in
            Button("common.done", role: .cancel) { unavailableFeature = nil }
        } message: { feature in
            Text(feature.message)
        }
        .alert(
            "reader.handoff.error.title",
            isPresented: readerAccessErrorIsPresented
        ) {
            Button("common.done", role: .cancel) { readerAccessErrorCode = nil }
        } message: {
            Text(readerAccessErrorMessage)
        }
        .alert(
            "work.metadata.filePath.fullTitle",
            isPresented: fullMetadataPathIsPresented
        ) {
            Button("common.done", role: .cancel) { fullMetadataPath = nil }
        } message: {
            Text(fullMetadataPath ?? "")
        }
    }

    private var downloadDialogScreen: some View {
        availabilityDialogScreen
        .confirmationDialog(
            "work.download.manage",
            isPresented: downloadMenuIsPresented,
            titleVisibility: .visible,
            presenting: downloadMenuRecord
        ) { record in
            Button("work.download.openOffline") {
                downloadMenuRecord = nil
                openOffline(record)
            }
            Button("downloads.remove.action", role: .destructive) {
                downloadMenuRecord = nil
                pendingDownloadRemoval = record
            }
            Button("common.cancel", role: .cancel) { downloadMenuRecord = nil }
        } message: { record in
            Text(record.resourceTitle)
        }
        .confirmationDialog(
            "downloads.remove.confirm.title",
            isPresented: pendingDownloadRemovalIsPresented,
            titleVisibility: .visible,
            presenting: pendingDownloadRemoval
        ) { record in
            Button("downloads.remove.action", role: .destructive) {
                downloads.remove(record)
                pendingDownloadRemoval = nil
            }
            Button("common.cancel", role: .cancel) { pendingDownloadRemoval = nil }
        } message: { _ in
            Text("downloads.remove.confirm.message")
        }
    }

    private var observedScreen: some View {
        downloadDialogScreen
        .overlay(alignment: .bottom) { feedbackBanner }
        .appCanvas()
        .onChange(of: managementRevision, initial: true) { _, _ in
            guard let change = managementChange, change.bookID == store.bookIDValue else { return }
            if change.deleted, let resourceID = change.resourceID, resourceID == store.selectedResourceID { dismiss() }
            else if change.readingStatusChanged { store.refreshAfterBookReadingStatusChange() }
            else { store.refreshIfLoaded() }
        }
        .task {
            if savedPageState.utf8.count < 4096,
               let restored = try? JSONDecoder().decode(BookContentViewState.self, from: Data(savedPageState.utf8)) {
                store.restoreViewState(restored)
            }
            store.loadIfNeeded()
        }
        .onAppear { store.refreshIfLoaded() }
        .onChange(of: store.viewState) { _, value in
            if let encoded = try? JSONEncoder().encode(value), let payload = String(data: encoded, encoding: .utf8) {
                savedPageState = payload
            }
        }
        .onChange(of: managementStore?.completedAction) { _, action in
            handleManagementCompletion(action)
        }
        .onChange(of: managementStore?.errorCode, initial: false, handleManagementErrorChange)
        .onChange(of: downloads.storageErrorCode, initial: false, handleStorageErrorChange)
        .onChange(of: selectedDownloadErrorCode, initial: false, handleSelectedDownloadErrorChange)
    }

    private var unavailableFeatureIsPresented: Binding<Bool> {
        Binding(
            get: { unavailableFeature != nil },
            set: { if !$0 { unavailableFeature = nil } }
        )
    }

    private var readerAccessErrorIsPresented: Binding<Bool> {
        Binding(
            get: { readerAccessErrorCode != nil },
            set: { if !$0 { readerAccessErrorCode = nil } }
        )
    }

    private var downloadMenuIsPresented: Binding<Bool> {
        Binding(
            get: { downloadMenuRecord != nil },
            set: { if !$0 { downloadMenuRecord = nil } }
        )
    }

    private var pendingDownloadRemovalIsPresented: Binding<Bool> {
        Binding(
            get: { pendingDownloadRemoval != nil },
            set: { if !$0 { pendingDownloadRemoval = nil } }
        )
    }

    private var fullMetadataPathIsPresented: Binding<Bool> {
        Binding(
            get: { fullMetadataPath != nil },
            set: { if !$0 { fullMetadataPath = nil } }
        )
    }

    private func handleManagementErrorChange(_ oldValue: String?, _ code: String?) {
        guard let code else { return }
        pendingReadingStatusTarget = nil
        let format = String(localized: "management.failed.format")
        let message = String(format: format, code)
        showFeedback(message, isError: true)
    }

    private func handleStorageErrorChange(_ oldValue: String?, _ code: String?) {
        handleSelectedDownloadError(code)
    }

    private func handleSelectedDownloadErrorChange(_ oldValue: String?, _ code: String?) {
        handleSelectedDownloadError(code)
    }

    private func handleSelectedDownloadError(_ code: String?) {
        guard let code else { return }
        showFeedback(downloadFailureMessage(code), isError: true)
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
        case .ready(let detail):
            if (store.destination == .root && store.contentsPage == nil)
                || (store.selectedResourceID != nil && selectedResource(detail) == nil) {
                if store.contentBrowserFailed {
                    contentBrowserRetry
                } else {
                    HStack { Spacer(); ProgressView(); Spacer() }.frame(minHeight: 420)
                }
            } else {
                readyContent(detail)
            }
        }
    }

    @ViewBuilder
    private func readyContent(_ detail: BookDetailContent) -> some View {
        let presented = pageDetail(detail)
        if store.isBookRoot && store.selectedResourceID == nil {
            VStack(alignment: .leading, spacing: 0) {
                hero(detail)
                    .bookContentAnchor("identity")
                    .accessibilityIdentifier("work.book.identity")
                    .padding(.top, .space1)
                    .padding(.bottom, 18)

                bookReadingProgress(detail)
                    .padding(.bottom, .space1)

                detailActions(detail)
                    .padding(.bottom, .space3)

                if normalizedDescription(detail) != nil {
                    aboutSection(detail)
                        .padding(.bottom, .space3)
                }

                Divider().overlay(theme.divider.opacity(0.72))
                contentBrowserSection(detail)
                    .bookContentAnchor("contents")
                    .padding(.top, .space3)
            }
        } else if store.selectedResourceID == nil {
            contentBrowserSection(detail)
                .bookContentAnchor("contents")
                .padding(.top, .space1)
        } else {
            VStack(alignment: .leading, spacing: 0) {
                hero(presented)
                    .bookContentAnchor("identity")
                    .accessibilityIdentifier("work.resource.identity")
                    .padding(.top, .space1)
                    .padding(.bottom, 18)

                detailActions(detail)
                    .padding(.bottom, .space3)

                if normalizedDescription(presented) != nil {
                    aboutSection(presented)
                        .padding(.bottom, .space3)
                }

                Divider().overlay(theme.divider.opacity(0.72))
                mediaSection(detail)
                    .padding(.top, .space3)
            }
        }
    }

    @ViewBuilder
    private func hero(_ detail: BookDetailContent) -> some View {
        VStack(alignment: .center, spacing: .space1Half) {
            cover(detail)
                .frame(
                    width: dynamicTypeSize.isAccessibilitySize ? 124 : 132,
                    height: dynamicTypeSize.isAccessibilitySize ? 186 : 198
                )
            identity(detail)
                .frame(maxWidth: .infinity)
        }
    }

    private func pageManagementTarget(_ detail: BookDetailContent) -> NativeManagementTarget {
        if store.isBookRoot {
            var target = NativeManagementTarget.book(detail.book.id, currentDetail?.book.title ?? detail.book.title)
            target.completed = currentDetail?.readingStatus == .finished
            return target
        }
        let resource = detail.resources.first { $0.id == store.selectedResourceID }
        return NativeManagementTarget(kind: .resource, bookID: detail.book.id, id: store.selectedResourceID ?? detail.book.id,
            title: resource?.title ?? detail.book.title, kindleEligible: resource?.kindleSendAvailable == true)
    }

    private func nodeManagementTarget(_ item: WorkContentItemPresentation) -> NativeManagementTarget? {
        guard let detail = currentDetail else { return nil }
        if item.entry.isSourceFolder {
            return NativeManagementTarget(kind: .directory, bookID: detail.book.id, id: item.entry.sourceNodeID,
                title: item.title, hasRepresentative: item.entry.representativeResourceID != nil)
        }
        if let resourceID = item.entry.resourceID {
            return NativeManagementTarget(kind: .resource, bookID: detail.book.id, id: resourceID, title: item.title,
                kindleEligible: item.resource?.kindleSendAvailable == true)
        }
        guard item.entry.isSourceFolder else { return nil }
        return NativeManagementTarget(kind: .directory, bookID: detail.book.id, id: item.entry.sourceNodeID,
            title: item.title, hasRepresentative: item.entry.representativeResourceID != nil)
    }

    private func cover(_ detail: BookDetailContent) -> some View {
        BookCoverView(
            reference: detail.book.cover,
            title: detail.book.title,
            context: context,
            client: client,
            cache: cache,
            cornerRadius: CGFloat(GeneratedDesignTokens.Radii.coverHero),
            managementTarget: pageManagementTarget(detail)
        )
        .id("work-cover-\(coverRefreshToken)")
    }

    private func identity(_ detail: BookDetailContent) -> some View {
        VStack(alignment: .center, spacing: .spaceHalf) {
            Text(detail.book.title)
                .appTextStyle(.title)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)

            creatorSeriesLine(detail)

            let chips = identityChips(detail)
            if !chips.isEmpty {
                FlowTags(tags: chips)
            }

            if store.selectedResourceID != nil {
                Spacer(minLength: .spaceHalf)
                progressSummary(detail)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private func identityChips(_ detail: BookDetailContent) -> [String] {
        detail.tags.reduce(into: []) { result, value in
            guard !result.contains(where: { $0.caseInsensitiveCompare(value) == .orderedSame }) else { return }
            result.append(value)
        }
    }

    private func creatorSeriesLine(_ detail: BookDetailContent) -> some View {
        HStack(spacing: .spaceHalf) {
            if let author = detail.authorFacets.first {
                facetButton(author, kind: .author)
            } else {
                Text(detail.book.author ?? "—")
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
    private func progressSummary(_ detail: BookDetailContent) -> some View {
        let progress = detail.book.progress
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

    private func bookReadingProgress(_ detail: BookDetailContent) -> some View {
        let resource = readingResource(detail)
        let progress = resource?.progress ?? 0
        let isAudio = resource?.readerType.lowercased() == "audio"
        return VStack(alignment: .leading, spacing: .space1) {
            if let resource, progress > 0 {
                Text(String(format: String(localized: isAudio ? "work.book.listening.format" : "work.book.reading.format"), resource.title))
                    .appTextStyle(.label)
                    .foregroundStyle(theme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("work.book.readingResource")
                ProgressView(value: min(100, max(0, progress)), total: 100)
                    .tint(theme.brandAccent)
                    .accessibilityLabel(Text("work.reading.progress"))
                    .accessibilityValue(Text((progress / 100).formatted(.percent.precision(.fractionLength(0)))))
            }
        }
    }

    private func detailActions(_ detail: BookDetailContent) -> some View {
        let selected = readingResource(detail)
        let readingStatus = store.isBookRoot ? (detail.readingStatus ?? .unread) : resourceReadingStatus(selected)
        let bookDownload = bookDownloadSummary(detail)
        let isAudio = selected?.readerType.lowercased() == "audio"
        let hasProgress = (selected?.progress ?? 0) > 0
        let title: LocalizedStringKey = isAudio
            ? (hasProgress ? "work.listener.continue.action" : "work.listener.start.action")
            : (hasProgress ? "work.reader.continue.action" : "work.reader.start.action")
        return VStack(spacing: .space1) {
            PrimaryActionButton(
                title,
                systemImage: isAudio ? "headphones" : "play.fill",
                isDisabled: selected?.isReadable != true,
                action: {
                    guard let selected else { return }
                    requestReaderAccess(detail: detail, resource: selected)
                }
            )
            .frame(minHeight: 52)
            .accessibilityIdentifier("work.reader.action")
            HStack(spacing: 0) {
                quickAction(store.isBookRoot ? bookDownloadTitle(bookDownload) : downloadActionTitle(selected), systemImage: store.isBookRoot ? bookDownloadImage(bookDownload) : (selected.map { downloadSystemImage(resourceID: $0.id) } ?? "arrow.down.circle")) {
                    if store.isBookRoot { activeSheet = .downloads; return }
                    guard let selected else { return }
                    handlePrimaryDownload(selected, detail: detail)
                }
                .disabled(!store.isBookRoot && (selected == nil || (selected?.isReadable != true && selected.flatMap { downloads.record(for: $0.id) } == nil)))
                .accessibilityIdentifier("work.download.action")
                quickAction(readingStatus.title, systemImage: readingStatusImage(readingStatus)) {
                    togglePageReadingStatus(detail)
                }
                .disabled((!store.isBookRoot && selected == nil) || managementStore == nil || managementStore?.isBusy == true)
                .accessibilityIdentifier("work.readingStatus.action")
                if store.isBookRoot {
                    quickAction("work.action.add", systemImage: "books.vertical") { openShelfPicker() }
                        .accessibilityIdentifier("work.shelf.action")
                    bookControlMenu(detail)
                } else if let selected {
                    bookControlMenu(detail, target: .resource(selected.id))
                }
            }
            .accessibilityIdentifier("work.detail.actions")
            if selected?.isReadable != true {
                Text("work.reader.unavailable.action")
                    .appTextStyle(.label)
                    .foregroundStyle(theme.textSecondary)
            }
        }
    }

    private func readingResource(_ detail: BookDetailContent) -> BookResource? {
        detail.readingResource(isBookRoot: store.isBookRoot, selectedResourceID: store.selectedResourceID)
    }

    private func bookDownloadSummary(_ detail: BookDetailContent) -> ErmaoShared.BookDetailDownloadSummary {
        let resourceIDs = Set(downloads.records.filter { $0.bookID == detail.book.id }.map(\.resourceID))
        let states: [ErmaoShared.BookDetailDownloadState] = resourceIDs.compactMap { id in
            guard let record = downloads.record(for: id) else { return nil }
            switch record.state {
            case .queued, .downloading: return .downloading
            case .paused: return .paused
            case .failedRetryable, .failedTerminal: return .failed
            case .completed: return record.isVerifiedOfflineCopy ? .downloaded : .failed
            }
        }
        return ErmaoShared.PublicKt.summarizeBookDetailDownloads(states: states)
    }

    private func bookDownloadTitle(_ summary: ErmaoShared.BookDetailDownloadSummary) -> LocalizedStringKey {
        switch summary.state {
        case .downloading: return "work.multiDownload.downloading"
        case .paused: return "work.multiDownload.paused"
        case .failed: return "work.download.retry"
        case .downloaded:
            return LocalizedStringKey(String(format: String(localized: "work.download.bookCount.format"), Int(summary.downloadedResources)))
        default: return "work.action.download"
        }
    }

    private func bookDownloadImage(_ summary: ErmaoShared.BookDetailDownloadSummary) -> String {
        switch summary.state {
        case .downloading: "arrow.down.circle"
        case .paused: "pause.circle"
        case .failed: "arrow.clockwise.circle"
        case .downloaded: "checkmark.circle"
        default: "arrow.down.circle"
        }
    }

    private func readingStatusImage(_ status: LibraryReadingStatus) -> String {
        switch status {
        case .unread: "book.closed"
        case .reading: "book"
        case .finished: "checkmark.circle"
        }
    }

    private func bookControlMenu(_ detail: BookDetailContent, target: WorkControlTarget = .book) -> some View {
        NativeManagementMore(target: pageManagementTarget(detail)) {
            quickActionLabel("work.action.more", systemImage: "ellipsis.circle")
        }
        .accessibilityIdentifier(target == .book ? "work.book.moreMenu" : "work.resource.moreMenu")
    }

    private func directoryControlMenu() -> some View {
        Menu {
            if let node = store.contentsPage?.currentNode, node.isSourceFolder {
                NativeManagementMenu(target: NativeManagementTarget(kind: .directory, bookID: store.bookIDValue,
                    id: node.sourceNodeID, title: node.title, hasRepresentative: node.representativeResourceID != nil))
            }
            Button { activeSheet = .downloads } label: {
                Label("work.action.download", systemImage: "arrow.down")
            }
            .accessibilityIdentifier("work.directory.download")
        } label: {
            Label("common.more", systemImage: "ellipsis")
                .labelStyle(.iconOnly)
        }
        .menuOrder(.fixed)
        .accessibilityIdentifier("work.directory.moreMenu")
    }

    private func controlMenuButtons(_ actions: [WorkControlAction]) -> some View {
        ForEach(actions) { action in
            Button(role: action.destructive ? .destructive : nil) {
                action.perform()
            } label: {
                Label { Text(action.title) } icon: { Image(systemName: action.systemImage) }
            }
            .disabled(!action.enabled)
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
            Image(systemName: systemImage)
                .font(.system(size: 24, weight: .regular))
                .frame(width: 28, height: 28)
                .accessibilityHidden(true)
            Text(title)
                .appTextStyle(.caption)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
        }
        .foregroundStyle(theme.textSecondary)
        .frame(maxWidth: .infinity, minHeight: 56)
        .contentShape(Rectangle())
    }

    @ViewBuilder
    private func aboutSection(_ detail: BookDetailContent) -> some View {
        if let description = normalizedDescription(detail) {
            VStack(alignment: .leading, spacing: .spaceHalf) {
                Text(description)
                    .appTextStyle(.body)
                    .foregroundStyle(theme.textSecondary)
                    .lineLimit(isDescriptionExpanded ? nil : 3)
                    .fixedSize(horizontal: false, vertical: true)
                Button {
                    isDescriptionExpanded.toggle()
                } label: {
                    Text(isDescriptionExpanded ? "work.description.collapse" : "work.description.expand")
                        .appTextStyle(.caption)
                        .frame(minHeight: .iosMinimumTouchTarget)
                }
                .buttonStyle(.plain)
                .foregroundStyle(theme.textSecondary)
                .frame(maxWidth: .infinity, alignment: .trailing)
                .accessibilityLabel(Text(isDescriptionExpanded ? "work.description.collapse" : "work.description.expand"))
            }
        }
    }

    private func normalizedDescription(_ detail: BookDetailContent) -> String? {
        WorkDescriptionPlainText.normalize(detail.description)
    }

    @ViewBuilder
    private func mediaSection(_ detail: BookDetailContent) -> some View {
        if let resourceID = store.selectedResourceID,
           let resource = detail.resources.first(where: { $0.id == resourceID }) {
            resourceDetailSection(detail, resource: resource)
        } else {
            contentBrowserSection(detail)
        }
    }

    @ViewBuilder
    private func contentBrowserSection(_ detail: BookDetailContent) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline) {
                Spacer()
                if let page = store.contentsPage {
                    Text(String(
                        format: String(localized: "work.contents.count.format"),
                        locale: locale,
                        page.total
                    ))
                    .appTextStyle(.label)
                    .foregroundStyle(theme.textSecondary)
                }
                Menu {
                    ForEach(BookContentSort.allCases, id: \.self) { sort in
                        Button(contentSortTitle(sort)) { store.selectContentSort(sort) }
                    }
                } label: {
                    Label(contentSortTitle(store.contentSort), systemImage: "arrow.up.arrow.down")
                        .labelStyle(.iconOnly)
                        .frame(width: .iosMinimumTouchTarget, height: .iosMinimumTouchTarget)
                }
                .accessibilityIdentifier("work.contents.sort")
                Button {
                    store.selectContentLayout(store.contentLayout == .grid ? .list : .grid)
                } label: {
                    Image(systemName: store.contentLayout == .grid ? "list.bullet" : "square.grid.2x2")
                        .frame(width: .iosMinimumTouchTarget, height: .iosMinimumTouchTarget)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(Text(store.contentLayout == .grid ? "library.view.list" : "library.view.grid"))
                .accessibilityIdentifier("work.contents.layout")
            }
            .padding(.bottom, .space1)

            if let page = store.contentsPage {
                contentBreadcrumbs(detail: detail, page: page)
                let items = workContentItemPresentations(page: page, detail: detail)
                if items.isEmpty {
                    Text("work.contents.empty")
                        .appTextStyle(.body)
                        .foregroundStyle(theme.textTertiary)
                        .frame(maxWidth: .infinity, minHeight: 96, alignment: .center)
                } else if store.contentLayout == .grid {
                    LazyVGrid(
                        columns: [
                            GridItem(
                                .adaptive(
                                    minimum: BookCoverLayout.horizontalCardWidth,
                                    maximum: BookCoverLayout.horizontalCardWidth
                                ),
                                spacing: .space2,
                                alignment: .top
                            )
                        ],
                        alignment: .leading,
                        spacing: .space2
                    ) {
                        ForEach(items) { item in
                            contentGridItem(item)
                        }
                    }
                } else {
                    VStack(spacing: 0) {
                        ForEach(items) { item in
                            if item.kind == .sourceDirectory {
                                sourceDirectoryRow(item)
                            } else if let resource = item.resource {
                                resourceListRow(
                                    resource,
                                    entry: item.entry,
                                    detail: detail,
                                    displayIndex: item.indexLabel
                                )
                            } else {
                                unresolvedResourceRow(item)
                            }
                            Divider().overlay(theme.divider.opacity(0.72))
                        }
                    }
                }
                if page.totalPages > 1 {
                    paginationRow(page: page.page, totalPages: page.totalPages, action: store.selectContentPage)
                        .padding(.top, .space2)
                }
            } else if store.isLoadingContentBrowser {
                HStack(spacing: .space1) {
                    ProgressView()
                    Text("common.loading")
                        .appTextStyle(.body)
                        .foregroundStyle(theme.textSecondary)
                }
                .frame(maxWidth: .infinity, minHeight: 112, alignment: .center)
            } else if store.contentBrowserFailed {
                contentBrowserRetry
            } else if detail.resources.isEmpty {
                Text("work.volumes.empty.message")
                    .appTextStyle(.body)
                    .foregroundStyle(theme.textTertiary)
                    .frame(maxWidth: .infinity, minHeight: 96, alignment: .center)
            } else {
                VStack(spacing: 0) {
                    ForEach(detail.resources) { resource in
                        resourceListRow(resource, entry: nil, detail: detail)
                        Divider().overlay(theme.divider.opacity(0.72))
                    }
                }
            }
        }
    }

    private func contentGridItem(_ item: WorkContentItemPresentation) -> some View {
        VStack(alignment: .leading, spacing: .spaceHalf) {
            Button {
                if item.kind == .sourceDirectory {
                    openDirectory(item.entry.sourceNodeID)
                } else if let resourceID = item.resource?.id ?? item.entry.resourceID {
                    openContent(.resource(resourceID: resourceID))
                }
            } label: {
                VStack(alignment: .leading, spacing: .space1) {
                    ZStack(alignment: .topLeading) {
                        BookCoverView(
                            reference: item.cover,
                            title: item.title,
                            context: context,
                            client: client,
                            cache: cache,
                            managementTarget: nodeManagementTarget(item)
                        )
                        .frame(width: BookCoverLayout.horizontalCardWidth)
                        .overlay(alignment: .bottom) {
                            if item.kind == .readableResource,
                               let progress = item.resource?.progress,
                               progress > 0 {
                                ResourceCoverProgressView(progress: progress)
                                    .padding(.horizontal, .space1)
                                    .padding(.bottom, .spaceHalf)
                            }
                        }

                        Text(item.indexLabel)
                            .appTextStyle(.caption)
                            .fontWeight(.semibold)
                            .monospacedDigit()
                            .foregroundStyle(theme.canvas)
                            .frame(width: 32, height: 32)
                            .background(theme.textPrimary.opacity(0.62))
                            .clipShape(Circle())
                            .padding(.space1)
                    }

                    HStack(alignment: .top, spacing: .spaceHalf) {
                        Text(item.title)
                            .appTextStyle(.body)
                            .fontWeight(.semibold)
                            .foregroundStyle(theme.textPrimary)
                            .lineLimit(2)
                        Spacer(minLength: 0)
                        if item.kind == .sourceDirectory {
                            Image(systemName: "chevron.right")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(theme.textTertiary)
                                .accessibilityHidden(true)
                        }
                    }
                    if item.kind == .readableResource, let format = item.resource?.formatLabel {
                        Text(format)
                            .appTextStyle(.caption)
                            .foregroundStyle(theme.textSecondary)
                    } else if item.kind == .readableResource {
                        Text("work.contents.readableResource")
                            .appTextStyle(.caption)
                            .foregroundStyle(theme.textSecondary)
                    }
                }
                .frame(width: BookCoverLayout.horizontalCardWidth, alignment: .leading)
            }
            .buttonStyle(.plain)
            .accessibilityElement(children: .ignore)
            .accessibilityIdentifier(
                item.kind == .sourceDirectory
                    ? "work.contents.folder.\(item.entry.sourceNodeID)"
                    : "work.resource.\(item.resource?.id ?? item.entry.resourceID ?? item.entry.sourceNodeID)"
            )
            .accessibilityLabel(Text(item.title))
            .accessibilityValue(Text(
                item.kind == .sourceDirectory
                    ? sourceDirectoryLabel(position: item.position, locale: locale)
                    : item.resource?.formatLabel ?? String(localized: "work.contents.readableResource")
            ))

            if item.kind == .readableResource && item.entry.hasChildren {
                Button("work.contents.openChildren") { openContent(.directory(sourceNodeID: item.entry.sourceNodeID)) }
                    .appTextStyle(.caption)
                    .frame(minHeight: .iosMinimumTouchTarget)
            }
        }
        .bookContentAnchor("node:\(item.entry.sourceNodeID)")
    }

    private func contentBreadcrumbs(detail: BookDetailContent, page: BookContentsPage) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: .spaceHalf) {
                ForEach(workContentBreadcrumbs(bookTitle: detail.book.title, page: page)) { breadcrumb in
                    if !breadcrumb.isRoot {
                        Image(systemName: "chevron.right")
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(theme.textTertiary)
                            .accessibilityHidden(true)
                    }
                    Button { openDirectory(breadcrumb.sourceNodeID) } label: {
                        Text(breadcrumb.title)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier(
                        breadcrumb.isRoot
                            ? "work.contents.breadcrumb.root"
                            : "work.contents.breadcrumb.\(breadcrumb.sourceNodeID ?? "unknown")"
                    )
                }
            }
            .appTextStyle(.caption)
            .foregroundStyle(theme.textSecondary)
            .frame(minHeight: .iosMinimumTouchTarget)
        }
        .accessibilityLabel(Text("work.contents.breadcrumbs"))
    }

    private func sourceDirectoryRow(_ item: WorkContentItemPresentation) -> some View {
        Button { openDirectory(item.entry.sourceNodeID) } label: {
            HStack(spacing: .space2) {
                BookCoverView(
                    reference: item.cover,
                    title: item.title,
                    context: context,
                    client: client,
                    cache: cache,
                            managementTarget: nodeManagementTarget(item)
                )
                .frame(width: 40)
                VStack(alignment: .leading, spacing: .spaceHalf) {
                    Text(item.title)
                        .appTextStyle(.body)
                        .fontWeight(.semibold)
                        .foregroundStyle(theme.textPrimary)
                        .lineLimit(1)
                    Text(sourceDirectoryLabel(position: item.position, locale: locale))
                        .appTextStyle(.caption)
                        .foregroundStyle(theme.textSecondary)
                }
                Spacer(minLength: .space1)
                Image(systemName: "chevron.right")
                    .font(.body.weight(.semibold))
                    .foregroundStyle(theme.textTertiary)
            }
            .frame(minHeight: 64)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("work.contents.folder.\(item.entry.sourceNodeID)")
    }

    private func unresolvedResourceRow(_ item: WorkContentItemPresentation) -> some View {
        Button {
            guard let resourceID = item.entry.resourceID else { return }
            openContent(.resource(resourceID: resourceID))
        } label: {
            HStack(spacing: .space2) {
                Text(item.indexLabel)
                    .appTextStyle(.caption)
                    .monospacedDigit()
                    .foregroundStyle(theme.textSecondary)
                    .frame(width: 28, alignment: .leading)
                BookCoverView(
                    reference: item.cover,
                    title: item.title,
                    context: context,
                    client: client,
                    cache: cache,
                            managementTarget: nodeManagementTarget(item)
                )
                .frame(width: 40)
                VStack(alignment: .leading, spacing: .spaceHalf) {
                    Text(item.title)
                        .appTextStyle(.body)
                        .fontWeight(.semibold)
                        .foregroundStyle(theme.textPrimary)
                        .lineLimit(1)
                    Text("work.contents.readableResource")
                        .appTextStyle(.caption)
                        .foregroundStyle(theme.textSecondary)
                }
                Spacer(minLength: .space1)
                Image(systemName: "chevron.right")
                    .font(.body.weight(.semibold))
                    .foregroundStyle(theme.textTertiary)
            }
            .frame(minHeight: 76)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func resourceListRow(
        _ resource: BookResource,
        entry: BookContentEntry?,
        detail: BookDetailContent,
        displayIndex: String? = nil
    ) -> some View {
        HStack(spacing: .space1) {
            Text(displayIndex ?? resourceDisplayIndex(resource, detail: detail))
                .appTextStyle(.caption)
                .monospacedDigit()
                .foregroundStyle(resource.isSelected ? theme.brandAccent : theme.textSecondary)
                .frame(width: 28, alignment: .leading)

            Button { openContent(.resource(resourceID: resource.id)) } label: {
                HStack(spacing: .space2) {
                    BookCoverView(
                        reference: resource.cover ?? entry?.cover,
                        title: resource.title,
                        context: context,
                        client: client,
                        cache: cache,
                        managementTarget: NativeManagementTarget(kind: .resource, bookID: resource.bookID, id: resource.id, title: resource.title, kindleEligible: resource.kindleSendAvailable)
                    )
                    .frame(width: 40)
                    .overlay(alignment: .bottom) {
                        if let progress = resource.progress, progress > 0 {
                            ResourceCoverProgressView(progress: progress)
                                .padding(.horizontal, 2)
                                .padding(.bottom, 2)
                        }
                    }
                    VStack(alignment: .leading, spacing: 2) {
                        Text(resource.title)
                            .appTextStyle(.body)
                            .fontWeight(.semibold)
                            .foregroundStyle(theme.textPrimary)
                            .lineLimit(1)
                        HStack(spacing: .spaceHalf) {
                            Text(resource.formatLabel)
                            Text("·")
                            Text("work.contents.readableResource")
                        }
                        .appTextStyle(.caption)
                        .foregroundStyle(theme.textSecondary)
                        .lineLimit(1)
                        if let progress = resource.progress, progress > 0 {
                            Text(progressLabel(progress))
                                .appTextStyle(.caption)
                                .foregroundStyle(theme.brandAccent)
                                .lineLimit(1)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    Spacer(minLength: 0)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            Button { handleDownload(resource, detail: detail) } label: {
                Image(systemName: downloadSystemImage(resourceID: resource.id))
                    .font(.system(size: 20, weight: .medium))
                    .foregroundStyle(downloadForeground(resourceID: resource.id))
                    .frame(width: .iosMinimumTouchTarget, height: .iosMinimumTouchTarget)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(Text(downloadAccessibilityLabel(resourceID: resource.id)))

            if entry?.hasChildren == true {
                Button { openDirectory(entry?.sourceNodeID) } label: {
                    Image(systemName: "chevron.right")
                        .font(.body.weight(.semibold))
                        .foregroundStyle(theme.textTertiary)
                        .frame(width: .iosMinimumTouchTarget, height: .iosMinimumTouchTarget)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(Text("work.contents.openChildren"))
            } else {
                Image(systemName: "chevron.right")
                    .font(.body.weight(.semibold))
                    .foregroundStyle(theme.textTertiary)
                    .frame(width: 16)
                    .accessibilityHidden(true)
            }
        }
        .frame(minHeight: 76)
        .padding(.horizontal, resource.isSelected ? .space1 : 0)
        .background(
            resource.isSelected ? theme.brandAccent.opacity(0.045) : Color.clear,
            in: RoundedRectangle(cornerRadius: 12, style: .continuous)
        )
        .overlay {
            if resource.isSelected {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(theme.brandAccent.opacity(0.72), lineWidth: 1.5)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("work.resource.\(resource.id)")
        .accessibilityValue(resourceAccessibilityValue(resource))
        .accessibilityAddTraits(resource.isSelected ? .isSelected : [])
    }

    private func resourceDisplayIndex(_ resource: BookResource, detail: BookDetailContent) -> String {
        resource.displayIndex(position: detail.resources.firstIndex(where: { $0.id == resource.id }) ?? 0)
    }

    @ViewBuilder
    private func resourceDetailSection(_ detail: BookDetailContent, resource: BookResource) -> some View {
        VStack(alignment: .leading, spacing: .space2) {
            selectedResourceMetadata(resource)
            if let status = resource.importStatus, status.uppercased() != "READY" {
                Text("work.resource.importPending").appTextStyle(.body).foregroundStyle(theme.textSecondary)
            }
            if let node = store.contentsPage?.currentNode, node.hasChildren {
                Button("work.contents.openChildren") { openContent(.directory(sourceNodeID: node.sourceNodeID)) }
                    .frame(minHeight: .iosMinimumTouchTarget)
            }
            if resourcePreviewIsVisible {
                HStack(alignment: .firstTextBaseline) {
                    Text(resourceDetailTitle(resource)).appTextStyle(.sectionTitle)
                    Spacer()
                    if let page = store.resourceDetailPage {
                        Text(String(
                            format: String(localized: "work.resource.units.count.format"),
                            locale: locale,
                            page.total
                        ))
                        .appTextStyle(.label)
                        .foregroundStyle(theme.textSecondary)
                    }
                }
                Text("\(resource.title) · \(resource.formatLabel)")
                    .appTextStyle(.caption)
                    .foregroundStyle(theme.textSecondary)
                    .padding(.top, .spaceHalf)
                    .padding(.bottom, .space1)

                if let page = store.resourceDetailPage {
                    if page.units.isEmpty {
                        Text("work.resource.units.empty")
                            .appTextStyle(.body)
                            .foregroundStyle(theme.textTertiary)
                            .frame(maxWidth: .infinity, minHeight: 96, alignment: .center)
                    } else {
                        if resource.readerType.lowercased() == "comic" || resource.readerType.lowercased() == "pdf" {
                            LazyVGrid(
                                columns: [
                                    GridItem(
                                        .adaptive(
                                            minimum: BookCoverLayout.horizontalCardWidth,
                                            maximum: BookCoverLayout.horizontalCardWidth
                                        ),
                                        spacing: .space2,
                                        alignment: .top
                                    )
                                ],
                                alignment: .leading,
                                spacing: .space2
                            ) {
                                ForEach(page.units) { unit in
                                    resourcePageTile(unit, detail: detail)
                                }
                            }
                        } else {
                            VStack(spacing: 0) {
                                ForEach(Array(page.units.enumerated()), id: \.element.id) { index, unit in
                                    resourceUnitRow(
                                        unit,
                                        displayIndex: (page.page - 1) * page.pageSize + index + 1,
                                        detail: detail
                                    )
                                    Divider().overlay(theme.divider.opacity(0.72))
                                }
                            }
                        }
                        if page.totalPages > 1 {
                            paginationRow(page: page.page, totalPages: page.totalPages, action: store.selectResourceDetailPage)
                                .padding(.top, .space2)
                        }
                    }
                } else if store.isLoadingContentBrowser {
                    HStack(spacing: .space1) {
                        ProgressView()
                        Text("common.loading")
                            .appTextStyle(.body)
                            .foregroundStyle(theme.textSecondary)
                    }
                    .frame(maxWidth: .infinity, minHeight: 112, alignment: .center)
                } else if store.contentBrowserFailed {
                    contentBrowserRetry
                }
            }
        }
    }

    private func resourcePageTile(_ unit: BookResourceDetailUnit, detail: BookDetailContent) -> some View {
        Button { requestReaderAccess(detail: detail, unit: unit) } label: {
            VStack(alignment: .leading, spacing: .space1) {
                if let previewURL = unit.previewURL, !previewURL.isEmpty {
                    BookCoverView(
                        reference: CoverReference(path: previewURL),
                        title: unit.title,
                        context: context,
                        client: client,
                        cache: cache
                    )
                    .frame(width: BookCoverLayout.horizontalCardWidth)
                } else {
                    Image(systemName: "photo")
                        .frame(
                            width: BookCoverLayout.horizontalCardWidth,
                            height: BookCoverLayout.horizontalCardHeight
                        )
                        .background(theme.surface)
                }
                Text(unit.title.isEmpty
                     ? String(format: String(localized: "work.resource.page.format"), unit.pageNumber ?? unit.sortOrder + 1)
                     : unit.title)
                    .appTextStyle(.body)
                    .foregroundStyle(theme.textPrimary)
                    .lineLimit(1)
            }
            .frame(width: BookCoverLayout.horizontalCardWidth, alignment: .leading)
        }
        .buttonStyle(.plain)
        .bookContentAnchor("unit:\(unit.id)")
    }

    private func resourceUnitRow(
        _ unit: BookResourceDetailUnit,
        displayIndex: Int,
        detail: BookDetailContent
    ) -> some View {
        Button { requestReaderAccess(detail: detail, unit: unit) } label: {
            HStack(spacing: .space1) {
                Text(String(format: "%02d", displayIndex))
                    .appTextStyle(.body)
                    .monospacedDigit()
                    .foregroundStyle(unit.chapterState == .current ? theme.brandAccent : theme.textSecondary)
                    .frame(width: 36, alignment: .leading)
                VStack(alignment: .leading, spacing: .spaceHalf) {
                    Text(unit.title.isEmpty
                         ? String(format: String(localized: "work.resource.unit.format"), displayIndex)
                         : unit.title)
                        .appTextStyle(.body)
                        .fontWeight(unit.chapterState == .current ? .semibold : .regular)
                        .foregroundStyle(unit.chapterState == .current ? theme.brandAccent : theme.textPrimary)
                        .lineLimit(2)
                    if unit.unitType.lowercased() == "track" {
                        Text(formatDuration(unit.durationMillis))
                            .appTextStyle(.caption)
                            .foregroundStyle(theme.textSecondary)
                    }
                }
                Spacer(minLength: .space1)
                if let state = unit.chapterState {
                    Text(chapterStateTitle(state))
                        .appTextStyle(.caption)
                        .foregroundStyle(state == .current ? theme.brandAccent : theme.textSecondary)
                }
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(theme.textTertiary)
            }
            .frame(minHeight: 56)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .bookContentAnchor("unit:\(unit.id)")
    }

    private func paginationRow(page: Int, totalPages: Int, action: @escaping (Int) -> Void) -> some View {
        HStack {
            Text(String(format: String(localized: "work.pagination.format"), locale: locale, page, totalPages))
                .appTextStyle(.caption)
                .foregroundStyle(theme.textSecondary)
            Spacer()
            Button("common.previous") { action(page - 1) }.disabled(page <= 1)
            Button("common.next") { action(page + 1) }.disabled(page >= totalPages)
        }
    }

    private func resourceDetailTitle(_ resource: BookResource) -> LocalizedStringKey {
        switch resource.readerType.lowercased() {
        case "audio": "work.tracks.title"
        case "comic", "pdf": "work.pages.title"
        default: "work.chapters.title"
        }
    }

    private func contentSortTitle(_ sort: BookContentSort) -> LocalizedStringKey {
        switch sort {
        case .nameAscending: "work.sort.nameAscending"
        case .nameDescending: "work.sort.nameDescending"
        case .updatedDescending: "work.sort.updatedDescending"
        case .updatedAscending: "work.sort.updatedAscending"
        case .typeAscending: "work.sort.typeAscending"
        case .sizeDescending: "work.sort.sizeDescending"
        }
    }

    private func formatDuration(_ milliseconds: Int64?) -> String {
        let seconds = max(0, milliseconds ?? 0) / 1_000
        let hours = seconds / 3_600
        let minutes = (seconds % 3_600) / 60
        let remainder = seconds % 60
        return hours > 0
            ? String(format: "%d:%02d:%02d", hours, minutes, remainder)
            : String(format: "%d:%02d", minutes, remainder)
    }

    private func chapterRow(
        _ chapter: BookChapter,
        displayIndex: Int,
        detail: BookDetailContent
    ) -> some View {
        Button { requestReaderAccess(detail: detail, chapterHref: chapter.href) } label: {
            HStack(spacing: .space1) {
                Text(String(format: "%02d", displayIndex))
                    .appTextStyle(.body)
                    .monospacedDigit()
                    .foregroundStyle(chapter.isCurrent ? theme.brandAccent : theme.textSecondary)
                    .frame(width: 36, alignment: .leading)
                Text(chapter.title)
                    .appTextStyle(.body)
                    .fontWeight(chapter.isCurrent ? .semibold : .regular)
                    .foregroundStyle(chapter.isCurrent ? theme.brandAccent : theme.textPrimary)
                    .lineLimit(2)
                Spacer(minLength: .space1)
                Text(chapterStateTitle(chapter.state))
                    .appTextStyle(.caption)
                    .foregroundStyle(chapter.isCurrent ? theme.brandAccent : theme.textSecondary)
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(theme.textTertiary)
            }
            .frame(minHeight: 56)
            .padding(.horizontal, chapter.isCurrent ? .space1 : 0)
            .background(chapter.isCurrent ? theme.brandAccent.opacity(0.055) : Color.clear)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func chapterStateTitle(_ state: ChapterReadingState) -> LocalizedStringKey {
        switch state {
        case .current: "work.chapter.current"
        case .read: "work.chapter.read"
        case .unread: "work.chapter.unread"
        }
    }

    private var contentBrowserRetry: some View {
        Button { store.retryContentBrowser() } label: {
            Label("common.retry", systemImage: "arrow.clockwise")
                .appTextStyle(.body)
                .frame(maxWidth: .infinity, minHeight: 96)
        }
        .buttonStyle(.plain)
        .foregroundStyle(theme.brandAccent)
    }

    private func resourceCoverItem(
        _ resource: BookResource,
        position: Int,
        detail: BookDetailContent
    ) -> some View {
        let index = resource.displayIndex(position: position)
        return VStack(alignment: .leading, spacing: .space1) {
            ZStack(alignment: .topLeading) {
                Button {
                    openContent(.resource(resourceID: resource.id))
                } label: {
                    BookCoverView(
                        reference: resource.cover,
                        title: resource.title,
                        context: context,
                        client: client,
                        cache: cache,
                        managementTarget: NativeManagementTarget(kind: .resource, bookID: resource.bookID, id: resource.id, title: resource.title, kindleEligible: resource.kindleSendAvailable)
                    )
                    .opacity(resource.isReadable == false ? 0.5 : 1)
                    .overlay {
                        if resource.isSelected {
                            RoundedRectangle(
                                cornerRadius: CGFloat(GeneratedDesignTokens.Radii.coverCompact),
                                style: .continuous
                            )
                            .stroke(theme.brandAccent, lineWidth: 2)
                        }
                    }
                    .overlay(alignment: .bottom) {
                        if let progress = resource.progress, progress > 0 {
                            ResourceCoverProgressView(progress: progress)
                                .padding(.horizontal, .space1)
                                .padding(.bottom, .spaceHalf)
                        }
                    }
                }
                .buttonStyle(.plain)
                .accessibilityElement(children: .ignore)
                .accessibilityIdentifier("work.resource.\(resource.id)")
                .accessibilityLabel(Text(resourceAccessibilityLabel(resource, index: index)))
                .accessibilityValue(resourceAccessibilityValue(resource))
                .accessibilityAddTraits(resource.isSelected ? .isSelected : [])
                .bookManagementMenu(NativeManagementTarget(kind: .resource, bookID: detail.book.id,
                    id: resource.id, title: resource.title, kindleEligible: resource.kindleSendAvailable))

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
                    handleDownload(resource, detail: detail)
                } label: {
                    Image(systemName: downloadSystemImage(resourceID: resource.id))
                        .font(.body.weight(.medium))
                        .foregroundStyle(downloadForeground(resourceID: resource.id))
                        .frame(width: 24, height: 24)
                        .background(theme.surfaceRaised.opacity(0.92))
                        .clipShape(Circle())
                        .frame(width: .iosMinimumTouchTarget, height: .iosMinimumTouchTarget)
                }
                .buttonStyle(.plain)
                .disabled(downloads.record(for: resource.id)?.isVerifiedOfflineCopy == true)
                .accessibilityLabel(Text(downloadAccessibilityLabel(resourceID: resource.id)))
                .frame(maxWidth: .infinity, alignment: .topTrailing)
            }

            Text(resource.title)
                .appTextStyle(.label)
                .foregroundStyle(theme.textPrimary)
                .lineLimit(2)
                .frame(minHeight: 40, alignment: .topLeading)
        }
    }

    private func selectedResourceMetadata(_ resource: BookResource) -> some View {
        let rows: [(LocalizedStringKey, String?, Bool)] = [
            ("work.metadata.format", resource.formatLabel, false),
            ("work.metadata.language", resource.language, false),
            ("work.metadata.published", formattedMetadataDate(resource.publishedAt), false),
            ("work.metadata.pages", resource.pageCount.map(String.init), false),
            ("work.metadata.source", resource.metadataSource, false),
            ("work.metadata.filePath", resource.assets.first?.path, true),
        ]
        return VStack(alignment: .leading, spacing: 0) {
            Text("work.metadata.title")
                .appTextStyle(.label)
                .fontWeight(.semibold)
                .foregroundStyle(theme.textSecondary)
                .padding(.bottom, .space1)
            ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                let value = metadataValue(row.1)
                HStack(alignment: .firstTextBaseline, spacing: .space2) {
                    Text(row.0).appTextStyle(.caption).foregroundStyle(theme.textSecondary)
                    Spacer(minLength: .space1)
                    Text(value)
                        .appTextStyle(.callout)
                        .multilineTextAlignment(.trailing)
                        .lineLimit(row.2 ? 1 : 2)
                        .truncationMode(.tail)
                }
                .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget)
                .contentShape(Rectangle())
                .onLongPressGesture {
                    if row.2, value != "—" { fullMetadataPath = value }
                }
                Divider().overlay(theme.divider.opacity(0.72))
            }
        }
        .accessibilityIdentifier("work.selectedResource.metadata")
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

    private func resourceAccessibilityValue(_ resource: BookResource) -> Text {
        if let progress = resource.progress {
            return Text("\(progressLabel(progress))")
        }
        return Text("work.volume.progress.notStarted")
    }

    private func resourceAccessibilityLabel(_ resource: BookResource, index: String) -> String {
        String(
            format: String(localized: "work.volume.accessibility.label"),
            locale: .current,
            index,
            resource.title
        )
    }

    private func selectedResource(_ detail: BookDetailContent) -> BookResource? {
        store.selectedResourceID.flatMap { id in detail.resources.first(where: { $0.id == id }) }
    }

    private func openDirectory(_ sourceNodeID: String?) {
        if sourceNodeID == nil || sourceNodeID == currentDetail?.rootSourceNodeID {
            openContent(.root)
        } else if let sourceNodeID {
            openContent(.directory(sourceNodeID: sourceNodeID))
        }
    }

    private func resourceReadingStatus(_ resource: BookResource?) -> LibraryReadingStatus {
        guard let progress = resource?.progress, progress > 0 else { return .unread }
        return progress >= 100 ? .finished : .reading
    }

    private func pageDetail(_ detail: BookDetailContent) -> BookDetailContent {
        if store.isBookRoot && store.selectedResourceID == nil { return detail }
        let resource = selectedResource(detail)
        let node = store.contentsPage?.currentNode
        let representative = node?.representativeResourceID.flatMap { id in detail.resources.first { $0.id == id } }
        return BookDetailContent(
            book: BookCard(
                id: detail.book.id, title: resource?.title ?? node?.title ?? detail.book.title,
                author: detail.book.author, cover: resource?.cover ?? node?.cover ?? representative?.cover ?? detail.book.cover,
                progress: resource?.progress
            ),
            description: resource != nil ? resource?.description : (node?.description ?? (store.isBookRoot ? detail.description : nil)),
            tags: store.isBookRoot ? detail.tags : [], seriesFacet: detail.seriesFacet,
            seriesIndex: detail.seriesIndex, authorFacets: detail.authorFacets, resources: detail.resources,
            selectedResourceID: store.selectedResourceID, readingStatus: resource == nil ? nil : resourceReadingStatus(resource),
            chapters: detail.chapters, rootSourceNodeID: detail.rootSourceNodeID
        )
    }

    private func kindleAsset(_ asset: ResourceAsset) -> Bool {
        let path = asset.path.lowercased()
        return path.hasSuffix(".epub") || path.hasSuffix(".pdf")
    }

    private var currentDetail: BookDetailContent? {
        guard case .ready(let detail) = store.state else { return nil }
        return detail
    }

    private var selectedDownloadErrorCode: String? {
        guard let detail = currentDetail,
              let resource = selectedResource(detail) else { return nil }
        return downloads.record(for: resource.id)?.stableErrorCode
    }

    @ViewBuilder
    private var feedbackBanner: some View {
        if let feedback {
            Label(
                feedback.message,
                systemImage: feedback.isError ? "exclamationmark.circle.fill" : "checkmark.circle.fill"
            )
            .appTextStyle(.callout)
            .foregroundStyle(feedback.isError ? Color.red : theme.textPrimary)
            .padding(.horizontal, .space2)
            .padding(.vertical, .space1Half)
            .background(theme.surfaceRaised)
            .clipShape(Capsule())
            .shadow(color: Color.black.opacity(0.12), radius: 10, y: 4)
            .padding(.horizontal, .space2)
            .padding(.bottom, .space2)
            .transition(.move(edge: .bottom).combined(with: .opacity))
            .accessibilityAddTraits(.isStaticText)
        }
    }

    private func showFeedback(_ message: String, isError: Bool) {
        let next = WorkDetailFeedback(message: message, isError: isError)
        withAnimation(.easeOut(duration: 0.18)) { feedback = next }
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(isError ? 5 : 3))
            guard feedback?.id == next.id else { return }
            withAnimation(.easeIn(duration: 0.16)) { feedback = nil }
        }
    }

    private func managementFeedback(_ action: WorkManagementStore.Action?) -> String {
        switch action {
        case .readingStatusUpdated: String(localized: "work.readingStatus.updated")
        case .coverUpdated: String(localized: "management.coverUpdated")
        case .rescanQueued: String(localized: "management.rescanQueued")
        case .metadataApplied: String(localized: "management.metadataApplied")
        case .workUpdated, .resourceUpdated: String(localized: "management.updated")
        case .kindleQueued: String(localized: "management.kindleQueued")
        case .bookDeleted, .none: String(localized: "management.updated")
        }
    }

    private func handleManagementCompletion(_ action: WorkManagementStore.Action?) {
        guard action != nil, let managementStore else { return }
        if action == .bookDeleted {
            downloads.remove(bookID: store.bookIDValue)
            managementStore.consumeCompletion()
            dismiss()
            return
        }
        if action == .coverUpdated {
            let mutatedResourceCover = managementStore.coverMutation.flatMap { mutation in
                currentDetail?.resources.first { $0.id == mutation.resourceId }?.cover?.path
            }
            let paths = Set(
                [
                    currentDetail?.book.cover?.path,
                    mutatedResourceCover,
                    managementStore.coverMutation?.coverUrl,
                ]
                    .compactMap { $0 }
                    .filter { !$0.isEmpty }
            )
            Task {
                for path in paths {
                    try? await cache.remove(namespace: context.namespaceKey, key: "cover|\(path)")
                }
                await MainActor.run { coverRefreshToken += 1 }
            }
        }
        activeSheet = nil
        showFeedback(managementFeedback(action), isError: false)
        managementStore.consumeCompletion()
        if action == .readingStatusUpdated, let target = pendingReadingStatusTarget {
            pendingReadingStatusTarget = nil
            switch target {
            case .book: store.refreshAfterBookReadingStatusChange()
            case .resource(let id): store.refreshAfterReadingStatusChange(resourceID: id)
            }
        } else {
            store.load(showBlockingLoading: false)
        }
    }

    private func togglePageReadingStatus(_ detail: BookDetailContent) {
        guard let managementStore, !managementStore.isBusy else { return }
        let current = store.isBookRoot ? (detail.readingStatus ?? .unread) : resourceReadingStatus(selectedResource(detail))
        let next: LibraryReadingStatus = current == .finished ? .unread : .finished
        if store.isBookRoot {
            pendingReadingStatusTarget = .book
            managementStore.setBookReadingStatus(next == .finished ? .finished : .unread)
        } else if let resource = selectedResource(detail) {
            pendingReadingStatusTarget = .resource(resource.id)
            managementStore.setReadingStatus(resourceID: resource.id, status: next == .finished ? .finished : .unread)
        }
    }

    private func openShelfPicker() {
        let generation = UUID()
        shelfRequestGeneration = generation
        activeSheet = .shelves
        isLoadingShelves = true
        shelfError = false
        Task {
            do {
                let loaded = try await shelfClient.fetchShelves(context: context, bookID: store.bookIDValue)
                guard shelfRequestGeneration == generation, case .shelves? = activeSheet else { return }
                shelves = loaded
                selectedShelfIDs = Set(loaded.filter(\.containsWork).map(\.id))
                isLoadingShelves = false
            } catch {
                guard shelfRequestGeneration == generation, case .shelves? = activeSheet else { return }
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
                            guard shelf.isMembershipEditable else { return }
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
                        .disabled(isSavingShelves || !shelf.isMembershipEditable)
                    }
                }
            }
            .navigationTitle("work.action.shelf")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("common.cancel") { activeSheet = nil }
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
        let generation = UUID()
        shelfRequestGeneration = generation
        let editableShelves = shelves.filter(\.isMembershipEditable)
        let original = Set(editableShelves.filter(\.containsWork).map(\.id))
        let additions = selectedShelfIDs.subtracting(original)
        let removals = original.subtracting(selectedShelfIDs)
        isSavingShelves = true
        Task {
            do {
                for shelfID in additions {
                    guard let shelf = editableShelves.first(where: { $0.id == shelfID }) else { continue }
                    try await shelfClient.updateShelf(context: context, bookID: store.bookIDValue, shelf: shelf, add: true)
                }
                for shelfID in removals {
                    guard let shelf = editableShelves.first(where: { $0.id == shelfID }) else { continue }
                    try await shelfClient.updateShelf(context: context, bookID: store.bookIDValue, shelf: shelf, add: false)
                }
                let refreshed = try await shelfClient.fetchShelves(
                    context: context,
                    bookID: store.bookIDValue
                )
                guard shelfRequestGeneration == generation, case .shelves? = activeSheet else { return }
                shelves = refreshed
                selectedShelfIDs = Set(refreshed.filter(\.containsWork).map(\.id))
                isSavingShelves = false
                activeSheet = nil
                showFeedback(String(localized: "work.shelf.saved"), isError: false)
            } catch {
                guard shelfRequestGeneration == generation, case .shelves? = activeSheet else { return }
                isSavingShelves = false
                shelfError = true
            }
        }
    }

    private func requestReaderAccess(detail: BookDetailContent, unit: BookResourceDetailUnit? = nil, chapterHref: String? = nil) {
        guard let resource = selectedResource(detail) else { return }
        requestReaderAccess(detail: detail, resource: resource, unit: unit, chapterHref: chapterHref)
    }

    private func requestReaderAccess(detail: BookDetailContent, resource: BookResource, unit: BookResourceDetailUnit? = nil, chapterHref: String? = nil) {
        guard resource.bookID == detail.book.id, resource.isReadable != false else { return }
        if resource.readerType.lowercased() == "audio" {
            guard let audioPlaybackRuntime else {
                readerAccessErrorCode = "AUDIO_ENGINE_UNAVAILABLE"
                return
            }
            audioPlaybackRuntime.launch(
                AudioLaunchIntent(
                    resourceID: resource.id,
                    assetID: resource.primaryAssetID,
                    chapterID: unit?.id,
                    positionMillis: nil,
                    autoplay: true
                ),
                namespace: context.namespaceKey
            )
            return
        }
        guard let readerType = ManagedDownloadReaderType.fixtureValue(
            format: resource.format,
            readerType: resource.readerType
        ) else {
            readerAccessErrorCode = "READER_TYPE_UNSUPPORTED"
            return
        }
        openReader(ReaderHandoff(
            bookID: detail.book.id,
            resourceID: resource.id,
            assetID: resource.primaryAssetID,
            title: detail.book.title,
            resourceTitle: resource.title,
            format: resource.format,
            readerType: readerType,
            source: .remoteStream,
            initialTargetPayload: (unit != nil || chapterHref != nil) ? ErmaoShared.PublicKt.encodeReaderLaunchTarget(
                target: ErmaoShared.PublicKt.readingUnitLaunchTarget(
                    readerType: resource.readerType, href: unit?.href ?? chapterHref,
                    pageNumber: unit?.pageNumber.map { KotlinInt(int: Int32($0)) }
                )
            ) : nil
        ))
    }

    private func requestReaderAccessForSelectedResource() {
        guard case .ready(let detail) = store.state else { return }
        requestReaderAccess(detail: detail)
    }

    private func downloadFailureMessage(_ code: String) -> String {
        if code == "DOWNLOAD_BOOTSTRAP_INVALID" {
            return String(localized: "download.bootstrap.invalid")
        }
        return String(format: String(localized: "work.download.failed.format"), code)
    }

    private func handlePrimaryDownload(_ resource: BookResource, detail: BookDetailContent) {
        if let record = downloads.record(for: resource.id) {
            switch record.state {
            case .queued, .downloading:
                downloads.pause(record)
                showFeedback(String(localized: "work.download.paused"), isError: false)
            case .paused, .failedRetryable, .failedTerminal:
                downloads.resume(record)
                showFeedback(String(localized: "work.download.resumed"), isError: false)
            case .completed:
                if record.isVerifiedOfflineCopy {
                    downloadMenuRecord = record
                } else {
                    downloads.retry(record)
                    showFeedback(String(localized: "work.download.resumed"), isError: false)
                }
            }
            return
        }
        downloads.enqueue(book: detail.book, resource: resource)
        showFeedback(String(localized: "work.download.queued"), isError: false)
    }

    private func downloadActionTitle(_ resource: BookResource?) -> LocalizedStringKey {
        guard let resource, let record = downloads.record(for: resource.id) else {
            return "work.action.download"
        }
        switch record.state {
        case .queued, .downloading: return "work.multiDownload.downloading"
        case .paused: return "work.multiDownload.paused"
        case .failedRetryable, .failedTerminal: return "work.download.retry"
        case .completed: return record.isVerifiedOfflineCopy ? "work.download.manage" : "work.download.retry"
        }
    }

    private func handleDownload(_ resource: BookResource, detail: BookDetailContent) {
        if let record = downloads.record(for: resource.id) {
            switch record.state {
            case .downloading, .queued: downloads.pause(record)
            case .paused, .failedRetryable, .failedTerminal: downloads.resume(record)
            case .completed:
                if record.isVerifiedOfflineCopy { downloadMenuRecord = record }
            }
        } else {
            downloads.enqueue(book: detail.book, resource: resource)
        }
    }

    private func downloadSystemImage(resourceID: String) -> String {
        guard let record = downloads.record(for: resourceID) else { return "arrow.down.circle" }
        switch record.state {
        case .queued, .downloading: return "pause.circle"
        case .paused, .failedRetryable, .failedTerminal: return "arrow.clockwise.circle"
        case .completed:
            return record.isVerifiedOfflineCopy ? "checkmark.circle" : "exclamationmark.circle"
        }
    }

    private func downloadForeground(resourceID: String) -> Color {
        downloads.record(for: resourceID)?.isVerifiedOfflineCopy == true
            ? theme.brandAccent
            : theme.textSecondary
    }

    private func openOffline(_ record: ManagedDownloadRecord) {
        guard record.isVerifiedOfflineCopy else {
            downloads.retry(record)
            showFeedback(String(localized: "downloads.error.invalid"), isError: true)
            return
        }
        if record.readerType == .audio {
            guard record.namespace == context.namespaceKey,
                  record.verifiedSharedArtifact != nil,
                  let expectedBytes = record.expectedBytes,
                  expectedBytes == record.receivedBytes,
                  let mimeType = record.mimeType,
                  let audioPlaybackRuntime else {
                showFeedback(String(localized: "downloads.error.invalid"), isError: true)
                return
            }
            Task { @MainActor in
                guard let fileURL = await downloads.localFileURL(for: record) else {
                    showFeedback(String(localized: "downloads.error.invalid"), isError: true)
                    return
                }
                audioPlaybackRuntime.launchVerifiedLocalArtifact(
                    namespace: context.namespaceKey,
                    userID: context.userID,
                    bookID: record.bookID,
                    bookTitle: record.bookTitle,
                    author: record.bookAuthor,
                    resourceID: record.resourceID,
                    resourceTitle: record.resourceTitle,
                    assetID: record.assetID,
                    fileURL: fileURL,
                    mimeType: mimeType,
                    sizeBytes: expectedBytes
                )
            }
            return
        }
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

    private func downloadAccessibilityLabel(resourceID: String) -> LocalizedStringKey {
        guard let record = downloads.record(for: resourceID) else { return "work.volume.download.action" }
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

enum WorkContentItemKind: Equatable {
    case sourceDirectory
    case readableResource
}

struct WorkContentItemPresentation: Identifiable, Equatable {
    let entry: BookContentEntry
    let kind: WorkContentItemKind
    let resource: BookResource?
    let cover: CoverReference?
    let title: String
    let position: Int
    let indexLabel: String

    var id: String { entry.sourceNodeID }
}

struct WorkContentBreadcrumbPresentation: Identifiable, Equatable {
    let title: String
    let sourceNodeID: String?

    var id: String { sourceNodeID ?? "work-contents-root" }
    var isRoot: Bool { sourceNodeID == nil }
}

func workContentItemPresentations(
    page: BookContentsPage,
    detail: BookDetailContent
) -> [WorkContentItemPresentation] {
    var entries = page.entries.filter { $0.isSourceFolder || $0.isDirectResource }
    if page.currentNode.isDirectResource,
       !entries.contains(where: { $0.sourceNodeID == page.currentNode.sourceNodeID }) {
        entries.insert(page.currentNode, at: 0)
    }

    let resourcesByID = Dictionary(uniqueKeysWithValues: detail.resources.map { ($0.id, $0) })
    let directories = entries.filter(\.isSourceFolder)
    let directResources = entries.filter(\.isDirectResource)

    let directoryItems = directories.enumerated().map { position, entry in
        let representative = entry.representativeResourceID.flatMap { resourcesByID[$0] }
        return WorkContentItemPresentation(
            entry: entry,
            kind: .sourceDirectory,
            resource: representative,
            cover: entry.cover ?? representative?.cover ?? detail.book.cover,
            title: entry.title,
            position: position,
            indexLabel: paddedWorkContentIndex(position)
        )
    }
    let resourceItems = directResources.enumerated().map { position, entry in
        let resource = entry.resourceID.flatMap { resourcesByID[$0] }
        return WorkContentItemPresentation(
            entry: entry,
            kind: .readableResource,
            resource: resource,
            cover: resource?.cover ?? entry.cover,
            title: resource?.title ?? entry.title,
            position: position,
            indexLabel: resource?.displayIndex(position: position) ?? paddedWorkContentIndex(position)
        )
    }
    return directoryItems + resourceItems
}

func workContentBreadcrumbs(
    bookTitle: String,
    page: BookContentsPage
) -> [WorkContentBreadcrumbPresentation] {
    [WorkContentBreadcrumbPresentation(title: bookTitle, sourceNodeID: nil)]
        + page.breadcrumbs.map {
            WorkContentBreadcrumbPresentation(title: $0.title, sourceNodeID: $0.sourceNodeID)
        }
}

func sourceDirectoryLabel(position: Int, locale: Locale = .current) -> String {
    String(
        format: String(localized: "work.contents.sourceDirectory.format", locale: locale),
        locale: locale,
        position + 1
    )
}

private func paddedWorkContentIndex(_ zeroBasedPosition: Int) -> String {
    String(format: "%02d", zeroBasedPosition + 1)
}

private struct ResourceCoverProgressView: View {
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
