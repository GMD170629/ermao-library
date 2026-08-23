import SwiftUI

struct FacetView: View {
    let context: ContentRequestContext
    let client: any ContentClient
    let cache: LibraryCacheStore
    let kind: FacetKind
    let facetID: String
    let openWork: (String) -> Void

    @StateObject private var store: FacetStore
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.appTheme) private var theme

    init(
        context: ContentRequestContext,
        client: any ContentClient,
        cache: LibraryCacheStore,
        kind: FacetKind,
        facetID: String,
        onUnauthorized: @escaping @MainActor () -> Void,
        openWork: @escaping (String) -> Void
    ) {
        self.context = context
        self.client = client
        self.cache = cache
        self.kind = kind
        self.facetID = facetID
        self.openWork = openWork
        _store = StateObject(
            wrappedValue: FacetStore(
                context: context,
                client: client,
                cache: cache,
                kind: kind,
                facetID: facetID,
                onUnauthorized: onUnauthorized
            )
        )
    }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: .space2) {
                content
            }
            .padding(.horizontal, .space2)
            .padding(.bottom, .space4)
        }
        .accessibilityIdentifier("facet.screen")
        .navigationTitle(kind == .series ? "facet.series.title" : "facet.author.title")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable { store.load() }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Button("common.refresh", systemImage: "arrow.clockwise") { store.load() }
                } label: { Image(systemName: "ellipsis") }
                .accessibilityLabel(Text("common.more"))
            }
        }
        .appCanvas()
        .task { store.load() }
    }

    @ViewBuilder
    private var content: some View {
        switch store.state {
        case .loading:
            HStack { Spacer(); ProgressView(); Spacer() }.frame(minHeight: 300)
        case .failure:
            ContentStatusView(
                systemImage: "wifi.exclamationmark",
                title: "facet.error.title",
                message: "facet.error.message",
                actionTitle: "common.retry",
                action: store.retry
            )
        case .inaccessible:
            ContentStatusView(
                systemImage: "eye.slash",
                title: "content.inaccessible.title",
                message: "content.inaccessible.message"
            )
        case .empty(let identity):
            identityHeader(identity, count: 0, isCached: false)
            ContentStatusView(
                systemImage: "books.vertical",
                title: "facet.empty.title",
                message: "facet.empty.message"
            )
        case .ready(let page, let cached):
            identityHeader(page.facet, count: page.total, isCached: cached)
            if kind == .series {
                seriesWorks(page.books)
            } else {
                WorkGrid(
                    works: page.books,
                    context: context,
                    client: client,
                    cache: cache,
                    columns: dynamicTypeSize.isAccessibilitySize ? 2 : 3,
                    onSelect: openWork,
                    onAppearWork: store.loadNextPageIfNeeded
                )
            }
            PaginationStatusView(
                isLoading: store.isLoadingNextPage,
                hasError: store.hasPaginationError,
                retry: store.retry
            )
        }
    }

    private func identityHeader(_ identity: FacetIdentity, count: Int, isCached: Bool) -> some View {
        VStack(alignment: .leading, spacing: .space1) {
            VStack(alignment: .leading, spacing: .space1) {
                Text(identity.name)
                    .appTextStyle(.title)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: .space1) {
                    Text(String(format: NSLocalizedString("facet.workCount.format", comment: ""), count))
                        .appTextStyle(.label)
                        .foregroundStyle(theme.textSecondary)
                }
                Text(kind == .series ? "facet.sort.seriesIndex" : "facet.sort.recentRead")
                    .appTextStyle(.caption)
                    .foregroundStyle(theme.textTertiary)
            }
            .accessibilityElement(children: .combine)
            if isCached {
                ContentOfflineNotice(retry: store.load)
                    .padding(.top, .spaceHalf)
            }
            Divider()
        }
        .padding(.top, .space1)
    }

    private func seriesWorks(_ works: [BookCard]) -> some View {
        LazyVStack(spacing: 0) {
            ForEach(Array(works.enumerated()), id: \.element.id) { index, work in
                Button { openWork(work.id) } label: {
                    HStack(spacing: .space2) {
                        BookCoverView(
                            reference: work.cover,
                            title: work.title,
                            context: context,
                            client: client,
                            cache: cache
                        )
                        .frame(width: dynamicTypeSize >= .xxLarge ? 72 : 96)
                        VStack(alignment: .leading, spacing: .spaceHalf) {
                            Text(work.title)
                                .appTextStyle(.headline)
                                .foregroundStyle(theme.textPrimary)
                                .lineLimit(2)
                            Text(work.author ?? "—")
                                .appTextStyle(.label)
                                .foregroundStyle(theme.textSecondary)
                                .lineLimit(1)
                            if !work.availableMediaKinds.isEmpty {
                                Text(mediaSummary(for: work))
                                    .appTextStyle(.caption)
                                    .foregroundStyle(theme.textSecondary)
                                    .lineLimit(1)
                            }
                            if let progress = work.progress, progress > 0 {
                                VStack(alignment: .leading, spacing: .spaceHalf) {
                                    Text(progress / 100, format: .percent.precision(.fractionLength(0)))
                                        .appTextStyle(.caption)
                                        .monospacedDigit()
                                        .foregroundStyle(theme.brandAccent)
                                    CoverProgressView(progress: progress)
                                }
                            }
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
                .accessibilityLabel(Text(seriesAccessibilityLabel(index: index, work: work)))
                .onAppear { store.loadNextPageIfNeeded(bookID: work.id) }
                Divider()
            }
        }
    }

    private func mediaSummary(for work: BookCard) -> String {
        work.availableMediaKinds.map { kind in
            switch kind {
            case .ebook: String(localized: "library.media.ebook")
            case .comic: String(localized: "library.media.comic")
            case .audiobook: String(localized: "library.media.audiobook")
            }
        }
        .joined(separator: " · ")
    }

    private func seriesAccessibilityLabel(index: Int, work: BookCard) -> String {
        String(
            format: String(localized: "facet.series.book.accessibility.format"),
            locale: .current,
            index + 1,
            work.title,
            work.author ?? "—"
        )
    }
}
