import Foundation
@preconcurrency import ErmaoShared

struct ContentRequestContext: Hashable, Codable, Sendable {
    let profileID: String
    let profileDisplayName: String
    let serverIdentity: String
    let userID: String
    let authorizationVersion: Int64
    let baseURL: String
    let acceptsInsecureTLS: Bool

    var namespaceKey: String {
        "\(serverIdentity)|\(userID)|\(authorizationVersion)"
    }
}

protocol PrivateContentCacheClearing: Sendable {
    func removeNamespace(_ namespace: String) async throws
}

protocol ShelfClient: Sendable {
    func fetchShelves(context: ContentRequestContext, bookID: String) async throws -> [ShelfOption]
    func updateShelf(context: ContentRequestContext, bookID: String, shelf: ShelfOption, add: Bool) async throws
}

struct ShelfOption: Identifiable, Equatable, Sendable {
    let id: String
    let name: String
    let containsWork: Bool
    let isMembershipEditable: Bool
}

enum ContentClientError: Error, Equatable, Sendable {
    case unauthorized
    case inaccessible
    case offline
    case transport
    case invalidResponse
}

enum LibraryScope: String, Codable, Hashable, Sendable {
    case books
    case series
    case authors
}

enum LibrarySort: String, Codable, Hashable, Sendable {
    case recentAdded
    case recentRead
    case title
    case author
}

enum LibraryViewMode: String, Codable, Hashable, Sendable {
    case grid
    case list
}

enum LibraryFacetSort: String, Codable, Hashable, Sendable {
    case seriesIndex
    case recentRead
}

enum LibraryReadingStatus: String, Codable, Hashable, Sendable {
    case unread = "UNREAD"
    case reading = "READING"
    case finished = "FINISHED"
}

enum FacetKind: String, Codable, Hashable, Sendable {
    case series = "SERIES"
    case author = "AUTHOR"
}

struct LibraryFilters: Codable, Equatable, Hashable, Sendable {
    var readingStatus: LibraryReadingStatus?

    var isEmpty: Bool { readingStatus == nil }
    var count: Int { readingStatus == nil ? 0 : 1 }
}

struct BooksQuery: Equatable, Hashable, Sendable {
    let query: String
    let libraryID: String?
    let sort: LibrarySort
    let filters: LibraryFilters
    let page: Int
    let pageSize: Int
}

struct LibrarySourceOption: Identifiable, Equatable, Hashable, Sendable {
    let id: String
    let name: String
}

struct GroupingsQuery: Equatable, Hashable, Sendable {
    let kind: FacetKind
    let query: String
    let page: Int
    let pageSize: Int
}

struct FacetQuery: Equatable, Hashable, Sendable {
    let kind: FacetKind
    let facetID: String
    let sort: LibraryFacetSort
    let page: Int
    let pageSize: Int
}

struct BookDetailQuery: Equatable, Hashable, Sendable {
    let bookID: String
    let resourceID: String?
}

struct CoverReference: Codable, Equatable, Hashable, Sendable {
    let path: String
}

struct BookCard: Identifiable, Codable, Equatable, Hashable, Sendable {
    let id: String
    let title: String
    let author: String?
    let cover: CoverReference?
    let progress: Double?
}

struct ContinueReadingItem: Codable, Equatable, Sendable {
    let book: BookCard
    let resourceTitle: String?
    let positionLabel: String?
}

struct BookPage: Codable, Equatable, Sendable {
    let books: [BookCard]
    let page: Int
    let pageSize: Int
    let total: Int
    let totalPages: Int
}

struct LibraryGrouping: Identifiable, Codable, Equatable, Sendable {
    let id: String
    let kind: FacetKind
    let name: String
    let bookCount: Int
    let representativeBooks: [BookCard]
}

struct GroupingPage: Codable, Equatable, Sendable {
    let groups: [LibraryGrouping]
    let page: Int
    let pageSize: Int
    let total: Int
    let totalPages: Int
}

struct FacetIdentity: Codable, Equatable, Hashable, Sendable {
    let id: String
    let kind: FacetKind
    let name: String
}

struct FacetPage: Codable, Equatable, Sendable {
    let facet: FacetIdentity
    let books: [BookCard]
    let page: Int
    let pageSize: Int
    let total: Int
    let totalPages: Int
}

struct BookResource: Identifiable, Codable, Equatable, Sendable {
    let id: String
    let bookID: String
    let sourceNodeID: String
    let title: String
    let description: String?
    let format: String
    let readerType: String
    let resourceIndex: Double?
    let cover: CoverReference?
    let sizeLabel: String?
    let progress: Double?
    let isReadable: Bool?
    let isSelected: Bool
    let sortOrder: Int
    let publisher: String?
    let publishedAt: String?
    let language: String?
    let isbn: String?
    let identifier: String?
    let narrator: String?
    let pageCount: Int?
    let metadataSource: String?
    let kindleSendAvailable: Bool
    let assets: [ResourceAsset]

    init(
        id: String,
        bookID: String,
        sourceNodeID: String = "mobile",
        title: String,
        description: String? = nil,
        format: String,
        readerType: String = "reflowable",
        resourceIndex: Double? = nil,
        cover: CoverReference? = nil,
        sizeLabel: String?,
        progress: Double?,
        isReadable: Bool?,
        isSelected: Bool,
        sortOrder: Int = 0,
        publisher: String? = nil,
        publishedAt: String? = nil,
        language: String? = nil,
        isbn: String? = nil,
        identifier: String? = nil,
        narrator: String? = nil,
        pageCount: Int? = nil,
        metadataSource: String? = nil,
        kindleSendAvailable: Bool = false,
        assets: [ResourceAsset] = []
    ) {
        self.id = id
        self.bookID = bookID
        self.sourceNodeID = sourceNodeID
        self.title = title
        self.description = description
        self.format = format
        self.readerType = readerType
        self.resourceIndex = resourceIndex
        self.cover = cover
        self.sizeLabel = sizeLabel
        self.progress = progress
        self.isReadable = isReadable
        self.isSelected = isSelected
        self.sortOrder = sortOrder
        self.publisher = publisher
        self.publishedAt = publishedAt
        self.language = language
        self.isbn = isbn
        self.identifier = identifier
        self.narrator = narrator
        self.pageCount = pageCount
        self.metadataSource = metadataSource
        self.kindleSendAvailable = kindleSendAvailable
        self.assets = assets
    }

    func displayIndex(position: Int) -> String {
        let value: String
        if let resourceIndex, resourceIndex.isFinite, resourceIndex > 0 {
            value = resourceIndex.rounded(.towardZero) == resourceIndex
                ? String(Int(resourceIndex))
                : String(resourceIndex).replacingOccurrences(
                    of: #"\.?0+$"#,
                    with: "",
                    options: .regularExpression
                )
        } else {
            value = String(position + 1)
        }
        return value.count >= 2 ? value : "0\(value)"
    }

    var formatLabel: String { format }
    var primaryAssetID: String? {
        assets.sorted { ($0.sortOrder ?? Int.max) < ($1.sortOrder ?? Int.max) }.first?.id
    }
}

struct ResourceAsset: Identifiable, Codable, Equatable, Sendable {
    let id: String
    let resourceID: String?
    let path: String
    let role: String?
    let mimeType: String?
    let sizeBytes: Int64
    let displaySize: String
    let sortOrder: Int?
    let url: String?
    let downloadURL: String?
}

struct BookResourcePage: Equatable, Sendable {
    let resources: [BookResource]
    let page: Int
    let total: Int
    let totalPages: Int
}

struct BookContentEntry: Identifiable, Equatable, Sendable {
    let sourceNodeID: String
    let parentSourceNodeID: String?
    let name: String
    let title: String
    let description: String?
    let kind: String
    let physicalKind: String
    let sizeBytes: Int64?
    let hasChildren: Bool
    let resourceID: String?
    let representativeResourceID: String?
    let cover: CoverReference?

    var id: String { sourceNodeID }
    var isDirectResource: Bool { resourceID?.isEmpty == false }
    var isSourceFolder: Bool { kind == "FOLDER" && !isDirectResource }
}

struct BookContentsPage: Equatable, Sendable {
    let bookID: String
    let currentSourceNodeID: String?
    let currentResourceID: String?
    let currentNode: BookContentEntry
    let currentResourceIDs: [String]
    let parentSourceNodeID: String?
    let breadcrumbs: [BookContentEntry]
    let entries: [BookContentEntry]
    let page: Int
    let pageSize: Int
    let total: Int
    let totalPages: Int
}

enum BookContentSort: String, CaseIterable, Equatable, Sendable {
    case nameAscending
    case nameDescending
    case updatedDescending
    case updatedAscending
    case typeAscending
    case sizeDescending
}

enum BookContentLayout: String, CaseIterable, Equatable, Sendable {
    case grid
    case list
}

enum ChapterReadingState: String, Codable, Equatable, Sendable {
    case current
    case read
    case unread
}

struct BookChapter: Identifiable, Codable, Equatable, Sendable {
    let id: String
    let title: String
    let progress: Double?
    let href: String?
    let sortOrder: Int
    let readingOrderPosition: Int?
    let state: ChapterReadingState

    var isCurrent: Bool { state == .current }

    init(
        id: String,
        title: String,
        progress: Double?,
        isCurrent: Bool,
        href: String? = nil,
        sortOrder: Int = 0,
        readingOrderPosition: Int? = nil,
        state: ChapterReadingState? = nil
    ) {
        self.id = id
        self.title = title
        self.progress = progress
        self.href = href
        self.sortOrder = sortOrder
        self.readingOrderPosition = readingOrderPosition
        self.state = state ?? (isCurrent ? .current : .unread)
    }
}

struct BookChapterPage: Equatable, Sendable {
    let resourceID: String
    let chapters: [BookChapter]
    let page: Int
    let pageSize: Int
    let total: Int
    let totalPages: Int
}

struct BookResourceDetailUnit: Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    let unitType: String
    let assetID: String?
    let href: String?
    let sortOrder: Int
    let pageNumber: Int?
    let previewURL: String?
    let level: Int?
    let durationMillis: Int64?
    let discNumber: Int?
    let trackNumber: Int?
    let chapterState: ChapterReadingState?
}

struct BookResourceDetailPage: Equatable, Sendable {
    let resourceID: String
    let units: [BookResourceDetailUnit]
    let page: Int
    let pageSize: Int
    let total: Int
    let totalPages: Int
    let currentHref: String?
    let currentChapterSortOrder: Int?
    let currentPageNumber: Int?
    let progress: Double
}

struct BookDetailContent: Codable, Equatable, Sendable {
    let book: BookCard
    let description: String?
    let tags: [String]
    let seriesFacet: FacetIdentity?
    let seriesIndex: Double?
    let authorFacets: [FacetIdentity]
    let resources: [BookResource]
    let selectedResourceID: String?
    let readingStatus: LibraryReadingStatus?
    let chapters: [BookChapter]

    init(
        book: BookCard,
        description: String?,
        tags: [String],
        seriesFacet: FacetIdentity?,
        seriesIndex: Double? = nil,
        authorFacets: [FacetIdentity],
        resources: [BookResource],
        selectedResourceID: String?,
        readingStatus: LibraryReadingStatus?,
        chapters: [BookChapter]
    ) {
        self.book = book
        self.description = description
        self.tags = tags
        self.seriesFacet = seriesFacet
        self.seriesIndex = seriesIndex
        self.authorFacets = authorFacets
        self.resources = resources
        self.selectedResourceID = selectedResourceID
        self.readingStatus = readingStatus
        self.chapters = chapters
    }
}

protocol ContentClient: Sendable {
    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem?
    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [BookCard]
    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [BookCard]
    func fetchBooks(context: ContentRequestContext, query: BooksQuery) async throws -> BookPage
    func fetchLibraryOptions(context: ContentRequestContext) async throws -> [LibrarySourceOption]
    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage
    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage
    func fetchBookDetail(context: ContentRequestContext, query: BookDetailQuery) async throws -> BookDetailContent
    func fetchBookResources(
        context: ContentRequestContext,
        bookID: String,
        page: Int,
        pageSize: Int
    ) async throws -> BookResourcePage
    func fetchBookContents(
        context: ContentRequestContext,
        bookID: String,
        sourceNodeID: String?,
        sort: BookContentSort,
        page: Int,
        pageSize: Int
    ) async throws -> BookContentsPage
    func fetchBookChapters(
        context: ContentRequestContext,
        bookID: String,
        resourceID: String,
        page: Int,
        pageSize: Int
    ) async throws -> BookChapterPage
    func fetchResourceDetail(
        context: ContentRequestContext,
        bookID: String,
        resourceID: String,
        page: Int,
        pageSize: Int
    ) async throws -> BookResourceDetailPage
    func fetchCoverData(context: ContentRequestContext, reference: CoverReference) async throws -> Data
}

extension ContentClient {
    func fetchLibraryOptions(context: ContentRequestContext) async throws -> [LibrarySourceOption] { [] }

    func fetchBookResources(
        context: ContentRequestContext,
        bookID: String,
        page: Int,
        pageSize: Int
    ) async throws -> BookResourcePage {
        throw ContentClientError.invalidResponse
    }

    func fetchBookContents(
        context: ContentRequestContext,
        bookID: String,
        sourceNodeID: String?,
        sort: BookContentSort,
        page: Int,
        pageSize: Int
    ) async throws -> BookContentsPage {
        throw ContentClientError.invalidResponse
    }

    func fetchBookChapters(
        context: ContentRequestContext,
        bookID: String,
        resourceID: String,
        page: Int,
        pageSize: Int
    ) async throws -> BookChapterPage {
        throw ContentClientError.invalidResponse
    }

    func fetchResourceDetail(
        context: ContentRequestContext,
        bookID: String,
        resourceID: String,
        page: Int,
        pageSize: Int
    ) async throws -> BookResourceDetailPage {
        throw ContentClientError.invalidResponse
    }

}

struct UnavailableContentClient: ContentClient {
    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? {
        throw ContentClientError.transport
    }

    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [BookCard] {
        throw ContentClientError.transport
    }

    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [BookCard] {
        throw ContentClientError.transport
    }

    func fetchBooks(context: ContentRequestContext, query: BooksQuery) async throws -> BookPage {
        throw ContentClientError.transport
    }

    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage {
        throw ContentClientError.transport
    }

    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage {
        throw ContentClientError.transport
    }

    func fetchBookDetail(context: ContentRequestContext, query: BookDetailQuery) async throws -> BookDetailContent {
        throw ContentClientError.transport
    }

    func fetchCoverData(context: ContentRequestContext, reference: CoverReference) async throws -> Data {
        throw ContentClientError.transport
    }
}

enum ContentCompositionRoot {
    static func makeClient(
        cookieStore: KeychainCookiePayloadStore = KeychainCookiePayloadStore()
    ) -> any ContentClient {
        let repository = IosCompositionKt.createIosContentRepository(cookieStore: cookieStore)
        return SharedContentClient(repository: repository)
    }
}

enum ShelfCompositionRoot {
    static func makeClient(
        cookieStore: KeychainCookiePayloadStore = KeychainCookiePayloadStore()
    ) -> any ShelfClient {
        SharedShelfClient(repository: IosCompositionKt.createIosShelfRepository(cookieStore: cookieStore))
    }
}
