import Foundation
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumShared
@preconcurrency import ReadiumStreamer

@MainActor
struct IosOpenedReadiumPublication {
    let publication: Publication
    let canonicalTableOfContents: [Link]
    private let closePublication: () async -> Void
    private let checkSafetyFailure: () throws -> Void

    init(
        publication: Publication,
        canonicalTableOfContents: [Link] = [],
        close: @escaping () async -> Void,
        checkSafetyFailure: @escaping () throws -> Void = {}
    ) {
        self.publication = publication
        self.canonicalTableOfContents = canonicalTableOfContents
        closePublication = close
        self.checkSafetyFailure = checkSafetyFailure
    }

    func close() async {
        await closePublication()
    }

    func checkForSafetyFailure() throws {
        try checkSafetyFailure()
    }
}

@MainActor
final class IosReadiumRuntime {
    private let assetRetriever: AssetRetriever
    private let publicationOpener: PublicationOpener

    init() {
        let httpClient = DefaultHTTPClient(ephemeral: true)
        let retriever = AssetRetriever(httpClient: httpClient)
        assetRetriever = retriever
        publicationOpener = PublicationOpener(
            parser: EPUBParser(),
            contentProtections: [],
            // EPUB resources are protected in the Asset before parsing. This callback is too
            // late for OPF/NCX/container documents and is intentionally a no-op.
            onCreatePublication: { _, _, _ in }
        )
    }

    func open(_ managed: IosManagedPublication) async throws -> IosOpenedReadiumPublication {
        switch managed.sourceFormat {
        case .epub:
            return try await openEPUB(managed)
        case .mobi, .azw, .azw3, .prc:
            return try await openMobiFamily(managed)
        case .txt:
            do {
                let publication = try IosTxtPublicationFactory().open(managed)
                return IosOpenedReadiumPublication(
                    publication: publication,
                    canonicalTableOfContents: publication.manifest.tableOfContents
                ) { publication.close() }
            } catch IosTxtPublicationError.invalidEncoding {
                throw IosReaderFailure(code: .txtEncodingUnsupported)
            } catch let error as IosPublicationSecurityError {
                throw IosReaderFailure.security(error)
            } catch let failure as IosReaderFailure {
                throw failure
            } catch {
                let code: IosReaderFailureCode = (error as NSError).kotlinException is ErmaoShared.TxtPublicationEmptyException
                    ? .txtEmpty : .parseFailed
                throw IosReaderFailure(code: code, underlyingError: error as NSError)
            }
        case .fb2:
            do {
                let publication = try IosFb2PublicationFactory().open(managed)
                return IosOpenedReadiumPublication(
                    publication: publication,
                    canonicalTableOfContents: publication.manifest.tableOfContents
                ) { publication.close() }
            } catch IosFb2PublicationError.limitExceeded {
                throw IosReaderFailure(code: .outOfMemoryRisk)
            } catch let error as IosPublicationSecurityError {
                throw IosReaderFailure.security(error)
            } catch let failure as IosReaderFailure {
                throw failure
            } catch {
                throw IosReaderFailure(code: .parseFailed, underlyingError: error as NSError)
            }
        default:
            throw IosReaderFailure(code: .unsupportedFormat)
        }
    }

    private func openEPUB(_ managed: IosManagedPublication) async throws -> IosOpenedReadiumPublication {
        guard let fileURL = FileURL(url: managed.fileURL) else {
            throw IosReaderFailure(code: .resourceMissing)
        }
        let archiveSafety = try await IosEpubArchiveSafetyPreflight.verify(fileURL: managed.fileURL)
        let asset: ReadiumShared.Asset
        switch await assetRetriever.retrieve(url: fileURL) {
        case let .success(value): asset = value
        case let .failure(error): throw IosReaderFailure(code: .engineError, underlyingError: error as NSError)
        }
        let safetyFailureSink = IosReaderSafetyFailureSink()
        let resourceRoles = IosEpubResourceRoleResolver()
        let protectedAsset: ReadiumShared.Asset
        do {
            protectedAsset = try protectEpubAsset(
                asset,
                failureSink: safetyFailureSink,
                archiveSafety: archiveSafety,
                resourceRoles: resourceRoles
            )
            try safetyFailureSink.throwIfPresent()
        } catch let error as IosPublicationSecurityError {
            throw IosReaderFailure.security(error)
        } catch {
            throw IosReaderFailure(code: .engineError, underlyingError: error as NSError)
        }
        let publication: Publication
        switch await publicationOpener.open(
            asset: protectedAsset,
            allowUserInteraction: false
        ) {
        case let .success(value):
            publication = value
            // The publication manifest is the first authoritative reading-order
            // description.  Mark it before the first resource read so a damaged
            // chapter is required while NCX/nav/cover remain isolatable.
            resourceRoles.markReadingOrder(paths: publication.readingOrder.map(\.href))
            do {
                try safetyFailureSink.throwIfPresent()
            } catch let safetyError as IosPublicationSecurityError {
                publication.close()
                safetyFailureSink.clear()
                throw IosReaderFailure.security(safetyError)
            }
        case let .failure(error):
            do {
                try safetyFailureSink.throwIfPresent()
            } catch let safetyError as IosPublicationSecurityError {
                safetyFailureSink.clear()
                throw IosReaderFailure.security(safetyError)
            }
            if archiveSafety.quarantinedResources.keys.contains(where: { resourceRoles.wasRequiredObserved(path: $0) }) {
                safetyFailureSink.clear()
                let failure = ErmaoShared.PublicKt.readerSafetyEpubArchiveIntegrityFailure()
                throw IosReaderFailure.security(
                    .rejected(ruleId: failure.ruleId, errorCode: failure.errorCode)
                )
            }
            safetyFailureSink.clear()
            throw IosReaderFailure(code: .parseFailed, underlyingError: error as NSError)
        }
        guard publication.conforms(to: .epub) else {
            publication.close()
            throw IosReaderFailure(code: .unsupportedFormat)
        }
        guard !publication.isRestricted else {
            publication.close()
            throw IosReaderFailure.safety(ErmaoShared.PublicKt.readerSafetyDrmFailure())
        }
        let canonicalTableOfContents: [Link]
        do {
            guard case let .container(containerAsset) = protectedAsset else {
                throw IosReaderFailure(code: .engineError)
            }
            canonicalTableOfContents = try await IosEpubChapterProjection.project(asset: containerAsset)
            try safetyFailureSink.throwIfPresent()
        } catch {
            defer {
                publication.close()
                safetyFailureSink.clear()
            }
            do {
                try safetyFailureSink.throwIfPresent()
            } catch let safetyError as IosPublicationSecurityError {
                throw IosReaderFailure.security(safetyError)
            }
            throw error
        }
        return IosOpenedReadiumPublication(
            publication: publication,
            canonicalTableOfContents: canonicalTableOfContents,
            close: {
                publication.close()
                safetyFailureSink.clear()
            },
            checkSafetyFailure: {
                try safetyFailureSink.throwIfPresent()
            }
        )
    }

    private func openMobiFamily(
        _ managed: IosManagedPublication
    ) async throws -> IosOpenedReadiumPublication {
        do {
            let result = try await IosMobiPublicationFactory().open(
                fileURL: managed.fileURL,
                resourceID: managed.resourceID,
                displayTitle: managed.displayTitle
            )
            return IosOpenedReadiumPublication(
                publication: result.publication,
                canonicalTableOfContents: result.publication.manifest.tableOfContents
            ) {
                await result.close()
            }
        } catch let error as IosMobiCoreError {
            if error.status == .drmProtected {
                throw IosReaderFailure.safety(
                    ErmaoShared.PublicKt.readerSafetyDrmFailure(),
                    underlyingError: error as NSError
                )
            }
            throw IosReaderFailure(code: Self.failureCode(error.status), underlyingError: error as NSError)
        } catch let error as IosPublicationSecurityError {
            throw IosReaderFailure.security(error)
        } catch let error as IosMobiPublicationError {
            switch error {
            case .closed, .invalidResourceIndex, .invalidResourcePath,
                 .duplicateResourcePath, .invalidTableOfContents, .invalidTextEncoding:
                throw IosReaderFailure(code: .parseFailed, underlyingError: error as NSError)
            case .invalidSourceIdentity:
                throw IosReaderFailure(code: .parseFailed, underlyingError: error as NSError)
            case .missingReadingOrder:
                throw IosReaderFailure(code: .unsupportedFormat)
            }
        }
    }

    private static func failureCode(_ status: IosMobiCoreStatus) -> IosReaderFailureCode {
        switch status {
        case .drmProtected:
            .engineError
        case .unsupported:
            .unsupportedFormat
        case .limitExceeded, .outOfMemory:
            .outOfMemoryRisk
        case .fileNotFound, .notFound:
            .resourceMissing
        case .io:
            .engineError
        case .corrupt, .parseFailed, .noContent:
            .parseFailed
        case .invalidArgument, .outOfRange,
             .bufferTooSmall, .internalFailure:
            .engineError
        }
    }

}

// Readium resolves container resources on background executors. Keeping this transform outside
// the @MainActor runtime prevents its resource mapper from inheriting main-actor isolation.
private func protectEpubAsset(
    _ asset: ReadiumShared.Asset,
    failureSink: IosReaderSafetyFailureSink,
    archiveSafety: IosEpubArchiveSafetyPreflight.IosEpubArchiveSafetyResult,
    resourceRoles: IosEpubResourceRoleResolver
) throws -> ReadiumShared.Asset {
    guard case let .container(containerAsset) = asset else {
        let failure = ErmaoShared.PublicKt.readerSafetyPlatformAlgorithmUnsupported(
            ruleId: ErmaoShared.PublicKt.readerSafetyPrepareXmlRuleId()
        )
        throw IosPublicationSecurityError.rejected(
            ruleId: failure.ruleId,
            errorCode: failure.errorCode
        )
    }
    let protectedContainer = containerAsset.container.map { href, resource in
        resourceRoles.observeParserAccess(path: href.path)
        let checkedResource = TransformingResource(resource) { result in
            return result.flatMap { data in
                do {
                    if let failure = archiveSafety.quarantineFor(path: href.path) {
                        let selected = archiveIntegrityFailure(
                            failure,
                            role: resourceRoles.role(for: href.path)
                        )
                        throw IosPublicationSecurityError.rejected(
                            ruleId: selected.ruleId,
                            errorCode: selected.errorCode
                        )
                    }
                    if let expected = archiveSafety.expectedFor(path: href.path) {
                        do {
                            try IosEpubArchiveSafetyPreflight.verifyResourceBytes(expected: expected, data: data)
                        } catch let error as IosPublicationSecurityError {
                            if case let .rejected(ruleId, errorCode) = error,
                               ruleId == ErmaoShared.PublicKt.readerSafetyOptionalResourceFailure().ruleId,
                               errorCode == ErmaoShared.PublicKt.readerSafetyOptionalResourceFailure().errorCode {
                                let required = archiveIntegrityFailure(
                                    ErmaoShared.PublicKt.readerSafetyEpubArchiveIntegrityFailure(),
                                    role: resourceRoles.role(for: href.path)
                                )
                                throw IosPublicationSecurityError.rejected(
                                    ruleId: required.ruleId,
                                    errorCode: required.errorCode
                                )
                            }
                            throw error
                        }
                    }
                    return .success(data)
                } catch is CancellationError {
                    return .failure(.cancelled)
                } catch {
                    failureSink.record(error, resourceRole: resourceRoles.role(for: href.path))
                    return .failure(.decoding("Unreadable EPUB resource", cause: error))
                }
            }
        }
        return TransformingResource(checkedResource) { result in
            let mediaType = try? await resource.properties().get().mediaType?.string
            return result.flatMap { data in
                do {
                    let prepared = try IosPublicationSecurityPolicy.prepareResource(
                        data: data,
                        mediaType: mediaType
                    )
                    if IosEpubArchiveSafetyPreflight.canonicalArchivePath(href.path) ==
                        "META-INF/container.xml"
                    {
                        for path in try IosEpubArchiveSafetyPreflight.rootfilePaths(from: prepared) {
                            resourceRoles.markControlDocument(path: path)
                        }
                    }
                    return .success(prepared)
                } catch is CancellationError {
                    return .failure(.cancelled)
                } catch {
                    failureSink.record(error, resourceRole: resourceRoles.role(for: href.path))
                    return .failure(.decoding("Unsafe or invalid EPUB resource", cause: error))
                }
            }
        }
    }
    return .container(ReadiumShared.ContainerAsset(container: protectedContainer, format: containerAsset.format))
}

private func archiveIntegrityFailure(
    _ failure: ErmaoShared.ReaderSafetyFailure,
    role: IosEpubResourceRole
) -> ErmaoShared.ReaderSafetyFailure {
    guard failure.ruleId == ErmaoShared.PublicKt.readerSafetyEpubArchiveIntegrityFailure().ruleId else {
        return failure
    }
    let decision = ErmaoShared.PublicKt.readerSafetyEvaluateRuleDecision(
        format: "EPUB",
        resourceRole: role.rawValue,
        ruleId: ErmaoShared.PublicKt.readerSafetyEpubArchiveIntegrityFailure().ruleId,
        enforcementAvailable: true,
        canIsolate: role == .optionalResource
    )
    return decision.action == "BLOCK_RESOURCE"
        ? ErmaoShared.PublicKt.readerSafetyOptionalResourceFailure()
        : ErmaoShared.PublicKt.readerSafetyEpubArchiveIntegrityFailure()
}
