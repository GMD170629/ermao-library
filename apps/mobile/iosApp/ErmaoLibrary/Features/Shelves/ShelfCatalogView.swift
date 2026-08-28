import SwiftUI

struct ShelfCatalogView: View {
    let context: ContentRequestContext
    let contentClient: any ContentClient
    let cache: AuthenticatedCoverCache
    let shelfID: String?
    let openShelf: (String) -> Void
    let openBook: (String) -> Void
    @StateObject private var store: ShelfCatalogStore
    @State private var presentsCreate = false
    @State private var action: Task<Void, Never>?
    @Environment(\.managementRevision) private var managementRevision
    @Environment(\.appTheme) private var theme
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(context: ContentRequestContext, client: any ShelfCatalogClient, contentClient: any ContentClient,
         cache: AuthenticatedCoverCache, shelfID: String? = nil, onUnauthorized: @escaping @MainActor () -> Void,
         openShelf: @escaping (String) -> Void, openBook: @escaping (String) -> Void) {
        self.context = context; self.contentClient = contentClient; self.cache = cache; self.shelfID = shelfID
        self.openShelf = openShelf; self.openBook = openBook
        _store = StateObject(wrappedValue: ShelfCatalogStore(context: context, client: client, shelfID: shelfID, onUnauthorized: onUnauthorized))
    }

    private var showsShelves: Bool { shelfID == nil || store.detail?.shelf.kind == .collection }

    var body: some View {
        searchableContent
            .navigationTitle(store.detail.map { Text($0.shelf.name) } ?? Text("tab.shelves"))
            .navigationBarTitleDisplayMode(shelfID == nil ? .large : .inline)
            .accessibilityIdentifier(shelfID == nil ? "shelves.root" : "shelves.detail")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    if shelfID == nil {
                        Button {
                            store.clearCreationError(); presentsCreate = true
                        } label: { Image(systemName: "plus") }
                        .accessibilityLabel(Text("shelves.create"))
                        .disabled(!isReady)
                    } else {
                        Menu {
                            Button("common.refresh", systemImage: "arrow.clockwise") { refresh() }
                        } label: { Image(systemName: "ellipsis") }
                        .accessibilityLabel(Text("common.more"))
                    }
                }
            }
            .sheet(isPresented: $presentsCreate) {
                ShelfCreateView(store: store) { id in presentsCreate = false; openShelf(id) }
            }
            .appCanvas()
            .onChange(of: managementRevision, initial: true) { _, _ in guard managementRevision > 0 else { return }; Task { await store.refresh() } }
        .task { await store.loadIfNeeded() }
            .onDisappear { action?.cancel(); action = nil }
    }

    private var isReady: Bool { if case .ready = store.state { return true }; return false }

    @ViewBuilder private var searchableContent: some View {
        if showsShelves {
            scrollContent.searchable(text: $store.query, placement: .navigationBarDrawer(displayMode: .always),
                                     prompt: Text(shelfID == nil ? "shelves.search" : "shelves.search.collection"))
        } else { scrollContent }
    }

    private var scrollContent: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                if shelfID == nil {
                    Picker("shelves.scope", selection: $store.scope) {
                        Text("shelves.all").tag(ShelfCatalogScope.all)
                        Text("tab.shelves").tag(ShelfCatalogScope.shelves)
                        Text("shelves.collections").tag(ShelfCatalogScope.collections)
                    }
                    .pickerStyle(.segmented)
                    .padding(.vertical, .space2)
                    .accessibilityIdentifier("shelves.scope")
                } else if let detail = store.detail {
                    ShelfCountLabel(shelf: detail.shelf)
                        .appTextStyle(.callout).foregroundStyle(theme.textSecondary)
                        .padding(.vertical, .space2)
                }
                Divider().overlay(theme.divider)
                resultContent
            }
            .padding(.horizontal, .space2)
            .padding(.bottom, .space4)
        }
        .refreshable { await store.refresh() }
    }

    @ViewBuilder private var resultContent: some View {
        switch store.state {
        case .loading:
            ProgressView().frame(maxWidth: .infinity).padding(.vertical, .space4)
                .accessibilityLabel(Text("common.loading"))
        case .failed(let error):
            ContentStatusView(
                systemImage: error == .inaccessible ? "lock" : "wifi.exclamationmark",
                title: error == .inaccessible ? "shelves.inaccessible" : "shelves.error",
                message: "shelves.error.message", actionTitle: "common.retry", action: refresh
            )
        case .ready(let catalog, let detail):
            if showsShelves {
                if store.visibleShelves.isEmpty {
                    ContentStatusView(systemImage: "books.vertical",
                        title: store.query.isEmpty ? "shelves.empty" : "shelves.noResults",
                        message: store.query.isEmpty ? "shelves.empty.message" : "shelves.noResults.message")
                }
                ForEach(store.visibleShelves) { shelf in
                    Button { openShelf(shelf.id) } label: {
                        shelfRow(shelf, catalog: catalog)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("shelf.row.\(shelf.id)")
                    Divider().overlay(theme.divider)
                }
            } else if let detail {
                if detail.shelf.books.isEmpty {
                    ContentStatusView(systemImage: "book.closed", title: "shelves.empty.books", message: "shelves.empty.books.message")
                }
                ForEach(detail.shelf.books) { book in
                    Button { openBook(book.id) } label: {
                        HStack(spacing: .space2) {
                            cover(book, manage: true).frame(width: 64).accessibilityHidden(true)
                            VStack(alignment: .leading, spacing: .spaceHalf) {
                                Text(book.title).appTextStyle(.headline).foregroundStyle(theme.textPrimary).lineLimit(3)
                                if let author = book.author {
                                    Text(author).appTextStyle(.callout).foregroundStyle(theme.textSecondary)
                                }
                            }.frame(maxWidth: .infinity, alignment: .leading)
                            chevron
                        }.padding(.vertical, .space2).contentShape(Rectangle())
                    }.buttonStyle(.plain).bookManagementMenu(.book(book.id, book.title))
                    Divider().overlay(theme.divider)
                }
                if detail.page < detail.totalPages {
                    if store.loadingMore { ProgressView().padding(.space2) }
                    else {
                        Button(store.paginationFailed ? "shelves.loadMore.retry" : "shelves.loadMore") {
                            action?.cancel(); action = Task { await store.loadMore() }
                        }.frame(maxWidth: .infinity, minHeight: 48)
                    }
                }
            }
        }
    }

    private func shelfRow(_ shelf: ShelfCatalogItem, catalog: [ShelfCatalogItem]) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: .space1) {
                Text(shelf.name).appTextStyle(.headline).foregroundStyle(theme.textPrimary).lineLimit(3)
                ShelfCountLabel(shelf: shelf).appTextStyle(.caption).foregroundStyle(theme.textSecondary)
                if shelf.kind == .smart {
                    if let description = shelf.description, !description.isEmpty {
                        Text(description).appTextStyle(.caption).foregroundStyle(theme.textSecondary).lineLimit(2)
                    } else {
                        Text(shelf.rulesSupported ? "shelves.smart.hint" : "shelves.rules.unsupported")
                            .appTextStyle(.caption).foregroundStyle(theme.textSecondary).lineLimit(2)
                    }
                }
            }.frame(maxWidth: .infinity, alignment: .leading)
            HStack(spacing: .space1) {
                ForEach(Array(shelfPreview(shelf, catalog: catalog).prefix(dynamicTypeSize >= .xxLarge ? 1 : 3))) { book in
                    cover(book).frame(width: 52)
                }
            }.accessibilityHidden(true)
            chevron
        }
        .padding(.vertical, 20)
        .frame(minHeight: 116)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }

    private var chevron: some View {
        Image(systemName: "chevron.right").font(.callout).foregroundStyle(theme.textSecondary).accessibilityHidden(true)
    }

    private func cover(_ book: ShelfPreview, manage: Bool = false) -> some View {
        BookCoverView(reference: book.cover, title: book.title, context: context, client: contentClient, cache: cache, managementTarget: manage ? .book(book.id, book.title) : nil)
            .id("\(context.namespaceKey)|\(book.id)|\(book.cover?.path ?? "")")
    }

    private func refresh() { action?.cancel(); action = Task { await store.refresh() } }
}

private struct ShelfCountLabel: View {
    let shelf: ShelfCatalogItem
    @Environment(\.locale) private var locale
    var body: some View {
        Text(String(format: String(localized: String.LocalizationValue(key), locale: locale), locale: locale,
                    shelf.count.formatted(.number.locale(locale))))
    }
    private var key: String {
        switch shelf.kind {
        case .standard: "shelves.count.books"
        case .smart: "shelves.count.smart"
        case .collection: "shelves.count.collection"
        }
    }
}

private struct ShelfCreateView: View {
    @ObservedObject var store: ShelfCatalogStore
    let onCreated: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var draft = ShelfCreateDraft()
    @State private var submission: Task<Void, Never>?

    var body: some View {
        NavigationStack {
            Form {
                Picker("shelves.scope", selection: $draft.isCollection) {
                    Text("tab.shelves").tag(false)
                    Text("shelves.collections").tag(true)
                }.pickerStyle(.segmented)
                TextField("shelves.name", text: $draft.name)
                TextField("shelves.description", text: $draft.description, axis: .vertical)
                if draft.isCollection {
                    Section("shelves.chooseMembers") {
                        ForEach(store.catalog.filter { $0.kind != .collection }) { shelf in
                            Toggle(shelf.name, isOn: Binding(
                                get: { draft.memberIDs.contains(shelf.id) },
                                set: { selected in
                                    if selected { draft.memberIDs.insert(shelf.id) }
                                    else { draft.memberIDs.remove(shelf.id) }
                                }
                            ))
                        }
                    }
                }
                if store.creation == .failed { Text("shelves.create.failed") }
            }
            .disabled(store.creation == .saving)
            .navigationTitle("shelves.create")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("common.cancel") { dismiss() }.disabled(store.creation == .saving)
                }
                ToolbarItem(placement: .confirmationAction) {
                    if store.creation == .saving { ProgressView() }
                    else {
                        Button("shelves.create") {
                            submission = Task { if let id = await store.create(draft) { onCreated(id) } }
                        }.disabled(!draft.isValid)
                    }
                }
            }
        }
        .interactiveDismissDisabled(store.creation == .saving)
        .onDisappear { submission?.cancel(); submission = nil }
    }
}
