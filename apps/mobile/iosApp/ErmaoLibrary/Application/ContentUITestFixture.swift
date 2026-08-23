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
                userLocale: "en-US",
                authorization: RuntimeAuthorization(
                    isAdmin: false,
                    canManageSystem: false,
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
    func loadAvatar(etag: String?) async throws -> SettingsAvatarContent {
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
        [ShelfOption(id: "favorites", name: "Favorites", containsWork: selected)]
    }

    func updateShelf(context: ContentRequestContext, bookID: String, shelfID: String, add: Bool) async throws {
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
            progress: 32,
            availableMediaKinds: [.ebook]
        ),
        BookCard(
            id: "the-left-hand-of-darkness",
            title: "The Left Hand of Darkness",
            author: "Ursula K. Le Guin",
            cover: nil,
            progress: nil,
            availableMediaKinds: [.ebook, .audiobook]
        ),
        BookCard(
            id: "a-wizard-of-earthsea",
            title: "A Wizard of Earthsea",
            author: "Ursula K. Le Guin",
            cover: nil,
            progress: 68,
            availableMediaKinds: [.ebook]
        )
    ]

    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? {
        ContinueReadingItem(book: books[0], resourceTitle: nil, positionLabel: "32%")
    }

    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [BookCard] {
        Array(books.prefix(limit))
    }

    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [BookCard] {
        Array(books.reversed().prefix(limit))
    }

    func fetchBooks(context: ContentRequestContext, query: BooksQuery) async throws -> BookPage {
        let filtered = query.query.isEmpty
            ? books
            : books.filter { $0.title.localizedCaseInsensitiveContains(query.query) }
        return BookPage(
            books: filtered,
            page: query.page,
            pageSize: query.pageSize,
            total: filtered.count,
            totalPages: filtered.isEmpty ? 0 : 1
        )
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
            ]
        )
    }

    func fetchCoverData(context: ContentRequestContext, reference: CoverReference) async throws -> Data {
        throw ContentClientError.invalidResponse
    }
}
