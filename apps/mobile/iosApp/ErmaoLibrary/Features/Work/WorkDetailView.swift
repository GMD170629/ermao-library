import SwiftUI
@preconcurrency import ErmaoShared

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
    case management(WorkManagementTask)

    var id: String {
        switch self {
        case .shelves: "shelves"
        case .downloads: "downloads"
        case .management(let task): "management-\(task.id)"
        }
    }
}

private struct WorkDetailFeedback: Identifiable, Equatable {
    let id = UUID()
    let message: String
    let isError: Bool
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
    let managementRepository: (any ErmaoShared.WorkManagementRepository)?
    let canManageSystem: Bool

    @StateObject private var store: BookDetailStore
    @State private var activeSheet: WorkDetailSheet?
    @State private var shelves: [ShelfOption] = []
    @State private var selectedShelfIDs: Set<String> = []
    @State private var shelfRequestGeneration = UUID()
    @State private var isLoadingShelves = false
    @State private var isSavingShelves = false
    @State private var shelfError = false
    @State private var isDescriptionExpanded = false
    @State private var unavailableFeature: UnavailableWorkFeature?
    @State private var readerAccessErrorCode: String?
    @StateObject private var managementHolder: WorkManagementStoreHolder
    @State private var managedResourceID: String?
    @State private var readingStatusOverride: LibraryReadingStatus?
    @State private var feedback: WorkDetailFeedback?
    @State private var coverRefreshToken = 0
    @State private var downloadMenuRecord: ManagedDownloadRecord?
    @State private var pendingDownloadRemoval: ManagedDownloadRecord?
    @State private var controlTarget: WorkControlTarget?
    @State private var controlAnchor = CGPoint(x: 260, y: 220)
    @State private var latestPointerLocation = CGPoint(x: 260, y: 220)
    @Environment(\.appTheme) private var theme
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.locale) private var locale
    @Environment(\.dismiss) private var dismiss
    @State private var confirmsCoverRegeneration = false
    @State private var confirmsRescan = false
    @State private var confirmsDeletion = false
    @State private var deletionConfirmation = ""

    init(
        context: ContentRequestContext,
        client: any ContentClient,
        shelfClient: any ShelfClient,
        cache: LibraryCacheStore,
        downloads: DownloadCenterStore,
        managementRepository: (any ErmaoShared.WorkManagementRepository)? = nil,
        canManageSystem: Bool = false,
        bookID: String,
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
        self.openFacet = openFacet
        self.openDownloads = openDownloads
        self.openReader = openReader
        _store = StateObject(
            wrappedValue: BookDetailStore(
                context: context,
                client: client,
                cache: cache,
                bookID: bookID,
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
        ScrollView {
            AnyView(content)
                .padding(.horizontal, .space2)
                .padding(.bottom, .space4)
        }
        .accessibilityIdentifier("work.detail.screen")
        .safeAreaInset(edge: .bottom, spacing: 0) {
            Color.clear.frame(height: .space2)
        }
        .navigationTitle("work.detail.title")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.hidden, for: .navigationBar)
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
            case .management(let task):
                NavigationStack { managementPage(task: task) }
                    .presentationDetents([.large])
                    .presentationDragIndicator(.visible)
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
    }

    private var coverDialogScreen: some View {
        availabilityDialogScreen
        .confirmationDialog("management.regenerateCoverConfirmTitle", isPresented: $confirmsCoverRegeneration) {
            Button("management.regenerateCover") { regenerateBookCover() }
            Button("common.cancel", role: .cancel) {}
        } message: { Text("management.regenerateCoverConfirmMessage") }
    }

    private var downloadDialogScreen: some View {
        coverDialogScreen
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

    private var managementDialogScreen: some View {
        downloadDialogScreen
        .confirmationDialog("management.rescanConfirmTitle", isPresented: $confirmsRescan) {
            Button("management.rescan") { rescanBook() }
            Button("common.cancel", role: .cancel) {}
        } message: { Text("management.rescanConfirmMessage") }
        .alert("management.deleteConfirmTitle", isPresented: $confirmsDeletion) {
            TextField("management.deleteConfirmPlaceholder", text: $deletionConfirmation)
            Button("management.delete", role: .destructive) { deleteBook() }
                .disabled(deletionConfirmation != currentDetail?.book.title)
            Button("common.cancel", role: .cancel) { deletionConfirmation = "" }
        } message: { Text("management.deleteConfirmMessage") }
    }

    private var observedScreen: some View {
        managementDialogScreen
        .overlay { controlMenuOverlay }
        .overlay(alignment: .bottom) { feedbackBanner }
        .appCanvas()
        .task { store.load() }
        .onAppear { store.refreshIfLoaded() }
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

    private func handleManagementErrorChange(_ oldValue: String?, _ code: String?) {
        guard let code else { return }
        readingStatusOverride = nil
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
        case .ready(let detail, _):
            readyContent(detail)
        }
    }

    private func readyContent(_ detail: BookDetailContent) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            hero(detail)
                .padding(.top, .space1)
                .padding(.bottom, 18)

            readerAction(detail)
                .padding(.bottom, .space3)

            if normalizedDescription(detail) != nil {
                aboutSection(detail)
                    .padding(.bottom, .space3)
            }

            Divider().overlay(theme.divider.opacity(0.72))
            mediaSection(detail)
                .padding(.top, .space3)
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

    private func cover(_ detail: BookDetailContent) -> some View {
        BookCoverView(
            reference: detail.book.cover,
            title: detail.book.title,
            context: context,
            client: client,
            cache: cache,
            cornerRadius: CGFloat(GeneratedDesignTokens.Radii.coverHero)
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

            Spacer(minLength: .spaceHalf)
            progressSummary(detail)
                .frame(maxWidth: .infinity, alignment: .leading)
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
        let progress = detail.book.progress ?? detail.resources.compactMap(\.progress).max()
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

    private func readerAction(_ detail: BookDetailContent) -> some View {
        let selected = selectedResource(detail)
        let readingStatus = readingStatusOverride ?? detail.readingStatus ?? .unread
        let isAudio = selected?.readerType.lowercased() == "audio"
        return VStack(spacing: .space1) {
            PrimaryActionButton(
                isAudio
                    ? (detail.readingStatus == .reading ? "work.listener.continue.action" : "work.listener.start.action")
                    : (detail.readingStatus == .reading ? "work.reader.continue.action" : "work.reader.start.action"),
                systemImage: "play.fill",
                isDisabled: selected == nil || selected?.isReadable == false,
                action: { requestReaderAccess(detail: detail) }
            )
            .frame(height: 52)
            HStack(spacing: 0) {
                quickAction(downloadActionTitle(selected), systemImage: selected.map { downloadSystemImage(resourceID: $0.id) } ?? "arrow.down") {
                    handlePrimaryDownload(detail)
                }
                .accessibilityIdentifier("work.download.action")
                quickAction(readingStatus.title, systemImage: readingStatus == .finished ? "checkmark.circle.fill" : "checkmark") {
                    toggleBookReadingStatus(detail)
                }
                .disabled(managementStore?.isBusy == true)
                .accessibilityIdentifier("work.readingStatus.action")
                quickAction("work.action.add", systemImage: "bookmark") { openShelfPicker() }
                    .accessibilityIdentifier("work.shelf.action")
                bookControlMenu(detail)
            }
        }
    }

    private func bookControlMenu(_ detail: BookDetailContent) -> some View {
        let actions = controlActions(target: .book, detail: detail)
        return Menu {
            ForEach(actions) { action in
                Button(role: action.destructive ? .destructive : nil) {
                    action.perform()
                } label: {
                    Label {
                        Text(action.title)
                    } icon: {
                        Image(systemName: action.systemImage)
                    }
                }
                .disabled(!action.enabled)
            }
        } label: {
            quickActionLabel("common.more", systemImage: "ellipsis")
        }
        .menuOrder(.fixed)
        .buttonStyle(.plain)
        .frame(maxWidth: .infinity)
        .accessibilityIdentifier("work.book.moreMenu")
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
                Text("work.contents.title").appTextStyle(.sectionTitle)
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
                Button {
                    store.selectContentLayout(store.contentLayout == .grid ? .list : .grid)
                } label: {
                    Image(systemName: store.contentLayout == .grid ? "list.bullet" : "square.grid.2x2")
                        .frame(width: .iosMinimumTouchTarget, height: .iosMinimumTouchTarget)
                }
                .buttonStyle(.plain)
            }
            .padding(.bottom, .space1)

            if let page = store.contentsPage {
                contentBreadcrumbs(detail: detail, page: page)
                let entries = visibleContentEntries(page)
                if entries.isEmpty {
                    Text("work.contents.empty")
                        .appTextStyle(.body)
                        .foregroundStyle(theme.textTertiary)
                        .frame(maxWidth: .infinity, minHeight: 96, alignment: .center)
                } else if store.contentLayout == .grid {
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: .space2) {
                        ForEach(entries) { entry in
                            contentGridEntry(entry, detail: detail)
                        }
                    }
                } else {
                    VStack(spacing: 0) {
                        ForEach(entries) { entry in
                            if entry.isSourceFolder {
                                sourceFolderRow(entry)
                            } else if let resourceID = entry.resourceID,
                                      let resource = detail.resources.first(where: { $0.id == resourceID }) {
                                resourceListRow(resource, entry: entry, detail: detail)
                            } else if entry.isDirectResource {
                                unresolvedResourceRow(entry)
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

    private func contentGridEntry(_ entry: BookContentEntry, detail: BookDetailContent) -> some View {
        let resource = entry.resourceID.flatMap { id in detail.resources.first(where: { $0.id == id }) }
        return Button {
            if let resource { store.selectResource(resource.id) }
            else { store.openContents(entry.sourceNodeID) }
        } label: {
            VStack(alignment: .leading, spacing: .space1) {
                if let resource {
                    BookCoverView(
                        reference: entry.cover ?? resource.cover,
                        title: resource.title,
                        context: context,
                        client: client,
                        cache: cache
                    )
                    .frame(maxWidth: .infinity)
                } else {
                    Image(systemName: "folder.fill")
                        .font(.system(size: 34))
                        .foregroundStyle(Color.orange.opacity(0.88))
                        .frame(maxWidth: .infinity, minHeight: 150)
                        .background(theme.surface)
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
                Text(entry.title)
                    .appTextStyle(.body)
                    .fontWeight(.semibold)
                    .foregroundStyle(theme.textPrimary)
                    .lineLimit(2)
                Text(resource?.formatLabel ?? String(localized: "work.contents.folder"))
                    .appTextStyle(.caption)
                    .foregroundStyle(theme.textSecondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .buttonStyle(.plain)
    }

    private func visibleContentEntries(_ page: BookContentsPage) -> [BookContentEntry] {
        var entries = page.entries.filter { $0.isSourceFolder || $0.isDirectResource }
        if page.currentNode.isDirectResource,
           !entries.contains(where: { $0.id == page.currentNode.id }) {
            entries.insert(page.currentNode, at: 0)
        }
        return entries
    }

    private func contentBreadcrumbs(detail: BookDetailContent, page: BookContentsPage) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: .spaceHalf) {
                Button { store.openContents(nil) } label: {
                    Text(detail.book.title)
                }
                .buttonStyle(.plain)
                ForEach(page.breadcrumbs) { entry in
                    Image(systemName: "chevron.right")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(theme.textTertiary)
                    Button { store.openContents(entry.sourceNodeID) } label: {
                        Text(entry.title)
                    }
                    .buttonStyle(.plain)
                }
                if page.currentSourceNodeID != nil,
                   page.breadcrumbs.last?.sourceNodeID != page.currentNode.sourceNodeID {
                    Image(systemName: "chevron.right")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(theme.textTertiary)
                    Text(page.currentNode.title)
                }
            }
            .appTextStyle(.caption)
            .foregroundStyle(theme.textSecondary)
            .frame(minHeight: .iosMinimumTouchTarget)
        }
        .accessibilityLabel(Text("work.contents.breadcrumbs"))
    }

    private func sourceFolderRow(_ entry: BookContentEntry) -> some View {
        Button { store.openContents(entry.sourceNodeID) } label: {
            HStack(spacing: .space2) {
                Image(systemName: "folder.fill")
                    .font(.system(size: 30, weight: .regular))
                    .foregroundStyle(Color.orange.opacity(0.88))
                    .frame(width: 40, height: 40)
                VStack(alignment: .leading, spacing: .spaceHalf) {
                    Text(entry.title)
                        .appTextStyle(.body)
                        .fontWeight(.semibold)
                        .foregroundStyle(theme.textPrimary)
                        .lineLimit(1)
                    Text(entry.hasChildren ? "work.contents.folder.hasChildren" : "work.contents.folder.empty")
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
        .accessibilityIdentifier("work.contents.folder.\(entry.sourceNodeID)")
    }

    private func unresolvedResourceRow(_ entry: BookContentEntry) -> some View {
        Button {
            guard let resourceID = entry.resourceID else { return }
            store.selectResource(resourceID)
        } label: {
            HStack(spacing: .space2) {
                BookCoverView(
                    reference: entry.cover,
                    title: entry.title,
                    context: context,
                    client: client,
                    cache: cache
                )
                .frame(width: 40)
                VStack(alignment: .leading, spacing: .spaceHalf) {
                    Text(entry.title)
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
        detail: BookDetailContent
    ) -> some View {
        HStack(spacing: .space1) {
            Text(resourceDisplayIndex(resource, detail: detail))
                .appTextStyle(.caption)
                .monospacedDigit()
                .foregroundStyle(resource.isSelected ? theme.brandAccent : theme.textSecondary)
                .frame(width: 28, alignment: .leading)

            Button { store.selectResource(resource.id) } label: {
                HStack(spacing: .space2) {
                    BookCoverView(
                        reference: entry?.cover ?? resource.cover,
                        title: resource.title,
                        context: context,
                        client: client,
                        cache: cache
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
                Button { store.openContents(entry?.sourceNodeID) } label: {
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
        VStack(alignment: .leading, spacing: 0) {
            if detail.resources.filter({ $0.isReadable != false }).count > 1 {
                Button { store.showContentBrowser() } label: {
                    Label("work.contents.back", systemImage: "arrow.left")
                }
                .buttonStyle(.plain)
                .foregroundStyle(theme.textSecondary)
                .frame(minHeight: .iosMinimumTouchTarget)
            }
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
                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: .space2) {
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

    private func resourcePageTile(_ unit: BookResourceDetailUnit, detail: BookDetailContent) -> some View {
        Button { requestReaderAccess(detail: detail) } label: {
            VStack(alignment: .leading, spacing: .space1) {
                if let previewURL = unit.previewURL, !previewURL.isEmpty {
                    BookCoverView(
                        reference: CoverReference(path: previewURL),
                        title: unit.title,
                        context: context,
                        client: client,
                        cache: cache
                    )
                    .frame(maxWidth: .infinity)
                } else {
                    Image(systemName: "photo")
                        .frame(maxWidth: .infinity, minHeight: 150)
                        .background(theme.surface)
                }
                Text(unit.title.isEmpty
                     ? String(format: String(localized: "work.resource.page.format"), unit.pageNumber ?? unit.sortOrder + 1)
                     : unit.title)
                    .appTextStyle(.body)
                    .foregroundStyle(theme.textPrimary)
                    .lineLimit(1)
            }
        }
        .buttonStyle(.plain)
    }

    private func resourceUnitRow(
        _ unit: BookResourceDetailUnit,
        displayIndex: Int,
        detail: BookDetailContent
    ) -> some View {
        Button { requestReaderAccess(detail: detail) } label: {
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
        Button { requestReaderAccess(detail: detail) } label: {
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
                    store.selectResource(resource.id)
                } label: {
                    BookCoverView(
                        reference: resource.cover,
                        title: resource.title,
                        context: context,
                        client: client,
                        cache: cache
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
                .onLongPressGesture {
                    controlAnchor = latestPointerLocation
                    controlTarget = .resource(resource.id)
                }
                .simultaneousGesture(
                    DragGesture(minimumDistance: 0, coordinateSpace: .global)
                        .onChanged { latestPointerLocation = $0.location }
                )
                .accessibilityAction(named: Text("management.volume")) {
                    controlAnchor = latestPointerLocation
                    controlTarget = .resource(resource.id)
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
        let rows: [(LocalizedStringKey, String?)] = [
            ("work.metadata.format", resource.formatLabel),
            ("work.metadata.language", resource.language),
            ("work.metadata.published", formattedMetadataDate(resource.publishedAt)),
            ("work.metadata.pages", resource.pageCount.map(String.init)),
            ("work.metadata.source", resource.metadataSource),
            ("work.metadata.filePath", resource.assets.first?.path),
        ]
        return VStack(alignment: .leading, spacing: 0) {
            Text("work.metadata.title")
                .appTextStyle(.label)
                .fontWeight(.semibold)
                .foregroundStyle(theme.textSecondary)
                .padding(.bottom, .space1)
            ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                HStack(alignment: .firstTextBaseline, spacing: .space2) {
                    Text(row.0).appTextStyle(.caption).foregroundStyle(theme.textSecondary)
                    Spacer(minLength: .space1)
                    Text(metadataValue(row.1))
                        .appTextStyle(.callout)
                        .multilineTextAlignment(.trailing)
                        .lineLimit(2)
                }
                .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget)
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
            ?? detail.resources.first(where: \.isSelected)
            ?? detail.resources.first
    }

    private func kindleAsset(_ asset: ResourceAsset) -> Bool {
        let path = asset.path.lowercased()
        return path.hasSuffix(".epub") || path.hasSuffix(".pdf")
    }

    private var currentDetail: BookDetailContent? {
        guard case .ready(let detail, _) = store.state else { return nil }
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

    private func controlMenuCard(target: WorkControlTarget, detail: BookDetailContent) -> some View {
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
        .accessibilityIdentifier(target == .book ? "work.book.controlMenu" : "work.resource.controlMenu")
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

    private func controlMenuHeader(target: WorkControlTarget, detail: BookDetailContent) -> some View {
        let resource = controlResource(target: target, detail: detail)
        return HStack(spacing: .space1) {
            Group {
                if let resource {
                    BookCoverView(
                        reference: resource.cover,
                        title: resource.title,
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
                Text(target == .book ? detail.book.title : (resource?.title ?? detail.book.title))
                    .appTextStyle(.body)
                    .fontWeight(.semibold)
                    .foregroundStyle(theme.textPrimary)
                    .lineLimit(1)
                if let resource {
                    Text("\(resource.title) · \(resource.formatLabel)")
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
        detail: BookDetailContent
    ) -> [WorkControlAction] {
        let resource = controlResource(target: target, detail: detail)
        let download = resource.flatMap { downloads.record(for: $0.id) }
        let activeDownload = download.map { record in
            [.queued, .downloading].contains(record.state)
        } ?? false
        let downloadTitle: LocalizedStringKey = download?.isVerifiedOfflineCopy == true
            ? "downloads.remove.action"
            : activeDownload ? "work.download.pause" : "work.action.download"
        let downloadIcon = activeDownload ? "pause.circle" : "icloud.and.arrow.down"
        let kindleEligible = resource?.assets.contains(where: kindleAsset) == true
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
                let managementAvailable = managementStore != nil
                actions.append(action("edit", "work.control.edit", "pencil", enabled: managementAvailable) { openManagement(.editWork, resourceID: nil) })
                actions.append(action("regenerateCover", "management.regenerateCover", "photo.badge.arrow.down", enabled: managementAvailable) {
                    openManagement(.cover, resourceID: resource?.id)
                })
                actions.append(action("recognize", "work.control.recognize", "text.magnifyingglass", enabled: managementAvailable) { openManagement(.recognize, resourceID: nil) })
                actions.append(action("rescan", "management.rescan", "arrow.clockwise", enabled: managementAvailable) { controlTarget = nil; confirmsRescan = true })
                actions.append(action("delete", "management.delete", "trash", enabled: managementAvailable, destructive: true) { controlTarget = nil; confirmsDeletion = true })
            }
        } else if let resource {
            actions.append(action("unread", "work.control.markUnread", "bookmark") { markUnread(resource) })
            actions.append(action("download", downloadTitle, downloadIcon) {
                handleControlDownload(resource, detail: detail)
            })
            if managementStore != nil && canManageSystem {
                actions.append(action("edit", "work.control.edit", "pencil") { openManagement(.editResource, resourceID: resource.id) })
            }
            if canManageSystem && kindleEligible {
                actions.append(action("kindle", "management.kindle", "paperplane") { openManagement(.kindle, resourceID: resource.id) })
            }
        }
        return actions
    }

    private func controlResource(target: WorkControlTarget, detail: BookDetailContent) -> BookResource? {
        switch target {
        case .book: selectedResource(detail)
        case .resource(let id): detail.resources.first { $0.id == id }
        }
    }

    private func openManagement(_ task: WorkManagementTask, resourceID: String?) {
        guard task == .kindle || managementStore != nil else {
            showFeedback(String(localized: "management.unavailable"), isError: true)
            return
        }
        controlTarget = nil
        managedResourceID = resourceID
        activeSheet = .management(task)
    }

    private func markUnread(_ resource: BookResource?) {
        controlTarget = nil
        guard let resource, let managementStore else {
            unavailableFeature = .readingStatus
            return
        }
        managementStore.setReadingStatus(resourceID: resource.id, status: .unread)
    }

    private func handleControlDownload(_ resource: BookResource?, detail: BookDetailContent) {
        controlTarget = nil
        guard let resource else { return }
        if let record = downloads.record(for: resource.id), record.isVerifiedOfflineCopy {
            downloadMenuRecord = record
        } else {
            handleDownload(resource, detail: detail)
        }
    }

    @ViewBuilder
    private func managementPage(task: WorkManagementTask) -> some View {
        if (task == .kindle || managementStore != nil),
           let managementStore,
           let detail = currentDetail {
            let resource = managedResourceID.flatMap { id in detail.resources.first { $0.id == id } }
            WorkManagementView(
                store: managementStore,
                task: task,
                detail: detail,
                resource: resource,
                workCover: AnyView(managementCover(detail: detail, resource: resource)),
                downloadForResource: { downloads.record(for: $0) }
            )
        }
    }

    @ViewBuilder
    private func managementCover(detail: BookDetailContent, resource: BookResource?) -> some View {
        if let resource {
            BookCoverView(
                reference: resource.cover,
                title: resource.title,
                context: context,
                client: client,
                cache: cache,
                cornerRadius: CGFloat(GeneratedDesignTokens.Radii.coverHero)
            )
            .id("management-cover-\(coverRefreshToken)")
        } else {
            cover(detail)
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
        store.load()
    }

    private func toggleBookReadingStatus(_ detail: BookDetailContent) {
        guard let managementStore else { unavailableFeature = .readingStatus; return }
        let current = readingStatusOverride ?? detail.readingStatus ?? .unread
        let next: LibraryReadingStatus = current == .finished ? .unread : .finished
        readingStatusOverride = next
        managementStore.setBookReadingStatus(next == .finished ? .finished : .unread)
    }

    private func regenerateBookCover() {
        guard let resourceID = currentDetail.flatMap(selectedResource)?.id else {
            showFeedback(String(localized: "management.missingSourceNode"), isError: true)
            return
        }
        managementStore?.regenerateBookCover(anchoredResourceID: resourceID)
    }

    private func rescanBook() {
        guard let sourceNodeID = currentDetail.flatMap(selectedResource)?.sourceNodeID,
              !sourceNodeID.isEmpty else {
            showFeedback(String(localized: "management.missingSourceNode"), isError: true)
            return
        }
        managementStore?.rescanBook(sourceNodeID: sourceNodeID)
    }

    private func deleteBook() {
        guard deletionConfirmation == currentDetail?.book.title else { return }
        deletionConfirmation = ""
        managementStore?.deleteBook()
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

    private func requestReaderAccess(detail: BookDetailContent) {
        guard let resource = selectedResource(detail) else { return }
        if let handoff = ManagedReaderAccessPolicy.verifiedLocalHandoff(
            record: downloads.record(for: resource.id),
            resourceID: resource.id
        ) {
            openReader(handoff)
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
            source: .remoteStream
        ))
    }

    private func requestReaderAccessForSelectedResource() {
        guard case .ready(let detail, _) = store.state else { return }
        requestReaderAccess(detail: detail)
    }

    private func downloadFailureMessage(_ code: String) -> String {
        if code == "DOWNLOAD_BOOTSTRAP_INVALID" {
            return String(localized: "download.bootstrap.invalid")
        }
        return String(format: String(localized: "work.download.failed.format"), code)
    }

    private func handlePrimaryDownload(_ detail: BookDetailContent) {
        let downloadableResources = detail.resources.filter { $0.isReadable != false }
        if downloadableResources.count > 1 || (store.contentsPage?.currentResourceIDs.count ?? 0) > 1 {
            activeSheet = .downloads
            return
        }
        guard let resource = selectedResource(detail) else {
            showFeedback(String(localized: "work.download.unavailable"), isError: true)
            return
        }
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
        case .queued, .downloading: return "work.download.pause"
        case .paused, .failedRetryable, .failedTerminal: return "work.download.resume"
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
        guard let record = downloads.record(for: resourceID) else { return "icloud.and.arrow.down" }
        switch record.state {
        case .queued, .downloading: return "pause.circle"
        case .paused, .failedRetryable, .failedTerminal: return "arrow.clockwise.circle"
        case .completed:
            return record.isVerifiedOfflineCopy ? "checkmark.circle.fill" : "exclamationmark.circle"
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
