import SwiftUI

struct LibraryView: View {
    let context: ContentRequestContext
    let client: any ContentClient
    let cache: LibraryCacheStore
    let openWork: (String) -> Void
    let openFacet: (FacetKind, String) -> Void

    @StateObject private var store: LibraryStore
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.appTheme) private var theme
    @State private var presentsFilter = false
    @AccessibilityFocusState private var filterButtonFocused: Bool

    init(
        context: ContentRequestContext,
        client: any ContentClient,
        cache: LibraryCacheStore,
        onUnauthorized: @escaping @MainActor () -> Void,
        openWork: @escaping (String) -> Void,
        openFacet: @escaping (FacetKind, String) -> Void
    ) {
        self.context = context
        self.client = client
        self.cache = cache
        self.openWork = openWork
        self.openFacet = openFacet
        _store = StateObject(
            wrappedValue: LibraryStore(
                context: context,
                client: client,
                cache: cache,
                onUnauthorized: onUnauthorized
            )
        )
    }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: .space2) {
                scopePicker
                resultsHeader
                resultContent
            }
            .padding(.horizontal, .space2)
            .padding(.bottom, .space4)
        }
        .refreshable { store.refresh() }
        .navigationTitle("tab.library")
        .navigationBarTitleDisplayMode(.large)
        .accessibilityIdentifier("library.screen")
        .searchable(
            text: Binding(
                get: { store.current.query },
                set: { value in store.setQuery(value) }
            ),
            placement: .navigationBarDrawer(displayMode: .always),
            prompt: Text(searchPrompt)
        )
        .toolbar { libraryToolbar }
        .sheet(isPresented: $presentsFilter) {
            LibraryFilterSheet(
                applied: store.current.filters,
                offlineAvailability: store.offlineFilterAvailability,
                onApply: store.applyFilters
            )
            .presentationDetents([.medium, .large])
        }
        .onChange(of: presentsFilter) { isPresented in
            if !isPresented { filterButtonFocused = true }
        }
        .appCanvas()
        .task { store.reload() }
    }

    private var searchPrompt: LocalizedStringKey {
        switch store.selectedScope {
        case .works: "library.search.works"
        case .series: "library.search.series"
        case .authors: "library.search.authors"
        }
    }

    private var scopePicker: some View {
        Picker("library.scope.accessibility", selection: Binding(
            get: { store.selectedScope },
            set: { scope in
                guard scope != store.selectedScope else { return }
                store.selectScope(scope)
            }
        )) {
            Text("library.scope.works").tag(LibraryScope.works)
            Text("library.scope.series").tag(LibraryScope.series)
            Text("library.scope.authors").tag(LibraryScope.authors)
        }
        .pickerStyle(.segmented)
    }

    @ViewBuilder
    private var resultsHeader: some View {
        VStack(alignment: .leading, spacing: .space1) {
            HStack(spacing: .space1) {
                if case .ready(_, let total, _, _) = store.current.results {
                    Text(String(format: NSLocalizedString(resultCountKey, comment: ""), locale: .current, total))
                        .appTextStyle(.label)
                        .foregroundStyle(theme.textSecondary)
                }
                if case .ready(_, _, _, let refreshing) = store.current.results,
                   refreshing {
                    ProgressView()
                        .controlSize(.small)
                        .tint(theme.brandAccent)
                        .accessibilityLabel(Text("library.stale.refreshing"))
                }
                Spacer()
                if store.selectedScope == .works {
                    Button {
                        presentsFilter = true
                    } label: {
                        Label(
                            store.current.filters.isEmpty
                                ? "library.filter.action"
                                : "library.filter.active.action",
                            systemImage: "line.3.horizontal.decrease"
                        )
                        .appTextStyle(.label)
                        .foregroundStyle(
                            store.current.filters.isEmpty
                                ? theme.textSecondary
                                : theme.actionAccent
                        )
                        .frame(minHeight: .iosMinimumTouchTarget)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityValue(Text("\(store.current.filters.count)"))
                    .accessibilityFocused($filterButtonFocused)
                }
            }

            if store.selectedScope == .works, !store.current.filters.isEmpty {
                VStack(alignment: .leading, spacing: .spaceHalf) {
                    ForEach(activeMediaFilters, id: \.self) { mediaKind in
                        appliedFilterButton(mediaKind.localizedTitle) {
                            store.removeMediaFilter(mediaKind)
                        }
                    }
                    ForEach(activeReadingFilters, id: \.self) { readingStatus in
                        appliedFilterButton(readingStatus.localizedTitle) {
                            store.removeReadingFilter(readingStatus)
                        }
                    }
                }
            }

        }
        .frame(minHeight: .iosMinimumTouchTarget, alignment: .top)
    }

    private var activeMediaFilters: [LibraryMediaKind] {
        [LibraryMediaKind.ebook, .comic, .audiobook].filter(store.current.filters.mediaKinds.contains)
    }

    private var activeReadingFilters: [LibraryReadingStatus] {
        [LibraryReadingStatus.unread, .reading, .finished].filter(store.current.filters.readingStatuses.contains)
    }

    private func appliedFilterButton(_ title: String, remove: @escaping () -> Void) -> some View {
        Button(action: remove) {
            HStack(spacing: .space1) {
                Text(title)
                    .appTextStyle(.label)
                    .fixedSize(horizontal: false, vertical: true)
                Image(systemName: "xmark")
                    .font(.caption.weight(.semibold))
                    .accessibilityHidden(true)
            }
            .foregroundStyle(theme.actionAccent)
            .frame(minHeight: .iosMinimumTouchTarget)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(
            Text(String(format: String(localized: "library.filter.remove.format"), locale: .current, title))
        )
    }

    private var resultCountKey: String {
        switch store.selectedScope {
        case .works: "library.results.works.format"
        case .series: "library.results.series.format"
        case .authors: "library.results.authors.format"
        }
    }

    @ViewBuilder
    private var resultContent: some View {
        switch store.current.results {
        case .idle, .loading:
            HStack { Spacer(); ProgressView(); Spacer() }.frame(minHeight: 360)
        case .failure:
            ContentStatusView(
                systemImage: "wifi.exclamationmark",
                title: "library.error.title",
                message: "library.error.message",
                actionTitle: "common.retry",
                action: store.reload
            )
            .frame(minHeight: 360)
        case .permissionRevalidating:
            ContentStatusView(
                systemImage: "lock.shield",
                title: "library.permission.revalidating.title",
                message: "library.permission.revalidating.message"
            )
            .overlay(alignment: .top) { ProgressView().padding(.top, .space2) }
            .frame(minHeight: 360)
        case .inaccessible:
            ContentStatusView(
                systemImage: "eye.slash",
                title: "content.inaccessible.title",
                message: "content.inaccessible.message"
            )
            .frame(minHeight: 360)
        case .empty:
            emptyResultsView
        case .ready(let items, _, _, _):
            if store.selectedScope == .works {
                worksContent(items.compactMap(\.work))
            } else {
                groupingContent(items.compactMap(\.grouping))
            }
            PaginationStatusView(
                isLoading: store.current.isLoadingNextPage,
                hasError: store.current.hasPaginationError,
                retry: store.retryNextPage
            )
        }
    }

    @ViewBuilder
    private var emptyResultsView: some View {
        if store.current.query.isEmpty {
            ContentStatusView(
                systemImage: "book.closed",
                title: emptyTitle,
                message: "library.empty.message"
            )
            .frame(minHeight: 360)
        } else {
            ContentStatusView(
                systemImage: "book.closed",
                title: emptyTitle,
                message: "library.empty.message",
                actionTitle: "library.search.clear",
                action: store.clearSearch
            )
            .frame(minHeight: 360)
        }
    }

    private var emptyTitle: LocalizedStringKey {
        switch store.selectedScope {
        case .works: "library.empty.works.title"
        case .series: "library.empty.series.title"
        case .authors: "library.empty.authors.title"
        }
    }

    @ViewBuilder
    private func worksContent(_ works: [WorkCard]) -> some View {
        if store.current.viewMode == .list || dynamicTypeSize.isAccessibilitySize {
            WorkList(
                works: works,
                context: context,
                client: client,
                cache: cache,
                onSelect: openWork,
                onAppearWork: appeared
            )
        } else {
            WorkGrid(
                works: works,
                context: context,
                client: client,
                cache: cache,
                columns: dynamicTypeSize >= .xxLarge ? 2 : 3,
                onSelect: openWork,
                onAppearWork: { appeared("work:\($0)") }
            )
        }
    }

    private func groupingContent(_ groups: [LibraryGrouping]) -> some View {
        LazyVStack(spacing: 0) {
            ForEach(groups) { group in
                Button {
                    openFacet(group.kind, group.id)
                } label: {
                    HStack(spacing: .space2) {
                        GroupingCoverStackView(
                            works: group.representativeWorks,
                            context: context,
                            client: client,
                            cache: cache,
                            isCompact: dynamicTypeSize >= .xxLarge
                        )
                        VStack(alignment: .leading, spacing: .spaceHalf) {
                            Text(group.name)
                                .appTextStyle(.headline)
                                .foregroundStyle(theme.textPrimary)
                                .lineLimit(2)
                            Text(groupSummary(group))
                                .appTextStyle(.label)
                                .foregroundStyle(theme.textSecondary)
                                .lineLimit(2)
                        }
                        Spacer(minLength: 0)
                        Image(systemName: "chevron.forward")
                            .foregroundStyle(theme.textTertiary)
                            .accessibilityHidden(true)
                    }
                    .padding(.vertical, .space1Half)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.borderless)
                .accessibilityIdentifier("facet.\(group.kind.rawValue.lowercased()).\(group.id)")
                .id("group:\(group.id)")
                .onAppear { appeared("group:\(group.id)") }
                Divider()
            }
        }
    }

    private func groupSummary(_ group: LibraryGrouping) -> String {
        if group.kind == .author {
            return String(
                format: String(localized: "library.group.workCount.format"),
                locale: .current,
                group.workCount
            )
        }
        let author = group.representativeWorks.first?.author.trimmingCharacters(in: .whitespacesAndNewlines)
        if let author, !author.isEmpty {
            return String(
                format: String(localized: "library.group.summary.format"),
                locale: .current,
                author,
                group.workCount
            )
        }
        return String(
            format: String(localized: "library.group.workCount.format"),
            locale: .current,
            group.workCount
        )
    }

    private func appeared(_ identifier: String) {
        store.rememberAnchor(identifier)
        store.loadNextPageIfNeeded(visibleItemID: identifier)
    }

    @ToolbarContentBuilder
    private var libraryToolbar: some ToolbarContent {
        if store.selectedScope == .works {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Section("library.sort.section") {
                        ForEach(
                            [LibrarySort.recentAdded, .recentRead, .title, .author],
                            id: \.self
                        ) { sort in
                            Button {
                                store.setSort(sort)
                            } label: {
                                if store.current.sort == sort {
                                    Label(sort.title, systemImage: "checkmark")
                                } else {
                                    Text(sort.title)
                                }
                            }
                        }
                    }
                    Section("library.view.section") {
                        Button {
                            store.setViewMode(.grid)
                        } label: {
                            Label("library.view.grid", systemImage: store.current.viewMode == .grid ? "checkmark" : "square.grid.3x2")
                        }
                        Button {
                            store.setViewMode(.list)
                        } label: {
                            Label("library.view.list", systemImage: store.current.viewMode == .list ? "checkmark" : "list.bullet")
                        }
                    }
                } label: {
                    Image(systemName: "ellipsis")
                }
                .accessibilityLabel(Text("common.more"))
            }
        }
    }
}

struct WorkCollectionView: View {
    let context: ContentRequestContext
    let client: any ContentClient
    let cache: LibraryCacheStore
    let kind: HomeCollectionKind
    let openWork: (String) -> Void

    @StateObject private var store: LibraryStore
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(
        context: ContentRequestContext,
        client: any ContentClient,
        cache: LibraryCacheStore,
        kind: HomeCollectionKind,
        onUnauthorized: @escaping @MainActor () -> Void,
        openWork: @escaping (String) -> Void
    ) {
        self.context = context
        self.client = client
        self.cache = cache
        self.kind = kind
        self.openWork = openWork
        _store = StateObject(
            wrappedValue: LibraryStore(
                context: context,
                client: client,
                cache: cache,
                onUnauthorized: onUnauthorized
            )
        )
    }

    var body: some View {
        ScrollView {
            LazyVStack(spacing: .space2) {
                collectionContent
                PaginationStatusView(
                    isLoading: store.current.isLoadingNextPage,
                    hasError: store.current.hasPaginationError,
                    retry: store.retryNextPage
                )
            }
            .padding(.horizontal, .space2)
            .padding(.bottom, .space4)
        }
        .navigationTitle(kind == .recentReading ? "home.recentReading.title" : "home.recentAdded.title")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable { store.refresh() }
        .appCanvas()
        .task {
            store.setSort(kind == .recentReading ? .recentRead : .recentAdded)
            store.reloadIfNeeded()
        }
    }

    @ViewBuilder
    private var collectionContent: some View {
        switch store.current.results {
        case .idle, .loading:
            HStack { Spacer(); ProgressView(); Spacer() }.frame(minHeight: 300)
        case .empty:
            ContentStatusView(
                systemImage: "books.vertical",
                title: "home.section.empty.title",
                message: "home.section.empty.message"
            )
        case .failure, .permissionRevalidating, .inaccessible:
            ContentStatusView(
                systemImage: "wifi.exclamationmark",
                title: "library.error.title",
                message: "library.error.message",
                actionTitle: "common.retry",
                action: store.reload
            )
        case .ready(let items, _, _, _):
            WorkGrid(
                works: items.compactMap(\.work),
                context: context,
                client: client,
                cache: cache,
                columns: dynamicTypeSize.isAccessibilitySize ? 2 : 3,
                onSelect: openWork,
                onAppearWork: { store.loadNextPageIfNeeded(visibleItemID: "work:\($0)") }
            )
        }
    }
}

private extension LibraryResultItem {
    var work: WorkCard? {
        guard case .work(let value) = self else { return nil }
        return value
    }

    var grouping: LibraryGrouping? {
        guard case .grouping(let value) = self else { return nil }
        return value
    }
}

private extension LibrarySort {
    var title: LocalizedStringKey {
        switch self {
        case .recentAdded: "library.sort.recentAdded"
        case .recentRead: "library.sort.recentRead"
        case .title: "library.sort.title"
        case .author: "library.sort.author"
        }
    }
}

private struct GroupingCoverStackView: View {
    let works: [WorkCard]
    let context: ContentRequestContext
    let client: any ContentClient
    let cache: LibraryCacheStore
    let isCompact: Bool

    private var coverWidth: CGFloat { isCompact ? 44 : 56 }
    private var coverOffset: CGFloat { isCompact ? 20 : 26 }
    private var previewWidth: CGFloat { isCompact ? 88 : 112 }
    private var previewHeight: CGFloat { coverWidth * 1.5 }

    var body: some View {
        ZStack(alignment: .leading) {
            ForEach(Array(works.prefix(3).enumerated()), id: \.element.id) { index, work in
                BookCoverView(
                    reference: work.cover,
                    title: work.title,
                    context: context,
                    client: client,
                    cache: cache
                )
                .frame(width: coverWidth)
                .offset(x: CGFloat(index) * coverOffset)
                .zIndex(Double(3 - index))
            }
            if works.isEmpty {
                RoundedRectangle(cornerRadius: CGFloat(GeneratedDesignTokens.Radii.coverCompact))
                    .fill(Color.secondary.opacity(0.12))
                    .aspectRatio(2 / 3, contentMode: .fit)
                    .frame(width: coverWidth)
                    .overlay(Image(systemName: "books.vertical").foregroundStyle(Color.secondary))
            }
        }
        .frame(width: previewWidth, height: previewHeight, alignment: .leading)
        .accessibilityHidden(true)
    }
}

private struct LibraryFilterSheet: View {
    let onApply: (LibraryFilters) -> Void
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appTheme) private var theme
    @State private var draft: LibraryFilters

    init(
        applied: LibraryFilters,
        offlineAvailability: OfflineFilterAvailability,
        onApply: @escaping (LibraryFilters) -> Void
    ) {
        self.onApply = onApply
        _ = offlineAvailability
        var normalized = applied
        normalized.downloadedOnly = false
        _draft = State(initialValue: normalized)
    }

    var body: some View {
        NavigationStack {
            List {
                Section("library.filter.media.section") {
                    filterRow("library.media.ebook", value: .ebook, selection: $draft.mediaKinds)
                    filterRow("library.media.comic", value: .comic, selection: $draft.mediaKinds)
                    filterRow("library.media.audiobook", value: .audiobook, selection: $draft.mediaKinds)
                }
                Section("library.filter.reading.section") {
                    filterRow("library.reading.unread", value: .unread, selection: $draft.readingStatuses)
                    filterRow("library.reading.reading", value: .reading, selection: $draft.readingStatuses)
                    filterRow("library.reading.finished", value: .finished, selection: $draft.readingStatuses)
                }
            }
            .listStyle(.insetGrouped)
            .scrollContentBackground(.hidden)
            .background(theme.canvas)
            .safeAreaInset(edge: .bottom) {
                PrimaryActionButton("library.filter.apply") {
                    onApply(draft)
                    dismiss()
                }
                .padding(.horizontal, .space2)
                .padding(.vertical, .space1)
                .background(theme.canvas)
            }
            .navigationTitle("library.filter.title")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("common.cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("library.filter.clear") { draft = LibraryFilters() }
                        .disabled(draft.isEmpty)
                }
            }
            .tint(theme.actionAccent)
        }
    }

    private func filterRow<Value: Hashable>(
        _ title: LocalizedStringKey,
        value: Value,
        selection: Binding<Set<Value>>
    ) -> some View {
        Button {
            if selection.wrappedValue.contains(value) {
                selection.wrappedValue.remove(value)
            } else {
                selection.wrappedValue.insert(value)
            }
        } label: {
            HStack {
                Text(title).foregroundStyle(Color.primary)
                Spacer()
                if selection.wrappedValue.contains(value) {
                    Image(systemName: "checkmark.square.fill")
                        .foregroundStyle(theme.brandAccent)
                        .accessibilityHidden(true)
                } else {
                    Image(systemName: "square")
                        .foregroundStyle(theme.textTertiary)
                        .accessibilityHidden(true)
                }
            }
            .frame(minHeight: .iosMinimumTouchTarget)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selection.wrappedValue.contains(value) ? .isSelected : [])
    }
}

private extension LibraryMediaKind {
    var localizedTitle: String {
        switch self {
        case .ebook: String(localized: "library.media.ebook")
        case .comic: String(localized: "library.media.comic")
        case .audiobook: String(localized: "library.media.audiobook")
        }
    }
}

private extension LibraryReadingStatus {
    var localizedTitle: String {
        switch self {
        case .unread: String(localized: "library.reading.unread")
        case .reading: String(localized: "library.reading.reading")
        case .finished: String(localized: "library.reading.finished")
        }
    }
}
