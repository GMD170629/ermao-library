import Foundation

enum ContentUITestFixture {
    static let launchEnvironmentKey = "ERMAO_UI_TEST_CONTENT_FIXTURE"

    @MainActor
    static func makeRuntime() -> PreviewMobileRuntime {
        let profile = RuntimeServerProfile(
            id: "ui-test-profile",
            displayName: "library.example.test",
            baseURL: "https://library.example.test",
            serverIdentity: "ui-test-server",
            isActive: true,
            tlsMode: .systemTrust
        )
        return PreviewMobileRuntime(
            snapshot: RuntimeSessionSnapshot(
                phase: .authenticated,
                profile: profile,
                userID: "ui-test-user",
                userDisplayName: "Reader",
                userEmail: "reader@example.test",
                userAvatarURL: nil,
                userLocale: Locale.preferredLanguages.first?.hasPrefix("zh") == true ? "zh-CN" : "en-US",
                authorization: RuntimeAuthorization(
                    isAdmin: false,
                    canManageSystem: true,
                    allLibraryScopes: true,
                    libraryIDs: [],
                    canViewManualImports: false,
                    authorizationVersion: 1
                ),
                reasonCode: nil
            )
        )
    }

    static func makeContentClient() -> any ContentClient {
        FixtureContentClient()
    }

    static func makeShelfClient() -> any ShelfClient { FixtureShelfClient() }

    static func makeSettingsClient() -> any SettingsClient {
        FixtureSettingsClient()
    }
}

private struct FixtureSettingsClient: SettingsClient {
    private var account: SettingsAccount {
        SettingsAccount(
            id: "ui-test-user",
            displayName: "Reader",
            email: "reader@example.test",
            avatarURL: nil
        )
    }

    func loadSettings() async throws -> (account: SettingsAccount, locale: SettingsLocale) {
        (account, .enUS)
    }

    func updateName(_ name: String) async throws -> SettingsAccount { account }
    func updateEmail(_ email: String, currentPassword: String) async throws -> SettingsAccount { account }
    func updatePassword(currentPassword: String, newPassword: String) async throws -> SettingsPasswordChange {
        SettingsPasswordChange(requiresLogin: true)
    }
    func loadAvatar(from avatarURL: String, etag: String?) async throws -> SettingsAvatarContent {
        SettingsAvatarContent(data: Data(), contentType: nil, etag: nil, notModified: false)
    }
    func uploadAvatar(_ upload: SettingsAvatarUpload) async throws -> SettingsAccount { account }
    func deleteAvatar() async throws -> SettingsAccount { account }
    func updateLocale(_ locale: SettingsLocale) async throws -> SettingsLocale { locale }
    func loadServerVersion() async throws -> String { "fixture-server" }
}

private actor FixtureShelfClient: ShelfClient {
    private var selected = false

    func fetchShelves(context: ContentRequestContext, bookID: String) async throws -> [ShelfOption] {
        [ShelfOption(id: "favorites", name: "Favorites", containsWork: selected, isMembershipEditable: true)]
    }

    func updateShelf(context: ContentRequestContext, bookID: String, shelf: ShelfOption, add: Bool) async throws {
        selected = add
    }
}

private struct FixtureContentClient: ContentClient {
    private let books = [
        BookCard(
            id: "pride-and-prejudice",
            title: "Pride and Prejudice",
            author: "Jane Austen",
            cover: nil,
            progress: 32
        ),
        BookCard(
            id: "the-left-hand-of-darkness",
            title: "The Left Hand of Darkness",
            author: "Ursula K. Le Guin",
            cover: nil,
            progress: nil
        ),
        BookCard(
            id: "a-wizard-of-earthsea",
            title: "A Wizard of Earthsea",
            author: "Ursula K. Le Guin",
            cover: nil,
            progress: 68
        )
    ]

    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? {
        let book = ProcessInfo.processInfo.environment["ERMAO_UI_TEST_MULTI_DETAIL"] == "1"
            ? books[1]
            : books[0]
        return ContinueReadingItem(book: book, resourceTitle: nil, positionLabel: book.progress.map { "\(Int($0))%" })
    }

    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [BookCard] {
        Array(books.prefix(limit))
    }

    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [BookCard] {
        Array(books.reversed().prefix(limit))
    }

    func fetchBooks(context: ContentRequestContext, query: BooksQuery) async throws -> BookPage {
        let filtered = books.filter { book in
            let libraryID = book.id == "pride-and-prejudice" ? "classics" : "science-fiction"
            let readingStatus: LibraryReadingStatus = book.progress == nil ? .unread : .reading
            return (query.query.isEmpty || book.title.localizedCaseInsensitiveContains(query.query))
                && (query.libraryID == nil || query.libraryID == libraryID)
                && (query.filters.readingStatus == nil || query.filters.readingStatus == readingStatus)
        }
        return BookPage(
            books: filtered,
            page: query.page,
            pageSize: query.pageSize,
            total: filtered.count,
            totalPages: filtered.isEmpty ? 0 : 1
        )
    }

    func fetchLibraryOptions(context: ContentRequestContext) async throws -> [LibrarySourceOption] {
        [
            LibrarySourceOption(id: "classics", name: "Classics"),
            LibrarySourceOption(id: "science-fiction", name: "科幻 / Sci-Fi"),
        ]
    }

    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage {
        let names = query.kind == .series
            ? ["Earthsea", "Dune", "The Expanse"]
            : ["J.K. Rowling", "Frank Herbert", "Ursula K. Le Guin"]
        let groups = names.enumerated().map { index, name in
            let representativeCount = index + 1
            return LibraryGrouping(
                id: name.lowercased().replacingOccurrences(of: " ", with: "-"),
                kind: query.kind,
                name: name,
                bookCount: representativeCount,
                representativeBooks: Array(books.prefix(representativeCount))
            )
        }
        return GroupingPage(groups: groups, page: query.page, pageSize: query.pageSize, total: groups.count, totalPages: 1)
    }

    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage {
        FacetPage(
            facet: FacetIdentity(
                id: query.facetID,
                kind: query.kind,
                name: query.kind == .series ? "Earthsea" : "Ursula K. Le Guin"
            ),
            books: books,
            page: query.page,
            pageSize: query.pageSize,
            total: books.count,
            totalPages: 1
        )
    }

    func fetchBookDetail(context: ContentRequestContext, query: BookDetailQuery) async throws -> BookDetailContent {
        let book = books.first(where: { $0.id == query.bookID }) ?? books[0]
        let selectedResourceID = query.resourceID ?? "resource-1"
        let resources: [BookResource] = if book.id == "the-left-hand-of-darkness" {
            [
                BookResource(
                    id: "resource-1", bookID: book.id,
                    title: "The Left Hand of Darkness I",
                    format: "EPUB", resourceIndex: 1,
                    sizeLabel: "2.6 MB",
                    progress: 34,
                    isReadable: true,
                    isSelected: selectedResourceID == "resource-1"
                ),
                BookResource(
                    id: "resource-2", bookID: book.id,
                    title: "The Left Hand of Darkness II",
                    format: "EPUB", resourceIndex: 2,
                    sizeLabel: "3.1 MB",
                    progress: 12,
                    isReadable: true,
                    isSelected: selectedResourceID == "resource-2"
                ),
                BookResource(
                    id: "resource-3", bookID: book.id,
                    title: "The Left Hand of Darkness III",
                    format: "EPUB", resourceIndex: 3,
                    sizeLabel: "3.4 MB",
                    progress: nil,
                    isReadable: true,
                    isSelected: selectedResourceID == "resource-3"
                )
            ]
        } else {
            [
                BookResource(
                    id: "resource-1", bookID: book.id,
                    title: "Resource 1",
                    format: "EPUB",
                    sizeLabel: "2.6 MB",
                    progress: book.progress,
                    isReadable: true,
                    isSelected: true
                )
            ]
        }
        return BookDetailContent(
            book: book,
            description: book.id == "a-wizard-of-earthsea"
                ? "  \n"
                : "A fixture description used only by the physical-device UI test.",
            tags: ["Classic", "Romance"],
            seriesFacet: FacetIdentity(id: "earthsea", kind: .series, name: "Earthsea"),
            authorFacets: [FacetIdentity(id: "ursula-le-guin", kind: .author, name: book.author ?? "")],
            resources: resources,
            selectedResourceID: selectedResourceID,
            readingStatus: book.progress == nil ? .unread : .reading,
            chapters: book.id == "the-left-hand-of-darkness" ? [] : [
                BookChapter(id: "chapter-1", title: "Chapter 1", progress: book.progress, isCurrent: true),
                BookChapter(id: "chapter-2", title: "Chapter 2", progress: nil, isCurrent: false),
            ],
            continueResourceID: "resource-1"
        )
    }

    func fetchBookContents(
        context: ContentRequestContext,
        bookID: String,
        sourceNodeID: String?,
        sort: BookContentSort,
        page: Int,
        pageSize: Int
    ) async throws -> BookContentsPage {
        if bookID != "the-left-hand-of-darkness" {
            let book = books.first { $0.id == bookID } ?? books[0]
            let resource = fixtureContentEntry(
                id: "resource-node-1", title: book.title, kind: "FILE",
                hasChildren: false, resourceID: "resource-1"
            )
            return BookContentsPage(
                bookID: bookID, currentSourceNodeID: nil, currentResourceID: "resource-1",
                currentNode: resource, currentResourceIDs: ["resource-1"], parentSourceNodeID: nil,
                breadcrumbs: [], entries: [resource], page: 1, pageSize: pageSize, total: 1, totalPages: 1
            )
        }
        let root = fixtureContentEntry(
            id: "fixture-root",
            title: "The Left Hand of Darkness",
            kind: "FOLDER",
            hasChildren: true
        )
        let winter = fixtureContentEntry(
            id: "winter-cycle",
            parentID: "fixture-root",
            title: "Winter Cycle",
            kind: "FOLDER",
            hasChildren: true,
            representativeResourceID: "resource-2"
        )
        let volumeOne = fixtureContentEntry(
            id: "resource-node-1",
            parentID: "fixture-root",
            title: "The Left Hand of Darkness I.cbz",
            kind: "FILE",
            hasChildren: false,
            resourceID: "resource-1"
        )
        let volumeTwo = fixtureContentEntry(
            id: "resource-node-2",
            parentID: "winter-cycle",
            title: "The Left Hand of Darkness II",
            kind: "FILE",
            hasChildren: false,
            resourceID: "resource-2"
        )
        let volumeThree = fixtureContentEntry(
            id: "resource-node-3",
            parentID: "winter-cycle",
            title: "The Left Hand of Darkness III",
            kind: "FILE",
            hasChildren: false,
            resourceID: "resource-3"
        )
        let isNested = sourceNodeID == winter.sourceNodeID
        let entries = isNested ? [volumeTwo, volumeThree] : [winter, volumeOne]
        return BookContentsPage(
            bookID: bookID,
            currentSourceNodeID: isNested ? winter.sourceNodeID : root.sourceNodeID,
            currentResourceID: nil,
            currentNode: isNested ? winter : root,
            currentResourceIDs: entries.compactMap(\.resourceID),
            parentSourceNodeID: isNested ? root.sourceNodeID : nil,
            breadcrumbs: isNested ? [winter] : [],
            entries: entries,
            page: page,
            pageSize: pageSize,
            total: entries.count,
            totalPages: 1
        )
    }

    func fetchBookChapters(
        context: ContentRequestContext,
        bookID: String,
        resourceID: String,
        page: Int,
        pageSize: Int
    ) async throws -> BookChapterPage {
        BookChapterPage(
            resourceID: resourceID,
            chapters: [
                BookChapter(id: "chapter-1", title: "Chapter 1", progress: 32, isCurrent: true, sortOrder: 1, state: .current),
                BookChapter(id: "chapter-2", title: "Chapter 2", progress: nil, isCurrent: false, sortOrder: 2, state: .unread),
            ],
            page: page,
            pageSize: pageSize,
            total: 2,
            totalPages: 1
        )
    }

    func fetchResourceDetail(
        context: ContentRequestContext,
        bookID: String,
        resourceID: String,
        page: Int,
        pageSize: Int
    ) async throws -> BookResourceDetailPage {
        BookResourceDetailPage(
            resourceID: resourceID,
            units: [
                BookResourceDetailUnit(
                    id: "chapter-1", title: "Chapter 1", unitType: "chapter", assetID: nil,
                    href: "chapter-1.xhtml", sortOrder: 1, pageNumber: nil, previewURL: nil, level: 0,
                    durationMillis: nil, discNumber: nil, trackNumber: nil, chapterState: .current
                ),
                BookResourceDetailUnit(
                    id: "chapter-2", title: "Chapter 2", unitType: "chapter", assetID: nil,
                    href: "chapter-2.xhtml", sortOrder: 2, pageNumber: nil, previewURL: nil, level: 0,
                    durationMillis: nil, discNumber: nil, trackNumber: nil, chapterState: .unread
                ),
            ],
            page: page,
            pageSize: pageSize,
            total: 2,
            totalPages: 1,
            currentHref: "chapter-1.xhtml",
            currentChapterSortOrder: 1,
            currentPageNumber: nil,
            progress: 32
        )
    }

    func fetchCoverData(context: ContentRequestContext, reference: CoverReference) async throws -> Data {
        throw ContentClientError.invalidResponse
    }

    private func fixtureContentEntry(
        id: String,
        parentID: String? = nil,
        title: String,
        kind: String,
        hasChildren: Bool,
        resourceID: String? = nil,
        representativeResourceID: String? = nil
    ) -> BookContentEntry {
        BookContentEntry(
            sourceNodeID: id,
            parentSourceNodeID: parentID,
            name: title,
            title: title,
            description: nil,
            kind: kind,
            physicalKind: kind == "FOLDER" ? "DIRECTORY" : "REGULAR_FILE",
            sizeBytes: nil,
            hasChildren: hasChildren,
            resourceID: resourceID,
            representativeResourceID: representativeResourceID ?? resourceID,
            cover: nil
        )
    }
}
