import SwiftUI

enum HomeCollectionKind: String, Hashable, Codable, Sendable {
    case recentReading
    case recentAdded
}

struct HomeView: View {
    let context: ContentRequestContext
    let client: any ContentClient
    let cache: AuthenticatedCoverCache
    let openWork: (String) -> Void
    let openCollection: (HomeCollectionKind) -> Void

    @StateObject private var store: HomeStore
    @Environment(\.managementRevision) private var managementRevision
    @Environment(\.appTheme) private var theme

    init(
        context: ContentRequestContext,
        client: any ContentClient,
        cache: AuthenticatedCoverCache,
        onUnauthorized: @escaping @MainActor () -> Void,
        openWork: @escaping (String) -> Void,
        openCollection: @escaping (HomeCollectionKind) -> Void
    ) {
        self.context = context
        self.client = client
        self.cache = cache
        self.openWork = openWork
        self.openCollection = openCollection
        _store = StateObject(
            wrappedValue: HomeStore(
                context: context,
                client: client,
                onUnauthorized: onUnauthorized
            )
        )
    }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: .space3) {
                continueSection
                horizontalSection(
                    title: "home.recentReading.title",
                    state: store.recentReading,
                    collection: .recentReading,
                    retry: store.retryRecentReading
                )
                horizontalSection(
                    title: "home.recentAdded.title",
                    state: store.recentAdded,
                    collection: .recentAdded,
                    retry: store.retryRecentAdded
                )
            }
            .padding(.horizontal, .space2)
            .padding(.bottom, .space4)
        }
        .refreshable { store.load() }
        .navigationTitle("tab.home")
        .navigationBarTitleDisplayMode(.large)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Button("common.refresh", systemImage: "arrow.clockwise") { store.load() }
                } label: {
                    Image(systemName: "ellipsis")
                }
                .accessibilityLabel(Text("common.more"))
            }
        }
        .appCanvas()
        .onChange(of: managementRevision, initial: true) { _, _ in guard managementRevision > 0 else { return }; store.load() }
        .task { store.load() }
    }

    @ViewBuilder
    private var continueSection: some View {
        VStack(alignment: .leading, spacing: .space1Half) {
            Text("home.continue.title").appTextStyle(.headline)
            switch store.continueReading {
            case .loading:
                HStack { Spacer(); ProgressView(); Spacer() }
                    .frame(minHeight: 180)
            case .empty:
                ContentStatusView(
                    systemImage: "book.closed",
                    title: "home.continue.empty.title",
                    message: "home.continue.empty.message"
                )
            case .failure:
                ContentStatusView(
                    systemImage: "wifi.exclamationmark",
                    title: "home.section.error.title",
                    message: "home.section.error.message",
                    actionTitle: "common.retry",
                    action: store.retryContinueReading
                )
            case .content(let item):
                VStack(spacing: .space1Half) {
                    Button { openWork(item.book.id) } label: {
                        HStack(spacing: .space2) {
                            BookCoverView(
                                reference: item.book.cover,
                                title: item.book.title,
                                context: context,
                                client: client,
                                cache: cache,
                                cornerRadius: CGFloat(GeneratedDesignTokens.Radii.coverHero),
                                managementTarget: .book(item.book.id, item.book.title, completed: item.book.completed)
                            )
                            .frame(width: BookCoverLayout.horizontalCardWidth)
                            VStack(alignment: .leading, spacing: .spaceHalf) {
                                Text(item.book.title).appTextStyle(.headline).lineLimit(2)
                                Text(item.book.author ?? "—")
                                    .appTextStyle(.callout)
                                    .foregroundStyle(theme.textSecondary)
                                    .lineLimit(1)
                                if let position = item.positionLabel ?? item.resourceTitle {
                                    Text(position)
                                        .appTextStyle(.label)
                                        .foregroundStyle(theme.textSecondary)
                                        .lineLimit(2)
                                }
                                if let progress = item.book.progress {
                                    Text(progress / 100, format: .percent.precision(.fractionLength(0)))
                                        .appTextStyle(.caption)
                                        .monospacedDigit()
                                    CoverProgressView(progress: progress)
                                }
                            }
                            Spacer(minLength: 0)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.borderless)
                    PrimaryActionButton("home.continue.action") { openWork(item.book.id) }
                }
                .padding(.space1Half)
                .background(theme.surface)
                .clipShape(RoundedRectangle(cornerRadius: CGFloat(GeneratedDesignTokens.Radii.task)))
                .overlay {
                    RoundedRectangle(cornerRadius: CGFloat(GeneratedDesignTokens.Radii.task))
                        .stroke(theme.divider, lineWidth: 1)
                }
            }
        }
    }

    @ViewBuilder
    private func horizontalSection(
        title: LocalizedStringKey,
        state: HomeSectionState<[BookCard]>,
        collection: HomeCollectionKind,
        retry: @escaping () -> Void
    ) -> some View {
        VStack(alignment: .leading, spacing: .space1Half) {
            HStack {
                Text(title).appTextStyle(.headline)
                Spacer()
                Button { openCollection(collection) } label: {
                    HStack(spacing: .spaceHalf) {
                        Text("home.viewAll")
                            .appTextStyle(.label)
                        Image(systemName: "chevron.forward")
                            .font(.caption.weight(.semibold))
                            .accessibilityHidden(true)
                    }
                    .foregroundStyle(theme.actionAccent)
                    .frame(minHeight: .iosMinimumTouchTarget)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityHint(Text("home.viewAll.hint"))
            }
            switch state {
            case .loading:
                HStack { Spacer(); ProgressView(); Spacer() }.frame(minHeight: 176)
            case .empty:
                ContentStatusView(
                    systemImage: "books.vertical",
                    title: "home.section.empty.title",
                    message: "home.section.empty.message"
                )
            case .failure:
                ContentStatusView(
                    systemImage: "wifi.exclamationmark",
                    title: "home.section.error.title",
                    message: "home.section.error.message",
                    actionTitle: "common.retry",
                    action: retry
                )
            case .content(let works):
                ScrollView(.horizontal) {
                    LazyHStack(alignment: .top, spacing: .space2) {
                        ForEach(works) { work in
                            Button { openWork(work.id) } label: {
                                VStack(alignment: .leading, spacing: .spaceHalf) {
                                    BookCoverView(
                                        reference: work.cover,
                                        title: work.title,
                                        context: context,
                                        client: client,
                                        cache: cache,
                            managementTarget: .book(work.id, work.title, completed: work.completed)
                                    )
                                    Text(work.title)
                                        .appTextStyle(.label)
                                        .foregroundStyle(theme.textPrimary)
                                        .lineLimit(1)
                                    if let progress = work.progress, progress > 0 {
                                        CoverProgressView(progress: progress)
                                    }
                                }
                                .frame(width: BookCoverLayout.horizontalCardWidth)
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.borderless)
                        }
                    }
                }
                .scrollIndicators(.hidden)
            }
        }
    }

}
