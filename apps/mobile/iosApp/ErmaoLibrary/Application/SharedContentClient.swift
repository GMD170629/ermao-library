import Foundation
@preconcurrency import ErmaoShared

/// iOS adapter for the resource-first shared library contract.
actor SharedContentClient: ContentClient {
    private let repository: any ErmaoShared.ContentRepository

    init(repository: any ErmaoShared.ContentRepository) {
        self.repository = repository
    }

    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? {
        let result = try await repository.loadContinueReading(context: sharedContext(context))
        let item: ErmaoShared.ContinueReadingItem? = try contentValue(result)
        guard let item else { return nil }
        return ContinueReadingItem(
            book: BookCard(
                id: item.bookId,
                title: item.title,
                author: item.author,
                cover: cover(item.coverUrl),
                progress: item.progress,
                availableMediaKinds: [mapMediaKind(item.mediaKind)].compactMap { $0 }
            ),
            resourceTitle: item.resourceTitle,
            positionLabel: item.narrator ?? item.chapter
        )
    }

    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [BookCard] {
        let result = try await repository.loadRecentReading(context: sharedContext(context), limit: Int32(limit))
        let values: [ErmaoShared.BookSummary] = try contentValue(result)
        return values.map(mapBook)
    }

    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [BookCard] {
        let result = try await repository.loadRecentAdded(context: sharedContext(context), limit: Int32(limit))
        let values: [ErmaoShared.BookSummary] = try contentValue(result)
        return values.map(mapBook)
    }

    func fetchBooks(context: ContentRequestContext, query: BooksQuery) async throws -> BookPage {
        try await fetchBooksResult(context: context, query: query).value
    }

    func fetchBooksResult(context: ContentRequestContext, query: BooksQuery) async throws -> ContentFetch<BookPage> {
        let result = try await repository.loadBooks(context: sharedContext(context), query: sharedBooksQuery(query))
        let payload: ContentFetch<ErmaoShared.LibraryPage<ErmaoShared.BookSummary>> = try contentFetch(result)
        return ContentFetch(
            value: BookPage(
                books: payload.value.items.map(mapBook),
                page: Int(payload.value.page),
                pageSize: Int(payload.value.pageSize),
                total: Int(payload.value.total),
                totalPages: Int(payload.value.totalPages)
            ),
            provenance: payload.provenance,
            isStale: payload.isStale
        )
    }

    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage {
        try await fetchGroupingsResult(context: context, query: query).value
    }

    func fetchGroupingsResult(context: ContentRequestContext, query: GroupingsQuery) async throws -> ContentFetch<GroupingPage> {
        let result = try await repository.loadGroupings(context: sharedContext(context), query: sharedGroupingQuery(query))
        let payload: ContentFetch<ErmaoShared.LibraryPage<ErmaoShared.GroupingSummary>> = try contentFetch(result)
        return ContentFetch(
            value: GroupingPage(
                groups: payload.value.items.map { group in
                    LibraryGrouping(
                        id: group.id,
                        kind: query.kind,
                        name: group.name,
                        bookCount: Int(group.bookCount),
                        representativeBooks: group.representativeBooks.map(mapBook)
                    )
                },
                page: Int(payload.value.page),
                pageSize: Int(payload.value.pageSize),
                total: Int(payload.value.total),
                totalPages: Int(payload.value.totalPages)
            ),
            provenance: payload.provenance,
            isStale: payload.isStale
        )
    }

    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage {
        try await fetchFacetResult(context: context, query: query).value
    }

    func fetchFacetResult(context: ContentRequestContext, query: FacetQuery) async throws -> ContentFetch<FacetPage> {
        let result = try await repository.loadFacet(context: sharedContext(context), query: sharedFacetQuery(query))
        let payload: ContentFetch<ErmaoShared.FacetPage> = try contentFetch(result)
        return ContentFetch(
            value: FacetPage(
                facet: mapFacet(payload.value.facet),
                books: payload.value.books.items.map(mapBook),
                page: Int(payload.value.books.page),
                pageSize: Int(payload.value.books.pageSize),
                total: Int(payload.value.books.total),
                totalPages: Int(payload.value.books.totalPages)
            ),
            provenance: payload.provenance,
            isStale: payload.isStale
        )
    }

    func fetchBookDetail(context: ContentRequestContext, query: BookDetailQuery) async throws -> BookDetailContent {
        let result = try await repository.loadBookDetail(
            context: sharedContext(context),
            query: ErmaoShared.BookDetailQuery(bookId: query.bookID, resourceId: query.resourceID)
        )
        let value: ErmaoShared.BookDetailSummary = try contentValue(result)
        let selectedResourceID = query.resourceID
            ?? value.continueResourceId
            ?? value.resources.first(where: { $0.progress < 100 })?.id
            ?? value.resources.first?.id
        let resources = value.resources.map { mapResource($0, selectedResourceID: selectedResourceID) }
        let selectedProgress = value.continueResourceProgress > 0 ? value.continueResourceProgress : nil
        let readingStatus: LibraryReadingStatus = if value.completed { .finished } else if selectedProgress != nil { .reading } else { .unread }
        return BookDetailContent(
            book: BookCard(
                id: value.id,
                title: value.title,
                author: value.author,
                cover: cover(value.coverUrl),
                progress: selectedProgress,
                availableMediaKinds: value.availableMediaKinds.compactMap(mapMediaKind)
            ),
            description: value.description_,
            tags: value.tags,
            seriesFacet: value.seriesFacet.map(mapFacet),
            seriesIndex: value.seriesIndex?.doubleValue,
            authorFacets: value.authorFacets.map(mapFacet),
            resources: resources,
            selectedResourceID: selectedResourceID,
            readingStatus: readingStatus,
            chapters: []
        )
    }

    func fetchBookResources(context: ContentRequestContext, bookID: String, page: Int, pageSize: Int) async throws -> BookResourcePage {
        let result = try await repository.loadBookResources(
            context: sharedContext(context),
            query: ErmaoShared.BookResourcePageQuery(bookId: bookID, page: Int32(page), pageSize: Int32(pageSize))
        )
        let value: ErmaoShared.BookResourcePage = try contentValue(result)
        return BookResourcePage(
            resources: value.resources.map { mapResource($0, selectedResourceID: nil) },
            page: Int(value.page),
            total: Int(value.total),
            totalPages: Int(value.totalPages)
        )
    }

    func fetchCoverData(context: ContentRequestContext, reference: CoverReference) async throws -> Data {
        let result = try await repository.loadCover(context: sharedContext(context), apiPath: reference.path, etag: nil)
        let value: ErmaoShared.AuthenticatedCover = try contentValue(result)
        return Data((0..<Int(value.bytes.size)).map { UInt8(bitPattern: value.bytes.get(index: Int32($0))) })
    }

    private func sharedContext(_ value: ContentRequestContext) -> ErmaoShared.ContentRequestContext {
        ErmaoShared.PublicKt.createContentRequestContext(
            profileId: value.profileID, displayName: value.profileDisplayName, baseUrl: value.baseURL,
            serverIdentity: value.serverIdentity, acceptsInsecureTls: value.acceptsInsecureTLS,
            userId: value.userID, authorizationVersion: value.authorizationVersion
        )
    }

    private func sharedBooksQuery(_ query: BooksQuery) -> ErmaoShared.BooksQuery {
        ErmaoShared.BooksQuery(
            query: query.query, sort: sharedSort(query.sort), viewMode: .grid,
            filters: ErmaoShared.PublicKt.createLibraryFilters(
                mediaKindWireValues: query.filters.mediaKinds.map(\.rawValue),
                readingStatuses: Set(query.filters.readingStatuses.map(sharedReadingStatus))
            ), page: Int32(query.page), pageSize: Int32(query.pageSize)
        )
    }

    private func sharedGroupingQuery(_ query: GroupingsQuery) -> ErmaoShared.GroupingQuery {
        ErmaoShared.GroupingQuery(kind: sharedFacetKind(query.kind), query: query.query, page: Int32(query.page), pageSize: Int32(query.pageSize))
    }

    private func sharedFacetQuery(_ query: FacetQuery) -> ErmaoShared.FacetQuery {
        ErmaoShared.FacetQuery(kind: sharedFacetKind(query.kind), facetId: query.facetID, sort: sharedFacetSort(query.sort), page: Int32(query.page), pageSize: Int32(query.pageSize))
    }

    private func contentValue<Value>(_ result: any ErmaoShared.ContentResult) throws -> Value {
        if let failure = result as? ErmaoShared.ContentResultFailure { throw mapError(failure.error) }
        guard let content = result as? ErmaoShared.ContentResultContent<AnyObject>, let value = content.value as? Value else { throw ContentClientError.invalidResponse }
        return value
    }

    private func contentFetch<Value: Sendable>(_ result: any ErmaoShared.ContentResult) throws -> ContentFetch<Value> {
        if let failure = result as? ErmaoShared.ContentResultFailure { throw mapError(failure.error) }
        guard let content = result as? ErmaoShared.ContentResultContent<AnyObject>, let value = content.value as? Value else { throw ContentClientError.invalidResponse }
        return ContentFetch(value: value, provenance: .network, isStale: false)
    }

    private func mapError(_ error: ErmaoShared.AppError) -> ContentClientError {
        switch error.kind.name {
        case "Unauthorized": .unauthorized
        case "Forbidden", "NotFoundOrUnavailable", "Gone": .inaccessible
        case "NetworkUnavailable", "Timeout", "ServiceUnavailable": .offline
        case "ProtocolViolation": .invalidResponse
        default: .transport
        }
    }

    private func mapBook(_ value: ErmaoShared.BookSummary) -> BookCard {
        BookCard(id: value.id, title: value.title, author: value.author, cover: cover(value.coverUrl), progress: value.progress > 0 ? value.progress : nil, availableMediaKinds: value.availableMediaKinds.compactMap(mapMediaKind))
    }

    private func mapResource(_ value: ErmaoShared.Resource, selectedResourceID: String?) -> BookResource {
        BookResource(
            id: value.id, bookID: value.bookId, sourceNodeID: value.sourceNodeId, title: value.title,
            description: value.description_, format: value.format, readerType: value.readerType,
            mediaKind: mapMediaKind(value.mediaKind) ?? .ebook,
            suggestedMediaKind: value.classification.suggestedMediaKind.flatMap(mapMediaKind),
            resourceIndex: value.resourceIndex?.doubleValue, cover: cover(value.coverUrl),
            sizeLabel: ByteCountFormatter.string(fromByteCount: value.sizeBytes, countStyle: .file),
            progress: value.progress > 0 ? value.progress : nil, isReadable: value.readable,
            isSelected: value.id == selectedResourceID, sortOrder: Int(value.sortOrder),
            publisher: value.publisher, publishedAt: value.publishedAt, language: value.language,
            isbn: value.isbn, identifier: value.identifier, narrator: value.narrator,
            pageCount: value.pageCount?.intValue, metadataSource: value.classification.source,
            kindleSendAvailable: value.kindleSendAvailable,
            assets: value.assets.map { asset in
                ResourceAsset(
                    id: asset.id, resourceID: asset.resourceId,
                    path: asset.url ?? asset.downloadUrl ?? "", role: asset.role, mimeType: asset.mimeType,
                    sizeBytes: asset.sizeBytes, displaySize: asset.displaySize,
                    sortOrder: asset.sortOrder?.intValue, url: asset.url, downloadURL: asset.downloadUrl
                )
            }
        )
    }

    private func cover(_ path: String) -> CoverReference? { path.isEmpty ? nil : CoverReference(path: path) }

    private func mapFacet(_ value: ErmaoShared.AppliedFacet) -> FacetIdentity {
        FacetIdentity(id: value.id, kind: value.kind.name == "Series" ? .series : .author, name: value.name)
    }

    private func mapMediaKind(_ value: Any) -> LibraryMediaKind? {
        if let raw = value as? String { return LibraryMediaKind(rawValue: raw) }
        let description = String(describing: value).uppercased()
        return LibraryMediaKind.allKnown.first { description.contains($0.rawValue) }
    }

    private func sharedSort(_ value: LibrarySort) -> ErmaoShared.LibrarySort {
        switch value { case .recentAdded: .recentlyadded; case .recentRead: .recentlyread; case .title: .title; case .author: .author }
    }

    private func sharedFacetKind(_ value: FacetKind) -> ErmaoShared.FacetKind { value == .series ? .series : .author }

    private func sharedFacetSort(_ value: LibraryFacetSort) -> ErmaoShared.FacetSort {
        switch value { case .seriesIndex: .seriesindex; case .recentRead: .recentlyread }
    }

    private func sharedReadingStatus(_ value: LibraryReadingStatus) -> ErmaoShared.ReadingStatus {
        switch value { case .unread: .unread; case .reading: .reading; case .finished: .finished }
    }
}

private extension LibraryMediaKind {
    static let allKnown: [LibraryMediaKind] = [.ebook, .comic, .audiobook]
}
