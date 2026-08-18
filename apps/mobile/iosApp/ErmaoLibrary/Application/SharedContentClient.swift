import Foundation
@preconcurrency import ErmaoShared

actor SharedContentClient: ContentClient {
    private let repository: any ErmaoShared.ContentRepository

    init(repository: any ErmaoShared.ContentRepository) {
        self.repository = repository
    }

    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? {
        let result = try await repository.loadContinueReading(context: sharedContext(context))
        let item: ErmaoShared.ContinueReadingItem? = try contentValue(result)
        guard let item else { return nil }
        let work = WorkCard(
            id: item.workId,
            title: item.title,
            author: item.author,
            cover: cover(item.coverUrl),
            progress: item.progress,
            availableMediaKinds: [mapMediaKind(item.mediaKind)].compactMap { $0 }
        )
        return ContinueReadingItem(work: work, volumeTitle: item.volumeTitle, positionLabel: item.narrator)
    }

    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [WorkCard] {
        let result = try await repository.loadRecentReading(
            context: sharedContext(context),
            limit: Int32(limit)
        )
        let values: [ErmaoShared.WorkSummary] = try contentValue(result)
        return values.map(mapWork)
    }

    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [WorkCard] {
        let result = try await repository.loadRecentAdded(
            context: sharedContext(context),
            limit: Int32(limit)
        )
        let values: [ErmaoShared.WorkSummary] = try contentValue(result)
        return values.map(mapWork)
    }

    func fetchWorks(context: ContentRequestContext, query: WorksQuery) async throws -> WorkPage {
        try await fetchWorksResult(context: context, query: query).value
    }

    func fetchWorksResult(context: ContentRequestContext, query: WorksQuery) async throws -> ContentFetch<WorkPage> {
        let sharedQuery = sharedWorksQuery(query)
        let result = try await repository.loadWorks(context: sharedContext(context), query: sharedQuery)
        let payload: ContentFetch<ErmaoShared.LibraryPage<ErmaoShared.WorkSummary>> = try contentFetch(result)
        return mapWorksPayload(payload)
    }

    private func mapWorksPayload(
        _ payload: ContentFetch<ErmaoShared.LibraryPage<ErmaoShared.WorkSummary>>
    ) -> ContentFetch<WorkPage> {
        ContentFetch(value: WorkPage(
            works: payload.value.items.compactMap { ($0 as? ErmaoShared.WorkSummary).map(mapWork) },
            page: Int(payload.value.page),
            pageSize: Int(payload.value.pageSize),
            total: Int(payload.value.total),
            totalPages: Int(payload.value.totalPages)
        ), provenance: payload.provenance, isStale: payload.isStale)
    }

    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage {
        try await fetchGroupingsResult(context: context, query: query).value
    }

    func fetchGroupingsResult(context: ContentRequestContext, query: GroupingsQuery) async throws -> ContentFetch<GroupingPage> {
        let result = try await repository.loadGroupings(
            context: sharedContext(context),
            query: sharedGroupingQuery(query)
        )
        let payload: ContentFetch<ErmaoShared.LibraryPage<ErmaoShared.GroupingSummary>> = try contentFetch(result)
        return mapGroupingsPayload(payload, kind: query.kind)
    }

    private func mapGroupingsPayload(
        _ payload: ContentFetch<ErmaoShared.LibraryPage<ErmaoShared.GroupingSummary>>,
        kind: FacetKind
    ) -> ContentFetch<GroupingPage> {
        ContentFetch(value: GroupingPage(
            groups: payload.value.items.compactMap { raw in
                guard let group = raw as? ErmaoShared.GroupingSummary else { return nil }
                return LibraryGrouping(
                    id: group.id,
                    kind: kind,
                    name: group.name,
                    workCount: Int(group.bookCount),
                    representativeWorks: group.representativeWorks.map(mapWork)
                )
            },
            page: Int(payload.value.page),
            pageSize: Int(payload.value.pageSize),
            total: Int(payload.value.total),
            totalPages: Int(payload.value.totalPages)
        ), provenance: payload.provenance, isStale: payload.isStale)
    }

    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage {
        try await fetchFacetResult(context: context, query: query).value
    }

    func fetchFacetResult(context: ContentRequestContext, query: FacetQuery) async throws -> ContentFetch<FacetPage> {
        let result = try await repository.loadFacet(
            context: sharedContext(context),
            query: sharedFacetQuery(query)
        )
        let payload: ContentFetch<ErmaoShared.FacetPage> = try contentFetch(result)
        return mapFacetPayload(payload)
    }

    private func mapFacetPayload(_ payload: ContentFetch<ErmaoShared.FacetPage>) -> ContentFetch<FacetPage> {
        ContentFetch(value: FacetPage(
            facet: mapFacet(payload.value.facet),
            works: payload.value.works.items.compactMap { ($0 as? ErmaoShared.WorkSummary).map(mapWork) },
            page: Int(payload.value.works.page),
            pageSize: Int(payload.value.works.pageSize),
            total: Int(payload.value.works.total),
            totalPages: Int(payload.value.works.totalPages)
        ), provenance: payload.provenance, isStale: payload.isStale)
    }

    func fetchWorkDetail(context: ContentRequestContext, query: WorkDetailQuery) async throws -> WorkDetailContent {
        let result = try await repository.loadWorkDetail(
            context: sharedContext(context),
            query: ErmaoShared.WorkDetailQuery(
                workId: query.workID,
                volumeId: query.volumeID
            )
        )
        let value: ErmaoShared.WorkDetailSummary = try contentValue(result)
        let versions = value.versions.map { version in
            WorkVersionContent(
                id: version.id,
                sourceKey: version.sourceKey,
                sourceName: version.sourceName,
                volumes: version.volumes.map { volume in
                    mapVolume(volume, selectedVolumeID: nil)
                },
                volumeCount: Int(version.volumeCount)
            )
        }
        let allVolumes = versions.flatMap(\.volumes)
        let selectedVolumeID = query.volumeID
            ?? value.continueVolumeId
            ?? allVolumes.first(where: { ($0.progress ?? 0) < 100 })?.id
            ?? allVolumes.first?.id
        let selectedVersionId = query.versionId
            ?? versions.first(where: { version in version.volumes.contains(where: { $0.id == selectedVolumeID }) })?.id
            ?? versions.first?.id
        let selectedVersion = versions.first(where: { $0.id == selectedVersionId }) ?? versions.first
        let volumes = (selectedVersion?.volumes ?? []).map { volume in
            WorkVolume(
                id: volume.id,
                versionID: volume.versionID,
                title: volume.title,
                formatLabel: volume.formatLabel,
                readerType: volume.readerType,
                suggestedMediaKind: volume.suggestedMediaKind,
                volumeIndex: volume.volumeIndex,
                cover: volume.cover,
                sizeLabel: volume.sizeLabel,
                progress: volume.progress,
                isReadable: volume.isReadable,
                isSelected: volume.id == selectedVolumeID,
                sortOrder: volume.sortOrder,
                publisher: volume.publisher,
                publishedAt: volume.publishedAt,
                language: volume.language,
                isbn: volume.isbn,
                identifier: volume.identifier,
                narrator: volume.narrator,
                pageCount: volume.pageCount,
                metadataSource: volume.metadataSource,
                kindleSendAvailable: volume.kindleSendAvailable,
                files: volume.files
            )
        }
        let selectedVolumeCount = selectedVersion?.volumeCount ?? volumes.count
        let selectedProgress = value.continueVolumeProgress > 0 ? value.continueVolumeProgress : nil
        let readingStatus: LibraryReadingStatus = if value.completed {
            .finished
        } else if selectedProgress != nil {
            .reading
        } else {
            .unread
        }
        return WorkDetailContent(
            work: WorkCard(
                id: value.id,
                title: value.title,
                author: value.author,
                cover: cover(value.coverUrl),
                progress: selectedProgress,
                availableMediaKinds: []
            ),
            description: value.description_,
            tags: value.tags,
            seriesFacet: value.seriesFacet.map(mapFacet),
            seriesIndex: value.seriesIndex?.doubleValue,
            authorFacets: value.authorFacets.map(mapFacet),
            versions: versions,
            selectedVersionId: selectedVersionId,
            selectedVolumeID: selectedVolumeID,
            readingStatus: readingStatus,
            volumes: volumes,
            volumeCount: selectedVolumeCount,
            chapters: []
        )
    }

    func fetchWorkVolumes(
        context: ContentRequestContext,
        workID: String,
        versionId: String,
        page: Int,
        pageSize: Int
    ) async throws -> WorkVolumePage {
        let result = try await repository.loadWorkVolumes(
            context: sharedContext(context),
            query: ErmaoShared.WorkVolumePageQuery(
                workId: workID,
                versionId: versionId,
                page: Int32(page),
                pageSize: Int32(pageSize)
            )
        )
        let value: ErmaoShared.WorkVolumePage = try contentValue(result)
        let volumes = value.volumes.map { volume in
            mapVolume(volume, selectedVolumeID: nil)
        }
        return WorkVolumePage(
            volumes: volumes,
            page: Int(value.page),
            total: Int(value.total),
            totalPages: Int(value.totalPages)
        )
    }

    func fetchCoverData(context: ContentRequestContext, reference: CoverReference) async throws -> Data {
        let result = try await repository.loadCover(
            context: sharedContext(context),
            apiPath: reference.path,
            etag: nil
        )
        let value: ErmaoShared.AuthenticatedCover = try contentValue(result)
        let bytes = value.bytes
        return Data((0..<Int(bytes.size)).map { UInt8(bitPattern: bytes.get(index: Int32($0))) })
    }

    private func sharedContext(_ value: ContentRequestContext) -> ErmaoShared.ContentRequestContext {
        ErmaoShared.PublicKt.createContentRequestContext(
            profileId: value.profileID,
            displayName: value.profileDisplayName,
            baseUrl: value.baseURL,
            serverIdentity: value.serverIdentity,
            acceptsInsecureTls: value.acceptsInsecureTLS,
            userId: value.userID,
            authorizationVersion: value.authorizationVersion
        )
    }

    private func sharedWorksQuery(_ query: WorksQuery) -> ErmaoShared.WorksQuery {
        ErmaoShared.WorksQuery(
            query: query.query,
            sort: sharedSort(query.sort),
            viewMode: .grid,
            filters: ErmaoShared.PublicKt.createLibraryFilters(
                mediaKindWireValues: query.filters.mediaKinds.map(\.rawValue),
                readingStatuses: Set(query.filters.readingStatuses.map(sharedReadingStatus))
            ),
            page: Int32(query.page),
            pageSize: Int32(query.pageSize)
        )
    }

    private func sharedGroupingQuery(_ query: GroupingsQuery) -> ErmaoShared.GroupingQuery {
        ErmaoShared.GroupingQuery(
            kind: sharedFacetKind(query.kind),
            query: query.query,
            page: Int32(query.page),
            pageSize: Int32(query.pageSize)
        )
    }

    private func sharedFacetQuery(_ query: FacetQuery) -> ErmaoShared.FacetQuery {
        ErmaoShared.FacetQuery(
            kind: sharedFacetKind(query.kind),
            facetId: query.facetID,
            sort: sharedFacetSort(query.sort),
            page: Int32(query.page),
            pageSize: Int32(query.pageSize)
        )
    }

    private func contentValue<Value>(_ result: any ErmaoShared.ContentResult) throws -> Value {
        if let failure = result as? ErmaoShared.ContentResultFailure { throw mapError(failure.error) }
        guard let content = result as? ErmaoShared.ContentResultContent<AnyObject>,
              let value = content.value as? Value else { throw ContentClientError.invalidResponse }
        return value
    }

    private func contentFetch<Value: Sendable>(_ result: any ErmaoShared.ContentResult) throws -> ContentFetch<Value> {
        if let failure = result as? ErmaoShared.ContentResultFailure { throw mapError(failure.error) }
        guard let content = result as? ErmaoShared.ContentResultContent<AnyObject>,
              let value = content.value as? Value else { throw ContentClientError.invalidResponse }
        return ContentFetch(
            value: value,
            provenance: .network,
            isStale: false
        )
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

    private func mapWork(_ value: ErmaoShared.WorkSummary) -> WorkCard {
        WorkCard(
            id: value.id,
            title: value.title,
            author: value.author,
            cover: cover(value.coverUrl),
            progress: value.progress > 0 ? value.progress : nil,
            availableMediaKinds: value.availableMediaKinds.compactMap(mapMediaKind)
        )
    }

    private func mapVolume(_ volume: ErmaoShared.Volume, selectedVolumeID: String?) -> WorkVolume {
        WorkVolume(
            id: volume.id,
            versionID: volume.versionId,
            title: volume.title,
            formatLabel: volume.format,
            readerType: volume.readerType,
            suggestedMediaKind: {
                guard let raw = volume.classification.suggestedMediaKind else { return nil }
                return mapMediaKind(raw)
            }(),
            volumeIndex: volume.volumeIndex?.doubleValue,
            cover: cover(volume.coverUrl),
            sizeLabel: ByteCountFormatter.string(
                fromByteCount: volume.sizeBytes,
                countStyle: .file
            ),
            progress: volume.progress > 0 ? volume.progress : nil,
            isReadable: volume.readable,
            isSelected: volume.id == selectedVolumeID,
            sortOrder: Int(volume.sortOrder),
            publisher: volume.publisher,
            publishedAt: volume.publishedAt,
            language: volume.language,
            isbn: volume.isbn,
            identifier: volume.identifier,
            narrator: volume.narrator,
            pageCount: volume.pageCount?.intValue,
            metadataSource: volume.origin,
            kindleSendAvailable: volume.kindleSendAvailable,
            files: volume.files.map {
                WorkVolumeFile(
                    id: $0.id,
                    path: $0.path,
                    sizeBytes: $0.sizeBytes,
                    displaySize: $0.displaySize
                )
            }
        )
    }

    private func cover(_ path: String) -> CoverReference? {
        path.isEmpty ? nil : CoverReference(path: path)
    }

    private func mapFacet(_ value: ErmaoShared.AppliedFacet) -> FacetIdentity {
        FacetIdentity(id: value.id, kind: value.kind.name == "Series" ? .series : .author, name: value.name)
    }

    private func mapMediaKind(_ value: Any) -> LibraryMediaKind? {
        if let raw = value as? String { return LibraryMediaKind(rawValue: raw) }
        let description = String(describing: value).uppercased()
        return LibraryMediaKind.allKnown.first { description.contains($0.rawValue) }
    }

    private func sharedSort(_ value: LibrarySort) -> ErmaoShared.LibrarySort {
        switch value {
        case .recentAdded: .recentlyadded
        case .recentRead: .recentlyread
        case .title: .title
        case .author: .author
        }
    }

    private func sharedFacetKind(_ value: FacetKind) -> ErmaoShared.FacetKind {
        value == .series ? .series : .author
    }

    private func sharedFacetSort(_ value: LibraryFacetSort) -> ErmaoShared.FacetSort {
        switch value {
        case .seriesIndex: .seriesindex
        case .recentRead: .recentlyread
        }
    }

    private func sharedReadingStatus(_ value: LibraryReadingStatus) -> ErmaoShared.ReadingStatus {
        switch value {
        case .unread: .unread
        case .reading: .reading
        case .finished: .finished
        }
    }
}

private extension LibraryMediaKind {
    static let allKnown: [LibraryMediaKind] = [.ebook, .comic, .audiobook]
}
