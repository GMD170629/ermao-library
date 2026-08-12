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

enum ContentClientError: Error, Equatable, Sendable {
    case unauthorized
    case inaccessible
    case offline
    case transport
    case invalidResponse
}

enum ContentProvenance: Sendable {
    case network
    case cache
}

struct ContentFetch<Value: Sendable>: Sendable {
    let value: Value
    let provenance: ContentProvenance
    let isStale: Bool
}

enum LibraryScope: String, Codable, Hashable, Sendable {
    case works
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

enum OfflineFilterAvailability: Equatable, Sendable {
    case available
    case unavailable(reasonCode: String)
}

enum LibraryMediaKind: String, Codable, Hashable, Sendable {
    case ebook = "EBOOK"
    case comic = "COMIC"
    case audiobook = "AUDIOBOOK"
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
    var mediaKinds: Set<LibraryMediaKind> = []
    var readingStatuses: Set<LibraryReadingStatus> = []
    var downloadedOnly = false

    var isEmpty: Bool { mediaKinds.isEmpty && readingStatuses.isEmpty && !downloadedOnly }
    var count: Int { mediaKinds.count + readingStatuses.count + (downloadedOnly ? 1 : 0) }
}

struct WorksQuery: Equatable, Hashable, Sendable {
    let query: String
    let sort: LibrarySort
    let filters: LibraryFilters
    let page: Int
    let pageSize: Int
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

struct WorkDetailQuery: Equatable, Hashable, Sendable {
    let workID: String
    let mediaKind: LibraryMediaKind?
    let volumeID: String?
}

struct CoverReference: Codable, Equatable, Hashable, Sendable {
    let path: String
}

struct WorkCard: Identifiable, Codable, Equatable, Hashable, Sendable {
    let id: String
    let title: String
    let author: String
    let cover: CoverReference?
    let progress: Double?
    let availableMediaKinds: [LibraryMediaKind]
}

struct ContinueReadingItem: Codable, Equatable, Sendable {
    let work: WorkCard
    let volumeTitle: String?
    let positionLabel: String?
}

struct WorkPage: Codable, Equatable, Sendable {
    let works: [WorkCard]
    let page: Int
    let pageSize: Int
    let total: Int
    let totalPages: Int
}

struct LibraryGrouping: Identifiable, Codable, Equatable, Sendable {
    let id: String
    let kind: FacetKind
    let name: String
    let workCount: Int
    let representativeWorks: [WorkCard]
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
    let works: [WorkCard]
    let page: Int
    let pageSize: Int
    let total: Int
    let totalPages: Int
}

struct WorkVolume: Identifiable, Codable, Equatable, Sendable {
    let id: String
    let title: String
    let formatLabel: String
    let sizeLabel: String?
    let progress: Double?
    let isReadable: Bool?
    let isSelected: Bool
}

struct WorkChapter: Identifiable, Codable, Equatable, Sendable {
    let id: String
    let title: String
    let progress: Double?
    let isCurrent: Bool
}

struct WorkDetailContent: Codable, Equatable, Sendable {
    let work: WorkCard
    let description: String?
    let tags: [String]
    let seriesFacet: FacetIdentity?
    let authorFacets: [FacetIdentity]
    let availableMediaKinds: [LibraryMediaKind]
    let selectedMediaKind: LibraryMediaKind?
    let selectedVolumeID: String?
    let readingStatus: LibraryReadingStatus?
    let volumes: [WorkVolume]
    let chapters: [WorkChapter]
}

protocol ContentClient: Sendable {
    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem?
    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [WorkCard]
    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [WorkCard]
    func fetchWorks(context: ContentRequestContext, query: WorksQuery) async throws -> WorkPage
    func fetchWorksResult(context: ContentRequestContext, query: WorksQuery) async throws -> ContentFetch<WorkPage>
    func restoreWorksResult(context: ContentRequestContext, query: WorksQuery) async throws -> ContentFetch<WorkPage>?
    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage
    func fetchGroupingsResult(context: ContentRequestContext, query: GroupingsQuery) async throws -> ContentFetch<GroupingPage>
    func restoreGroupingsResult(context: ContentRequestContext, query: GroupingsQuery) async throws -> ContentFetch<GroupingPage>?
    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage
    func fetchFacetResult(context: ContentRequestContext, query: FacetQuery) async throws -> ContentFetch<FacetPage>
    func restoreFacetResult(context: ContentRequestContext, query: FacetQuery) async throws -> ContentFetch<FacetPage>?
    func fetchWorkDetail(context: ContentRequestContext, query: WorkDetailQuery) async throws -> WorkDetailContent
    func fetchCoverData(context: ContentRequestContext, reference: CoverReference) async throws -> Data
}

extension ContentClient {
    func fetchWorksResult(context: ContentRequestContext, query: WorksQuery) async throws -> ContentFetch<WorkPage> {
        ContentFetch(value: try await fetchWorks(context: context, query: query), provenance: .network, isStale: false)
    }

    func restoreWorksResult(context: ContentRequestContext, query: WorksQuery) async throws -> ContentFetch<WorkPage>? { nil }

    func fetchGroupingsResult(context: ContentRequestContext, query: GroupingsQuery) async throws -> ContentFetch<GroupingPage> {
        ContentFetch(value: try await fetchGroupings(context: context, query: query), provenance: .network, isStale: false)
    }

    func restoreGroupingsResult(context: ContentRequestContext, query: GroupingsQuery) async throws -> ContentFetch<GroupingPage>? { nil }

    func fetchFacetResult(context: ContentRequestContext, query: FacetQuery) async throws -> ContentFetch<FacetPage> {
        ContentFetch(value: try await fetchFacet(context: context, query: query), provenance: .network, isStale: false)
    }

    func restoreFacetResult(context: ContentRequestContext, query: FacetQuery) async throws -> ContentFetch<FacetPage>? { nil }
}

struct UnavailableContentClient: ContentClient {
    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? {
        throw ContentClientError.transport
    }

    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [WorkCard] {
        throw ContentClientError.transport
    }

    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [WorkCard] {
        throw ContentClientError.transport
    }

    func fetchWorks(context: ContentRequestContext, query: WorksQuery) async throws -> WorkPage {
        throw ContentClientError.transport
    }

    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage {
        throw ContentClientError.transport
    }

    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage {
        throw ContentClientError.transport
    }

    func fetchWorkDetail(context: ContentRequestContext, query: WorkDetailQuery) async throws -> WorkDetailContent {
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
        let repository = IosCompositionKt.createIosContentRepository(
            cookieStore: cookieStore,
            snapshotStore: LibrarySnapshotFilePayloadStore()
        )
        return SharedContentClient(repository: repository)
    }
}
