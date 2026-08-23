import Foundation
import SwiftUI
import CryptoKit
@preconcurrency import ErmaoShared

struct IosReaderLaunchRequest: Identifiable, Equatable, Sendable {
    let context: ContentRequestContext
    let bookID: String
    let resourceID: String
    let displayTitle: String
    let managedDownloadRecordID: String?

    init(
        context: ContentRequestContext,
        bookID: String,
        resourceID: String,
        displayTitle: String,
        managedDownloadRecordID: String? = nil
    ) {
        self.context = context
        self.bookID = bookID
        self.resourceID = resourceID
        self.displayTitle = displayTitle
        self.managedDownloadRecordID = managedDownloadRecordID
    }

    var id: String { "\(context.namespaceKey)|\(resourceID)" }
}

struct IosReaderDownloadArtifact: Sendable {
    let fileURL: URL
    let assetID: String
    let displayTitle: String
    let bookID: String
    let resourceID: String
    let sourceFormat: String
}

protocol IosReaderDownloadArtifactProviding: Sendable {
    func verifiedReaderArtifact(recordID: String, namespace: String) async throws -> IosReaderDownloadArtifact?
    func deleteReaderArtifact(recordID: String, namespace: String) async throws
}

struct IosReaderNavigationSnapshot: Codable {
    struct Unit: Codable {
        let id: String
        let title: String
        let href: String?
    }

    struct ComicPage: Codable {
        let href: String
        let mediaType: String
        let width: Int?
        let height: Int?
        let title: String?
    }

    let units: [Unit]
    let comicPages: [ComicPage]
    let pdfPageTitles: [String]
    let pageCount: Int?
}

final class IosReaderNavigationCache {
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func save(
        serverIdentity: String,
        userID: String,
        resourceID: String,
        bootstrap: ErmaoShared.ReaderBootstrap
    ) {
        let previous = load(serverIdentity: serverIdentity, userID: userID, resourceID: resourceID)
        let units = bootstrap.units.isEmpty ? previous?.units ?? [] : bootstrap.units.prefix(20_000).map {
            IosReaderNavigationSnapshot.Unit(id: $0.id, title: $0.title, href: $0.href)
        }
        let comicPages = bootstrap.comicPages.isEmpty
            ? previous?.comicPages ?? []
            : bootstrap.comicPages.prefix(20_000).map {
                IosReaderNavigationSnapshot.ComicPage(
                    href: $0.resourceHref,
                    mediaType: $0.mediaType,
                    width: $0.width.map { Int($0.intValue) },
                    height: $0.height.map { Int($0.intValue) },
                    title: $0.title
                )
            }
        let pdfPageTitles = bootstrap.pdfPages.isEmpty
            ? previous?.pdfPageTitles ?? []
            : bootstrap.pdfPages.prefix(20_000).map(\.title)
        let snapshot = IosReaderNavigationSnapshot(
            units: units,
            comicPages: comicPages,
            pdfPageTitles: pdfPageTitles,
            pageCount: bootstrap.pageCount?.intValue ?? previous?.pageCount
        )
        guard let data = try? JSONEncoder().encode(snapshot) else { return }
        defaults.set(data, forKey: key(serverIdentity: serverIdentity, userID: userID, resourceID: resourceID))
    }

    func load(serverIdentity: String, userID: String, resourceID: String) -> IosReaderNavigationSnapshot? {
        guard let data = defaults.data(
            forKey: key(serverIdentity: serverIdentity, userID: userID, resourceID: resourceID)
        ) else { return nil }
        return try? JSONDecoder().decode(IosReaderNavigationSnapshot.self, from: data)
    }

    /// Navigation snapshots are private Reader state. Use the account prefix
    /// so clearing one namespace cannot remove another account's snapshots.
    func clear(serverIdentity: String, userID: String) {
        let prefix = "reader.navigation.v2.\(accountDigest(serverIdentity: serverIdentity, userID: userID))."
        for key in defaults.dictionaryRepresentation().keys where key.hasPrefix(prefix) {
            defaults.removeObject(forKey: key)
        }
    }

    private func key(serverIdentity: String, userID: String, resourceID: String) -> String {
        return "reader.navigation.v2.\(accountDigest(serverIdentity: serverIdentity, userID: userID)).\(resourceDigest(resourceID))"
    }

    private func accountDigest(serverIdentity: String, userID: String) -> String {
        SHA256.hash(data: Data("\(serverIdentity)\0\(userID)".utf8))
            .map { String(format: "%02x", $0) }.joined()
    }

    private func resourceDigest(_ resourceID: String) -> String {
        SHA256.hash(data: Data(resourceID.utf8))
            .map { String(format: "%02x", $0) }.joined()
    }
}

extension ManagedDownloadStore: IosReaderDownloadArtifactProviding {
    func deleteReaderArtifact(recordID: String, namespace: String) async throws {
        guard let record = try records(namespace: namespace).first(where: { $0.id == recordID }) else { return }
        try remove(record)
    }
}

@MainActor
final class IosReaderComposition: ObservableObject {
    private let cookieStore: KeychainCookiePayloadStore
    private let managedStore: IosManagedPublicationStore
    private let deviceIdentity: IosReaderDeviceIdentity
    private let downloadArtifacts: any IosReaderDownloadArtifactProviding
    private let navigationCache = IosReaderNavigationCache()

    init(
        cookieStore: KeychainCookiePayloadStore,
        downloadArtifacts: any IosReaderDownloadArtifactProviding
    ) throws {
        self.cookieStore = cookieStore
        self.downloadArtifacts = downloadArtifacts
        managedStore = try IosManagedPublicationStore()
        deviceIdentity = IosReaderDeviceIdentity()
    }

    func makeHost(request: IosReaderLaunchRequest) -> IosReaderBootstrapHost {
        IosReaderBootstrapHost(request: request, composition: self)
    }

    fileprivate func bootstrap(
        _ request: IosReaderLaunchRequest,
        reacquireDownloadedPublication: Bool = false,
        retryOpening: Bool = false
    ) async throws -> IosReaderSession {
        let namespace = ErmaoShared.PublicKt.createReaderSyncNamespace(
            serverIdentity: request.context.serverIdentity,
            userId: request.context.userID,
            authorizationVersion: request.context.authorizationVersion
        )
        let profile = ErmaoShared.PublicKt.createReaderServerProfile(
            id: request.context.profileID,
            displayName: request.context.profileDisplayName,
            baseUrl: request.context.baseURL,
            serverIdentity: request.context.serverIdentity,
            isActive: true,
            acceptsInsecureTls: request.context.acceptsInsecureTLS
        )
        let gateway = IosCompositionKt.createIosReaderBootstrapGateway(cookieStore: cookieStore)
        let launchArtifact: IosReaderDownloadArtifact?
        if let recordID = request.managedDownloadRecordID, !reacquireDownloadedPublication {
            guard let artifact = try await downloadArtifacts.verifiedReaderArtifact(
                recordID: recordID,
                namespace: request.context.namespaceKey
            ), artifact.resourceID == request.resourceID else {
                throw IosReaderFailure(code: .resourceMissing)
            }
            launchArtifact = artifact
        } else {
            launchArtifact = nil
        }
        let bootstrapRequest = ErmaoShared.ReaderBootstrapRequest(
            profile: profile,
            namespace: namespace,
            resourceId: request.resourceID
        )
        let result: ErmaoShared.ReaderBootstrapResult?
        do {
            result = try await gateway.load(request: bootstrapRequest)
        } catch {
            result = nil
        }
        let onlineBootstrap = (result as? ErmaoShared.ReaderBootstrapResultContent)?.value
        if let onlineBootstrap {
            navigationCache.save(
                serverIdentity: request.context.serverIdentity,
                userID: request.context.userID,
                resourceID: request.resourceID,
                bootstrap: onlineBootstrap
            )
        }
        let cachedNavigation = navigationCache.load(
            serverIdentity: request.context.serverIdentity,
            userID: request.context.userID,
            resourceID: request.resourceID
        )
        let target: ErmaoShared.ReaderProgressSyncTarget
        let exactSourceFormat: ErmaoShared.ReaderSourceFormat
        let remoteSnapshot: ErmaoShared.ReaderProgressSnapshotV4?
        let source: ErmaoShared.ReaderSource
        if let onlineBootstrap {
            remoteSnapshot = onlineBootstrap.remoteSnapshot
            if let launchArtifact,
               !reacquireDownloadedPublication,
               let artifactFormat = IosManagedPublicationStore.sourceFormat(launchArtifact.sourceFormat),
               Self.hasCompleteReaderEngine(for: artifactFormat) {
                do {
                    _ = try await managedStore.importPublication(
                        from: launchArtifact.fileURL,
                        resourceID: launchArtifact.resourceID,
                        displayTitle: launchArtifact.displayTitle,
                        sourceFormat: artifactFormat,
                        bookID: launchArtifact.bookID,
                        namespace: request.context.namespaceKey,
                        parserVersion: Self.localParserVersion(for: artifactFormat),
                        normalizationVersion: Self.localNormalizationVersion(for: artifactFormat)
                    )
                } catch {
                    // A damaged download record must not hide an already usable managed
                    // publication or prevent a fresh server acquisition below.
                }
            }
            let existing: IosManagedPublication?
            if retryOpening {
                existing = nil
            } else {
                existing = try? await managedStore.resolve(
                    resourceID: request.resourceID,
                    namespace: request.context.namespaceKey
                )
            }
            if reacquireDownloadedPublication ||
                (retryOpening && onlineBootstrap.publication.originalSourceFormat.readerFormat != .comic) {
                exactSourceFormat = onlineBootstrap.publication.sourceFormat
                target = onlineBootstrap.target
                source = try await download(
                    bootstrap: onlineBootstrap,
                    gateway: gateway,
                    namespace: request.context.namespaceKey
                )
            } else if let existing {
                exactSourceFormat = existing.sourceFormat
                source = Self.sharedSource(existing)
                target = ErmaoShared.ReaderProgressSyncTarget(
                    namespace: namespace,
                    bookId: onlineBootstrap.target.bookId,
                    resourceId: onlineBootstrap.target.resourceId,
                    sourceFormat: exactSourceFormat.readerFormat
                )
            } else if onlineBootstrap.publication.sourceFormat == .pdf,
                      IosPdfiumFeatureFlags.nativePdfiumRangeV1 {
                exactSourceFormat = onlineBootstrap.publication.sourceFormat
                target = onlineBootstrap.target
                source = ErmaoShared.RemoteByteRangeReaderSource(
                    resourceId: onlineBootstrap.publication.resourceId,
                    displayTitle: onlineBootstrap.publication.displayTitle,
                    bookId: onlineBootstrap.publication.bookId,
                    assetId: onlineBootstrap.publication.assetId,
                    namespace: namespace,
                    apiPath: onlineBootstrap.publication.apiPath,
                    expectedSizeBytes: onlineBootstrap.publication.expectedSizeBytes
                )
            } else if onlineBootstrap.publication.sourceFormat.readerFormat == .comic,
                      let access = onlineBootstrap.comicAccess {
                exactSourceFormat = onlineBootstrap.publication.sourceFormat
                target = onlineBootstrap.target
                source = ErmaoShared.RemoteComicReaderSource(
                    resourceId: onlineBootstrap.publication.resourceId,
                    displayTitle: onlineBootstrap.publication.displayTitle,
                    bookId: onlineBootstrap.publication.bookId,
                    assetId: onlineBootstrap.publication.assetId,
                    namespace: namespace,
                    sourceFormat: onlineBootstrap.publication.originalSourceFormat,
                    manifestApiPath: access.manifestApiPath,
                    pageApiPathTemplate: access.pageApiPathTemplate,
                    pages: onlineBootstrap.comicPages.map {
                        ErmaoShared.RemoteComicPage(
                            pageIndex: $0.pageIndex,
                            resourceHref: $0.resourceHref,
                            mediaType: $0.mediaType,
                            width: $0.width,
                            height: $0.height
                        )
                    }
                )
            } else {
                exactSourceFormat = onlineBootstrap.publication.sourceFormat
                target = onlineBootstrap.target
                source = try await download(
                    bootstrap: onlineBootstrap,
                    gateway: gateway,
                    namespace: request.context.namespaceKey
                )
            }
            guard Self.hasCompleteReaderEngine(for: exactSourceFormat) else {
                throw IosReaderFailure(code: .unsupportedFormat)
            }
        } else {
            let existing = try await managedStore.resolve(
                resourceID: request.resourceID,
                namespace: request.context.namespaceKey
            )
            target = ErmaoShared.ReaderProgressSyncTarget(
                namespace: namespace,
                bookId: request.bookID,
                resourceId: request.resourceID,
                sourceFormat: existing.sourceFormat.readerFormat
            )
            exactSourceFormat = existing.sourceFormat
            guard Self.hasCompleteReaderEngine(for: exactSourceFormat) else {
                throw IosReaderFailure(code: .unsupportedFormat)
            }
            remoteSnapshot = nil
            source = Self.sharedSource(existing)
        }

        guard source.resourceId == target.resourceId,
              source.sourceFormat == exactSourceFormat,
              source.format == target.sourceFormat,
              exactSourceFormat.readerFormat == target.sourceFormat
        else {
            throw IosReaderFailure(code: .corruptFile)
        }
        let localIdentity = ErmaoShared.PublicKt.createReaderLocalProgressIdentity(
            namespace: namespace,
            clientId: deviceIdentity.stableDeviceId(),
            bookId: target.bookId,
            resourceId: target.resourceId
        )
        let progressStore: any ErmaoShared.ReaderProgressSyncingStore
        let progressCoordination: IosReaderProgressSessionCoordination?
        var sessionRemoteSnapshot = remoteSnapshot
        do {
            let database = try IosReaderLocalDatabase(identity: localIdentity)
            let serverPort = IosCompositionKt.createIosReaderProgressSyncPort(
                cookieStore: cookieStore,
                profile: profile
            )
            let progressRuntime = ErmaoShared.PublicKt.createReaderProgressSyncRuntime(
                stateStore: database,
                target: target,
                server: serverPort
            )
            progressStore = progressRuntime.store
            let localProgress = try await database.load(resourceId: source.resourceId)
            let durableState = try await database.loadSyncState()
            let startupDecision = ErmaoShared.PublicKt.decidePendingVsServerStartup(
                localProgress: localProgress,
                durableState: durableState,
                remoteSnapshot: remoteSnapshot,
                openedSource: source
            )
            var shouldRetryStartupPending = false
            if let useServer = startupDecision as? ErmaoShared.PendingVsServerDecisionUseServer,
               useServer.discardPending,
               let pending = durableState.pending {
                try await database.discardPendingAfterConflict(
                    mutationId: pending.mutationId,
                    serverRevision: useServer.snapshot?.revision ?? durableState.confirmedRevision
                )
            } else if startupDecision is ErmaoShared.PendingVsServerDecisionUseLocalPending {
                sessionRemoteSnapshot = nil
                shouldRetryStartupPending = true
            }
            progressCoordination = IosReaderProgressSessionCoordination(
                runtime: progressRuntime,
                database: database,
                target: target,
                server: serverPort,
                clientID: localIdentity.clientId,
                bootstrapSnapshot: remoteSnapshot
            )
            if shouldRetryStartupPending {
                try? await progressStore.retryPendingUpload()
            }
        } catch {
            progressStore = IosNonBlockingReaderProgressStore()
            progressCoordination = nil
        }
        let preferencesStore = IosReaderPreferencesStore(
            serverIdentity: request.context.serverIdentity,
            userID: request.context.userID
        )
        let bookmarkStore = IosReaderBookmarkStore(
            serverIdentity: request.context.serverIdentity,
            userID: request.context.userID,
            resourceID: source.resourceId
        )
        let bookmarkSyncPort = IosCompositionKt.createIosReaderBookmarkSyncPort(
            cookieStore: cookieStore,
            profile: profile
        )
        if exactSourceFormat.readerFormat == .comic {
            let serverPages: [IosCbzPage] = if let onlineBootstrap, !onlineBootstrap.comicPages.isEmpty {
                onlineBootstrap.comicPages.map {
                    IosCbzPage(
                        pageIndex: Int($0.pageIndex),
                        resourceHref: $0.resourceHref,
                        mediaType: $0.mediaType,
                        width: $0.width.map { Int($0.intValue) },
                        height: $0.height.map { Int($0.intValue) },
                        title: $0.title
                    )
                }
            } else {
                cachedNavigation?.comicPages.enumerated().map { index, page in
                    IosCbzPage(
                        pageIndex: index,
                        resourceHref: page.href,
                        mediaType: page.mediaType,
                        width: page.width,
                        height: page.height,
                        title: page.title
                    )
                } ?? []
            }
            let pages: [IosCbzPage]
            if source is ErmaoShared.RemoteComicReaderSource {
                guard !serverPages.isEmpty else {
                    throw IosReaderFailure(code: .resourceMissing)
                }
                pages = serverPages
            } else {
                pages = try await localComicPages(
                    resourceID: source.resourceId,
                    namespace: request.context.namespaceKey,
                    serverHints: serverPages
                )
            }
            return .comic(IosComicReaderSession(
                resourceID: source.resourceId,
                displayTitle: source.displayTitle,
                pages: pages,
                preferences: preferencesStore.load(),
                preferencesStore: preferencesStore,
                managedStore: managedStore,
                progressStore: progressStore,
                progressCoordination: progressCoordination,
                remoteSnapshot: sessionRemoteSnapshot,
                namespaceKey: request.context.namespaceKey,
                bookID: request.bookID,
                publishProgressUpdate: { ReaderProgressPresentationCenter.shared.publish($0) },
                deviceIdentity: deviceIdentity,
                remoteSource: source as? ErmaoShared.RemoteComicReaderSource,
                comicPageServer: source is ErmaoShared.RemoteComicReaderSource
                    ? IosCompositionKt.createIosComicPageServerPort(
                        cookieStore: cookieStore,
                        profile: profile
                    )
                    : nil
            ))
        }
        if exactSourceFormat == .pdf {
            let pageTitleHints = if let onlineBootstrap, !onlineBootstrap.pdfPages.isEmpty {
                onlineBootstrap.pdfPages.map(\.title)
            } else {
                cachedNavigation?.pdfPageTitles ?? []
            }
            return .pdf(IosPdfReaderSession(
                resourceID: source.resourceId,
                displayTitle: source.displayTitle,
                pageCountHint: onlineBootstrap?.pageCount?.intValue ?? cachedNavigation?.pageCount,
                pageTitleHints: pageTitleHints,
                preferences: preferencesStore.load(),
                preferencesStore: preferencesStore,
                remoteSource: source as? ErmaoShared.RemoteByteRangeReaderSource,
                rangeCache: source is ErmaoShared.RemoteByteRangeReaderSource
                    ? try IosPdfRangeCache()
                    : nil,
                rangeServer: source is ErmaoShared.RemoteByteRangeReaderSource
                    ? IosCompositionKt.createIosPdfRangeServerPort(
                        cookieStore: cookieStore,
                        profile: profile
                    )
                    : nil,
                managedStore: managedStore,
                progressStore: progressStore,
                progressCoordination: progressCoordination,
                remoteSnapshot: sessionRemoteSnapshot,
                namespaceKey: request.context.namespaceKey,
                bookID: request.bookID,
                publishProgressUpdate: { ReaderProgressPresentationCenter.shared.publish($0) },
                deviceIdentity: deviceIdentity
            ))
        }
        let navigationUnits: [IosReaderTocEntry] = if let onlineBootstrap, !onlineBootstrap.units.isEmpty {
            onlineBootstrap.units.map {
                IosReaderTocEntry(id: $0.id, title: $0.title, href: $0.href, depth: 0)
            }
        } else {
            cachedNavigation?.units.map {
                IosReaderTocEntry(id: $0.id, title: $0.title, href: $0.href, depth: 0)
            } ?? []
        }
        return .reflowable(IosReflowableReaderSession(
            resourceID: source.resourceId,
            displayTitle: source.displayTitle,
            sourceFormat: exactSourceFormat,
            canonicalNavigation: navigationUnits,
            preferences: preferencesStore.load(),
            managedStore: managedStore,
            progressStore: progressStore,
            progressCoordination: progressCoordination,
            preferencesStore: preferencesStore,
            bookmarkStore: bookmarkStore,
            bookmarkSyncPort: bookmarkSyncPort,
            bookmarkSyncTarget: ErmaoShared.ReaderBookmarkSyncTarget(
                serverIdentity: request.context.serverIdentity,
                resourceId: source.resourceId
            ),
            remoteSnapshot: sessionRemoteSnapshot,
            namespaceKey: request.context.namespaceKey,
            bookID: request.bookID,
            publishProgressUpdate: { ReaderProgressPresentationCenter.shared.publish($0) },
            deviceIdentity: deviceIdentity
        ))
    }

    fileprivate func deleteDownloadedArtifact(for request: IosReaderLaunchRequest) async throws {
        guard let recordID = request.managedDownloadRecordID else { return }
        try await downloadArtifacts.deleteReaderArtifact(
            recordID: recordID,
            namespace: request.context.namespaceKey
        )
        try? await managedStore.remove(
            resourceID: request.resourceID,
            namespace: request.context.namespaceKey
        )
    }

    private static func sharedSource(_ existing: IosManagedPublication) -> ErmaoShared.ReaderSource {
        ErmaoShared.LocalReaderSource(
            resourceId: existing.resourceID,
            displayTitle: existing.displayTitle,
            format: existing.sourceFormat.readerFormat,
            bookId: existing.bookID,
            sourceFormat: existing.sourceFormat
        )
    }

    /// Keep download/validation capability separate from actual reader capability.
    private static func hasCompleteReaderEngine(for sourceFormat: ErmaoShared.ReaderSourceFormat) -> Bool {
        switch sourceFormat {
        case .epub, .mobi, .azw, .azw3, .prc, .txt, .cbz, .zip, .cbr, .rar, .pdf:
            true
        default:
            false
        }
    }

    private static func localParserVersion(for format: ErmaoShared.ReaderSourceFormat) -> String {
        switch format {
        case .epub: "epub-package:1"
        case .txt: "shuku-txt-parser-v1"
        case .cbz, .zip: "archive-images:natural-order-v1"
        case .pdf: "pdf:source-v1"
        default: IosMobiBook.parserIdentifier
        }
    }

    private static func localNormalizationVersion(for format: ErmaoShared.ReaderSourceFormat) -> String {
        switch format {
        case .epub: "shuku-epub-locator-dom-v2"
        case .txt: "shuku-txt-publication-v2"
        case .cbz, .zip: "shuku-comic-pages-v1"
        case .pdf: "shuku-pdf-pages-v1"
        default: IosMobiPublicationIdentity.normalizationIdentifier
        }
    }

    private func localComicPages(
        resourceID: String,
        namespace: String,
        serverHints: [IosCbzPage]
    ) async throws -> [IosCbzPage] {
        let publication = try await managedStore.resolve(
            resourceID: resourceID,
            namespace: namespace
        )
        do {
            let localPages = try IosCbzArchiveIndex(fileURL: publication.fileURL).pages
            return localPages.enumerated().map { index, page in
                IosCbzPage(
                    pageIndex: page.pageIndex,
                    resourceHref: page.resourceHref,
                    mediaType: page.mediaType,
                    width: page.width,
                    height: page.height,
                    title: serverHints.indices.contains(index) ? serverHints[index].title : nil
                )
            }
        } catch IosCbzError.limitExceeded {
            throw IosReaderFailure(code: .comicOutOfMemoryRisk)
        } catch IosCbzError.encrypted {
            throw IosReaderFailure(code: .comicArchiveEncrypted)
        } catch {
            throw IosReaderFailure(code: .comicArchiveCorrupt)
        }
    }

    private func download(
        bootstrap: ErmaoShared.ReaderBootstrap,
        gateway: ErmaoShared.ReaderServerGateway,
        namespace: String
    ) async throws -> ErmaoShared.ReaderSource {
        let result = try await gateway.download(
            download: bootstrap.publication,
            sinkFactory: IosPublicationDownloadSinkFactory(
                store: managedStore,
                namespace: namespace
            )
        )
        guard let content = result as? ErmaoShared.PublicationDownloadResultContent else {
            let failure = result as? ErmaoShared.PublicationDownloadResultFailure
            throw IosReaderFailure(code: failure?.recoverable == true ? .networkUnavailable : .resourceMissing)
        }
        return content.source
    }
}

@MainActor
enum IosReaderSession {
    case reflowable(IosReflowableReaderSession)
    case comic(IosComicReaderSession)
    case pdf(IosPdfReaderSession)
}

@MainActor
final class IosReaderBootstrapHost: ObservableObject {
    enum State {
        case loading
        case ready(IosReaderSession)
        case failure(IosReaderFailureCode)
    }

    @Published private(set) var state: State = .loading
    private let request: IosReaderLaunchRequest
    private unowned let composition: IosReaderComposition
    private var started = false

    init(request: IosReaderLaunchRequest, composition: IosReaderComposition) {
        self.request = request
        self.composition = composition
    }

    func start() async {
        guard !started else { return }
        started = true
        do {
            state = .ready(try await composition.bootstrap(request))
        } catch let failure as IosReaderFailure {
            state = .failure(failure.code)
        } catch {
            state = .failure(.networkUnavailable)
        }
    }

    var hasDownloadedArtifact: Bool { request.managedDownloadRecordID != nil }

    func retry() async {
        started = false
        state = .loading
        do {
            state = .ready(try await composition.bootstrap(
                request,
                reacquireDownloadedPublication: request.managedDownloadRecordID != nil,
                retryOpening: true
            ))
            started = true
        } catch let failure as IosReaderFailure {
            state = .failure(failure.code)
        } catch {
            state = .failure(.networkUnavailable)
        }
    }

    func readOnline() async {
        guard request.managedDownloadRecordID != nil else { return }
        started = false
        state = .loading
        do {
            state = .ready(try await composition.bootstrap(IosReaderLaunchRequest(
                context: request.context,
                bookID: request.bookID,
                resourceID: request.resourceID,
                displayTitle: request.displayTitle
            )))
            started = true
        } catch let failure as IosReaderFailure {
            state = .failure(failure.code)
        } catch {
            state = .failure(.networkUnavailable)
        }
    }

    func deleteDownload() async throws {
        try await composition.deleteDownloadedArtifact(for: request)
    }
}

struct IosReaderBootstrapView: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var host: IosReaderBootstrapHost

    init(request: IosReaderLaunchRequest, composition: IosReaderComposition) {
        _host = StateObject(wrappedValue: composition.makeHost(request: request))
    }

    var body: some View {
        Group {
            switch host.state {
            case .loading:
                ProgressView("reader.download.preparing")
            case .ready(let session):
                switch session {
                case .reflowable(let value):
                    IosReflowableReaderView(session: value, onRetry: { Task { await host.retry() } })
                case .comic(let value):
                    IosComicReaderView(session: value, onRetry: { Task { await host.retry() } })
                case .pdf(let value):
                    IosPdfReaderView(session: value, onRetry: { Task { await host.retry() } })
                }
            case .failure(let code):
                VStack(spacing: 16) {
                    Image(systemName: "exclamationmark.triangle").font(.largeTitle)
                    Text("reader.error.title").font(.headline)
                    Text(code.localizedDescription).multilineTextAlignment(.center)
                    Button("common.retry") { Task { await host.retry() } }
                    if host.hasDownloadedArtifact {
                        Button("reader.read.online") { Task { await host.readOnline() } }
                        Button("reader.download.delete", role: .destructive) {
                            Task {
                                try? await host.deleteDownload()
                                dismiss()
                            }
                        }
                    }
                    Button("common.close") { dismiss() }
                }
                .padding(24)
            }
        }
        .task { await host.start() }
    }
}
