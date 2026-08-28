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
                progress: item.progress
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
        let result = try await repository.loadBooks(context: sharedContext(context), query: sharedBooksQuery(query))
        let payload: ErmaoShared.LibraryPage<ErmaoShared.BookSummary> = try contentValue(result)
        return BookPage(
            books: try mapBooks(payload.items),
            page: Int(payload.page),
            pageSize: Int(payload.pageSize),
            total: Int(payload.total),
            totalPages: Int(payload.totalPages)
        )
    }

    func fetchLibraryOptions(context: ContentRequestContext) async throws -> [LibrarySourceOption] {
        let result = try await repository.loadLibraryOptions(context: sharedContext(context))
        let values: [ErmaoShared.LibraryOption] = try contentValue(result)
        return values.map { LibrarySourceOption(id: $0.id, name: $0.name) }
    }

    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage {
        let result = try await repository.loadGroupings(context: sharedContext(context), query: sharedGroupingQuery(query))
        let payload: ErmaoShared.LibraryPage<ErmaoShared.GroupingSummary> = try contentValue(result)
        return GroupingPage(
            groups: try payload.items.map { rawValue in
                guard let group = rawValue as? ErmaoShared.GroupingSummary else {
                    throw ContentClientError.invalidResponse
                }
                return LibraryGrouping(
                    id: group.id,
                    kind: query.kind,
                    name: group.name,
                    bookCount: Int(group.bookCount),
                    representativeBooks: group.representativeBooks.map(mapBook)
                )
            },
            page: Int(payload.page),
            pageSize: Int(payload.pageSize),
            total: Int(payload.total),
            totalPages: Int(payload.totalPages)
        )
    }

    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage {
        let result = try await repository.loadFacet(context: sharedContext(context), query: sharedFacetQuery(query))
        let payload: ErmaoShared.FacetPage = try contentValue(result)
        return FacetPage(
            facet: mapFacet(payload.facet),
            books: try mapBooks(payload.books.items),
            page: Int(payload.books.page),
            pageSize: Int(payload.books.pageSize),
            total: Int(payload.books.total),
            totalPages: Int(payload.books.totalPages)
        )
    }

    func fetchBookDetail(context: ContentRequestContext, query: BookDetailQuery) async throws -> BookDetailContent {
        let result = try await repository.loadBookDetail(
            context: sharedContext(context),
            query: ErmaoShared.BookDetailQuery(bookId: query.bookID, resourceId: query.resourceID)
        )
        let value: ErmaoShared.BookDetailSummary = try contentValue(result)
        let selectedResourceID = query.resourceID
        let resources = value.resources.filter { !$0.hidden && $0.bookId == value.id }
            .map { mapResource($0, selectedResourceID: selectedResourceID) }
        let selectedProgress = value.continueResourceProgress > 0 ? value.continueResourceProgress : nil
        let readingStatus: LibraryReadingStatus = if value.completed { .finished } else if resources.contains(where: { ($0.progress ?? 0) > 0 }) { .reading } else { .unread }
        return BookDetailContent(
            book: BookCard(
                id: value.id,
                title: value.title,
                author: value.author,
                cover: cover(value.coverUrl),
                progress: selectedProgress
            ),
            description: value.description_,
            tags: value.tags,
            seriesFacet: value.seriesFacet.map(mapFacet),
            seriesIndex: value.seriesIndex?.doubleValue,
            authorFacets: value.authorFacets.map(mapFacet),
            resources: resources,
            selectedResourceID: selectedResourceID,
            readingStatus: readingStatus,
            chapters: [],
            rootSourceNodeID: value.sourceNodeId,
            continueResourceID: value.continueResourceId
        )
    }

    func fetchBookResources(context: ContentRequestContext, bookID: String, page: Int, pageSize: Int) async throws -> BookResourcePage {
        let result = try await repository.loadBookResources(
            context: sharedContext(context),
            query: ErmaoShared.BookResourcePageQuery(bookId: bookID, page: Int32(page), pageSize: Int32(pageSize))
        )
        let value: ErmaoShared.BookResourcePage = try contentValue(result)
        return BookResourcePage(
            resources: value.resources.filter { !$0.hidden && $0.bookId == bookID }
                .map { mapResource($0, selectedResourceID: nil) },
            page: Int(value.page),
            total: Int(value.total),
            totalPages: Int(value.totalPages)
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
        let result = try await repository.loadBookContents(
            context: sharedContext(context),
            query: ErmaoShared.BookContentsQuery(
                bookId: bookID,
                sourceNodeId: sourceNodeID,
                sort: sharedContentSort(sort),
                page: Int32(page),
                pageSize: Int32(pageSize)
            )
        )
        let value: ErmaoShared.BookContentsPage = try contentValue(result)
        return BookContentsPage(
            bookID: value.bookId,
            currentSourceNodeID: value.currentSourceNodeId,
            currentResourceID: value.currentResourceId,
            currentNode: mapContentEntry(value.currentNode),
            currentResourceIDs: value.currentResourceIds,
            parentSourceNodeID: value.parentSourceNodeId,
            breadcrumbs: value.breadcrumbs.map(mapContentEntry),
            entries: value.entries.map(mapContentEntry),
            page: Int(value.page),
            pageSize: Int(value.pageSize),
            total: Int(value.total),
            totalPages: Int(value.totalPages)
        )
    }

    func fetchBookChapters(
        context: ContentRequestContext,
        bookID: String,
        resourceID: String,
        page: Int,
        pageSize: Int
    ) async throws -> BookChapterPage {
        let result = try await repository.loadResourceReadingUnits(
            context: sharedContext(context),
            query: ErmaoShared.ResourceReadingUnitsQuery(
                bookId: bookID,
                resourceId: resourceID,
                page: Int32(page),
                pageSize: Int32(pageSize)
            )
        )
        let value: ErmaoShared.ResourceReadingUnitsPage = try contentValue(result)
        let currentSortOrder = value.currentChapterSortOrder?.intValue
        let currentIndex = value.currentChapterIndex?.intValue
        let chapters = value.units.enumerated().compactMap { index, unit -> BookChapter? in
            guard unit.unitType.lowercased() == "chapter" else { return nil }
            let sortOrder = Int(unit.sortOrder)
            let state: ChapterReadingState
            if sortOrder == currentSortOrder || index == currentIndex {
                state = .current
            } else if let currentSortOrder, sortOrder < currentSortOrder {
                state = .read
            } else if let currentIndex, index < currentIndex {
                state = .read
            } else {
                state = .unread
            }
            return BookChapter(
                id: unit.id,
                title: unit.title ?? String(
                    format: String(localized: "work.chapter.fallback.format"),
                    locale: .current,
                    (page - 1) * pageSize + index + 1
                ),
                progress: state == .current ? value.progress : nil,
                isCurrent: state == .current,
                href: unit.href,
                sortOrder: sortOrder,
                readingOrderPosition: unit.metadata.readingOrderPosition?.intValue,
                state: state
            )
        }
        return BookChapterPage(
            resourceID: value.resourceId,
            chapters: chapters,
            page: Int(value.page),
            pageSize: Int(value.pageSize),
            total: Int(value.total),
            totalPages: Int(value.totalPages)
        )
    }

    func fetchResourceDetail(
        context: ContentRequestContext,
        bookID: String,
        resourceID: String,
        page: Int,
        pageSize: Int
    ) async throws -> BookResourceDetailPage {
        let result = try await repository.loadResourceReadingUnits(
            context: sharedContext(context),
            query: ErmaoShared.ResourceReadingUnitsQuery(
                bookId: bookID,
                resourceId: resourceID,
                page: Int32(page),
                pageSize: Int32(pageSize)
            )
        )
        let value: ErmaoShared.ResourceReadingUnitsPage = try contentValue(result)
        let currentSortOrder = value.currentChapterSortOrder?.intValue
        let currentIndex = value.currentChapterIndex?.intValue
        let units = value.units.enumerated().map { index, unit in
            let sortOrder = Int(unit.sortOrder)
            let chapterState: ChapterReadingState? = if unit.unitType.lowercased() != "chapter" {
                nil
            } else if sortOrder == currentSortOrder || index == currentIndex {
                .current
            } else if let currentSortOrder, sortOrder < currentSortOrder {
                .read
            } else if let currentIndex, index < currentIndex {
                .read
            } else {
                .unread
            }
            return BookResourceDetailUnit(
                id: unit.id,
                title: unit.title ?? "",
                unitType: unit.unitType,
                assetID: unit.assetId,
                href: unit.href,
                sortOrder: sortOrder,
                pageNumber: unit.metadata.pageNumber?.intValue,
                previewURL: unit.previewUrl,
                level: unit.metadata.level?.intValue,
                durationMillis: unit.durationMillis?.int64Value,
                discNumber: unit.discNumber?.intValue,
                trackNumber: unit.trackNumber?.intValue,
                chapterState: chapterState
            )
        }
        return BookResourceDetailPage(
            resourceID: value.resourceId,
            units: units,
            page: Int(value.page),
            pageSize: Int(value.pageSize),
            total: Int(value.total),
            totalPages: Int(value.totalPages),
            currentHref: value.currentHref,
            currentChapterSortOrder: currentSortOrder,
            currentPageNumber: value.currentPageNumber?.intValue,
            progress: value.progress
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
            query: query.query, libraryId: query.libraryID, sort: sharedSort(query.sort), viewMode: .grid,
            filters: ErmaoShared.PublicKt.createLibraryFilters(
                readingStatus: query.filters.readingStatus.map(sharedReadingStatus)
            ), page: Int32(query.page), pageSize: Int32(query.pageSize)
        )
    }

    private func sharedGroupingQuery(_ query: GroupingsQuery) -> ErmaoShared.GroupingQuery {
        ErmaoShared.GroupingQuery(kind: sharedFacetKind(query.kind), query: query.query, page: Int32(query.page), pageSize: Int32(query.pageSize))
    }

    private func sharedFacetQuery(_ query: FacetQuery) -> ErmaoShared.FacetQuery {
        ErmaoShared.FacetQuery(kind: sharedFacetKind(query.kind), facetId: query.facetID, sort: sharedFacetSort(query.sort), page: Int32(query.page), pageSize: Int32(query.pageSize))
    }

    private func sharedContentSort(_ sort: BookContentSort) -> ErmaoShared.BookContentSort {
        switch sort {
        case .nameAscending: .nameascending
        case .nameDescending: .namedescending
        case .updatedDescending: .updateddescending
        case .updatedAscending: .updatedascending
        case .typeAscending: .typeascending
        case .sizeDescending: .sizedescending
        }
    }

    private func contentValue<Value>(_ result: any ErmaoShared.ContentResult) throws -> Value {
        if let failure = result as? ErmaoShared.ContentResultFailure { throw mapError(failure.error) }
        guard let content = result as? ErmaoShared.ContentResultContent<AnyObject>, let value = content.value as? Value else { throw ContentClientError.invalidResponse }
        return value
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
        BookCard(id: value.id, title: value.title, author: value.author, cover: cover(value.coverUrl), progress: value.progress > 0 ? value.progress : nil, completed: value.completed?.boolValue)
    }

    private func mapBooks(_ values: [Any]) throws -> [BookCard] {
        try values.map { value in
            guard let book = value as? ErmaoShared.BookSummary else {
                throw ContentClientError.invalidResponse
            }
            return mapBook(book)
        }
    }

    private func mapResource(_ value: ErmaoShared.Resource, selectedResourceID: String?) -> BookResource {
        BookResource(
            id: value.id, bookID: value.bookId, sourceNodeID: value.sourceNodeId, title: value.title,
            description: value.description_, format: value.format, readerType: value.readerType,
            resourceIndex: value.resourceIndex?.doubleValue, cover: cover(value.coverUrl),
            sizeLabel: ByteCountFormatter.string(fromByteCount: value.sizeBytes, countStyle: .file),
            progress: value.progress > 0 ? value.progress : nil, isReadable: value.readable,
            isSelected: value.id == selectedResourceID, sortOrder: Int(value.sortOrder),
            publisher: value.publisher, publishedAt: value.publishedAt, language: value.language,
            isbn: value.isbn, identifier: value.identifier, narrator: value.narrator,
            pageCount: value.pageCount?.intValue, metadataSource: nil,
            kindleSendAvailable: value.kindleSendAvailable,
            assets: value.assets.map { asset in
                ResourceAsset(
                    id: asset.id, resourceID: asset.resourceId,
                    path: asset.url ?? asset.downloadUrl ?? "", role: asset.role, mimeType: asset.mimeType,
                    sizeBytes: asset.sizeBytes, displaySize: asset.displaySize,
                    sortOrder: asset.sortOrder?.intValue, url: asset.url, downloadURL: asset.downloadUrl
                )
            },
            importStatus: value.importStatus
        )
    }

    private func mapContentEntry(_ value: ErmaoShared.BookContentEntry) -> BookContentEntry {
        BookContentEntry(
            sourceNodeID: value.sourceNodeId,
            parentSourceNodeID: value.parentSourceNodeId,
            name: value.name,
            title: value.title,
            description: value.description_,
            kind: value.kind,
            physicalKind: value.physicalKind,
            sizeBytes: value.sizeBytes?.int64Value,
            hasChildren: value.hasChildren,
            resourceID: value.resourceId,
            representativeResourceID: value.representativeResourceId,
            cover: value.coverUrl.flatMap(cover)
        )
    }

    private func cover(_ path: String) -> CoverReference? { path.isEmpty ? nil : CoverReference(path: path) }

    private func mapFacet(_ value: ErmaoShared.AppliedFacet) -> FacetIdentity {
        FacetIdentity(id: value.id, kind: value.kind.name == "Series" ? .series : .author, name: value.name)
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
