import Foundation
import SwiftUI
import CryptoKit
import OSLog
@preconcurrency import ErmaoShared

struct IosReaderLaunchRequest: Identifiable, Equatable, Sendable {
    let context: ContentRequestContext
    let bookID: String
    let resourceID: String
    let displayTitle: String
    let managedDownloadRecordID: String?
    let initialTargetPayload: String?

    init(
        context: ContentRequestContext,
        bookID: String,
        resourceID: String,
        displayTitle: String,
        managedDownloadRecordID: String? = nil,
        initialTargetPayload: String? = nil
    ) {
        self.context = context
        self.bookID = bookID
        self.resourceID = resourceID
        self.displayTitle = displayTitle
        self.managedDownloadRecordID = managedDownloadRecordID
        self.initialTargetPayload = initialTargetPayload
    }

    var id: String { "\(context.namespaceKey)|\(resourceID)" }
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

@MainActor
final class IosReaderComposition: ObservableObject {
    private static let logger = Logger(subsystem: "com.ermao.library", category: "MobileReader")
    private let cookieStore: KeychainCookiePayloadStore
    private let managedStore: IosManagedPublicationStore
    private let deviceIdentity: IosReaderDeviceIdentity
    private let completedDownloads: any CompletedDownloadProviding
    private let navigationCache = IosReaderNavigationCache()

    init(
        cookieStore: KeychainCookiePayloadStore,
        completedDownloads: any CompletedDownloadProviding
    ) throws {
        self.cookieStore = cookieStore
        self.completedDownloads = completedDownloads
        managedStore = try IosManagedPublicationStore()
        deviceIdentity = IosReaderDeviceIdentity()
    }

    func makeHost(request: IosReaderLaunchRequest) -> IosReaderBootstrapHost {
        IosReaderBootstrapHost(request: request, composition: self)
    }

    fileprivate func bootstrap(
        _ request: IosReaderLaunchRequest
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
        var launchArtifact: CompletedDownloadFile?
        if let recordID = request.managedDownloadRecordID {
            guard let artifact = try await completedDownloads.completedFile(
                recordID: recordID,
                namespace: request.context.namespaceKey
            ), artifact.resourceID == request.resourceID else {
                throw IosReaderFailure(code: .resourceMissing)
            }
            launchArtifact = artifact
            Self.logger.notice(
                "reader_start platform=ios format=\(artifact.sourceFormat, privacy: .public) entry=download_center stage=artifact_verified code=READER_LOCAL_ARTIFACT_VERIFIED"
            )
        } else {
            launchArtifact = nil
        }
        let opensVerifiedLocalArtifact = launchArtifact != nil
        var launchArtifactFailure: IosReaderFailure?
        let bootstrapRequest = ErmaoShared.ReaderBootstrapRequest(
            profile: profile,
            namespace: namespace,
            resourceId: request.resourceID
        )
        let result: ErmaoShared.ReaderBootstrapResult?
        let bootstrapFailure: IosReaderFailure?
        if opensVerifiedLocalArtifact {
            // Download Center is a pure-local entry point. A verified original must
            // never wait for bootstrap or progress network timeouts before opening.
            result = nil
            bootstrapFailure = nil
            Self.logger.notice(
                "reader_start platform=ios format=local entry=download_center stage=bootstrap_skipped code=READER_LOCAL_ONLY"
            )
        } else {
            do {
                result = try await gateway.load(request: bootstrapRequest)
                if let failure = result as? ErmaoShared.ReaderBootstrapResultFailure {
                    bootstrapFailure = IosReaderFailure(
                        code: IosReaderFailureCode(sharedCode: failure.readerErrorCode)
                    )
                } else {
                    bootstrapFailure = nil
                }
            } catch {
                result = nil
                bootstrapFailure = IosReaderFailure(code: .networkUnavailable)
            }
        }
        let onlineBootstrap = (result as? ErmaoShared.ReaderBootstrapResultContent)?.value
        if let launchArtifact {
            let artifactFormat = Self.completedFileSourceFormat(
                launchArtifact.sourceFormat
            )
            if let artifactFormat, Self.hasCompleteReaderEngine(for: artifactFormat) {
                do {
                    let values = try launchArtifact.fileURL.resourceValues(forKeys: [.fileSizeKey])
                    await managedStore.bindCompleted(IosManagedPublication(
                        resourceID: launchArtifact.resourceID, displayTitle: launchArtifact.displayTitle,
                        fileURL: launchArtifact.fileURL, byteCount: Int64(values.fileSize ?? 0),
                        bookID: launchArtifact.bookID, assetID: launchArtifact.assetID,
                        namespace: request.context.namespaceKey, sourceFormat: artifactFormat
                    ))
                } catch let failure as IosReaderFailure {
                    launchArtifactFailure = failure
                } catch {
                    launchArtifactFailure = IosReaderFailure(code: .corruptFile)
                }
            } else {
                launchArtifactFailure = IosReaderFailure(code: .unsupportedFormat)
            }
        }
        if let onlineBootstrap {
            if let assetID = onlineBootstrap.remoteAccess.assetId {
                try await managedStore.removeAutomaticReplica(resourceID: request.resourceID, assetID: assetID,
                                                              namespace: request.context.namespaceKey)
            }
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
            target = onlineBootstrap.target
            exactSourceFormat = onlineBootstrap.remoteAccess.sourceFormat
            let resolved = ErmaoShared.BootstrapReaderPublication(bootstrapGateway: gateway)
                .resolve(request: bootstrapRequest, bootstrap: onlineBootstrap)
            guard let content = resolved as? ErmaoShared.ReaderPublicationBootstrapResultContent else {
                throw IosReaderFailure(code: .unsupportedFormat)
            }
            source = content.source
        } else {
            guard opensVerifiedLocalArtifact else {
                throw bootstrapFailure ?? IosReaderFailure(code: .networkUnavailable)
            }
            let existing: IosManagedPublication
            do {
                Self.logger.notice(
                    "reader_start platform=ios format=local entry=download_center stage=managed_resolve_started code=READER_LOCAL_RESOLVE"
                )
                existing = try await managedStore.resolve(
                    resourceID: request.resourceID,
                    namespace: request.context.namespaceKey
                )
            } catch {
                if let launchArtifactFailure { throw launchArtifactFailure }
                if let bootstrapFailure { throw bootstrapFailure }
                if let readerFailure = error as? IosReaderFailure { throw readerFailure }
                throw IosReaderFailure(code: .resourceMissing)
            }
            Self.logger.notice(
                "reader_start platform=ios format=\(existing.sourceFormat.wireValue, privacy: .public) entry=download_center stage=managed_resolve_completed code=READER_LOCAL_RESOLVE"
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
        var progressStore: any ErmaoShared.ReaderProgressSyncingStore
        let progressCoordination: IosReaderProgressSessionCoordination?
        var sessionRemoteSnapshot = remoteSnapshot
        do {
            let database = try IosReaderLocalDatabase(identity: localIdentity)
            if opensVerifiedLocalArtifact {
                Self.logger.notice(
                    "reader_start platform=ios format=\(exactSourceFormat.wireValue, privacy: .public) entry=download_center stage=progress_open_started code=READER_LOCAL_PROGRESS"
                )
                progressStore = IosLocalOnlyReaderProgressStore(database: database)
                progressCoordination = nil
                sessionRemoteSnapshot = nil
                Self.logger.notice(
                    "reader_start platform=ios format=\(exactSourceFormat.wireValue, privacy: .public) entry=download_center stage=progress_open_completed code=READER_LOCAL_PROGRESS"
                )
            } else {
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
                if startupDecision is ErmaoShared.PendingVsServerDecisionUseLocalPending {
                    sessionRemoteSnapshot = nil
                }
                try await progressRuntime.coordinator.applyStartupDecision(
                    target: target,
                    decision: startupDecision
                )
                progressCoordination = IosReaderProgressSessionCoordination(
                    runtime: progressRuntime,
                    database: database,
                    target: target,
                    server: serverPort,
                    clientID: localIdentity.clientId,
                    bootstrapSnapshot: remoteSnapshot
                )
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
        let bookmarkSyncPort = opensVerifiedLocalArtifact ? nil : IosCompositionKt.createIosReaderBookmarkSyncPort(
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
                initialTarget: ErmaoShared.PublicKt.decodeReaderLaunchTarget(payload: request.initialTargetPayload),
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
                    ? ErmaoShared.PdfRangeMemory()
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
                initialTarget: ErmaoShared.PublicKt.decodeReaderLaunchTarget(payload: request.initialTargetPayload),
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
            onlineSource: source as? ErmaoShared.RemoteReflowableReaderSource,
            onlinePublication: (source as? ErmaoShared.RemoteReflowableReaderSource).map {
                IosCompositionKt.createIosOnlinePublicationSession(cookieStore: cookieStore, profile: profile, source: $0)
            },
            preferences: preferencesStore.load(),
            managedStore: managedStore,
            progressStore: progressStore,
            progressCoordination: progressCoordination,
            preferencesStore: preferencesStore,
            bookmarkStore: bookmarkStore,
            bookmarkSyncPort: bookmarkSyncPort,
            bookmarkSyncTarget: opensVerifiedLocalArtifact ? nil : ErmaoShared.ReaderBookmarkSyncTarget(
                serverIdentity: request.context.serverIdentity,
                resourceId: source.resourceId
            ),
            remoteSnapshot: sessionRemoteSnapshot,
                initialTarget: ErmaoShared.PublicKt.decodeReaderLaunchTarget(payload: request.initialTargetPayload),
            namespaceKey: request.context.namespaceKey,
            bookID: request.bookID,
            publishProgressUpdate: { ReaderProgressPresentationCenter.shared.publish($0) },
            deviceIdentity: deviceIdentity
        ))
    }

    private static func sharedSource(_ existing: IosManagedPublication) -> ErmaoShared.ReaderSource {
        ErmaoShared.LocalReaderSource(
            resourceId: existing.resourceID,
            displayTitle: existing.displayTitle,
            format: existing.sourceFormat.readerFormat,
            bookId: existing.bookID,
            assetId: existing.assetID,
            sourceFormat: existing.sourceFormat
        )
    }

    private static func completedFileSourceFormat(
        _ storedFormat: String
    ) -> ErmaoShared.ReaderSourceFormat? {
        IosManagedPublicationStore.sourceFormat(storedFormat)
    }

    /// Keep download/validation capability separate from actual reader capability.
    private static func hasCompleteReaderEngine(for sourceFormat: ErmaoShared.ReaderSourceFormat) -> Bool {
        switch sourceFormat {
        case .epub, .mobi, .azw, .azw3, .prc, .txt, .fb2, .cbz, .zip, .cbr, .rar, .imagedir, .pdf:
            true
        default:
            false
        }
    }

    private static func localParserVersion(for format: ErmaoShared.ReaderSourceFormat) -> String {
        switch format {
        case .epub: "epub-package:1"
        case .txt: "shuku-txt-parser-v1"
        case .fb2: "shuku-fb2-parser-v1"
        case .cbz, .zip, .cbr, .rar: "libarchive-3.8.9:zip-rar-rar5-read-only"
        case .imagedir: "original-page-set-v1"
        case .pdf: "pdf:source-v1"
        default: IosMobiBook.parserIdentifier
        }
    }

    private static func localNormalizationVersion(for format: ErmaoShared.ReaderSourceFormat) -> String {
        switch format {
        case .epub: "shuku-epub-locator-dom-v2"
        case .txt: "shuku-txt-publication-v2"
        case .fb2: "shuku-fb2-publication-v1"
        case .cbz, .zip, .cbr, .rar: "shuku-comic-pages-v1"
        case .imagedir: "shuku-image-dir-pages-v1"
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
        if publication.sourceFormat == .imagedir {
            let localPages = try IosImageDirectoryBundle(
                directory: publication.fileURL,
                expectedResourceID: resourceID
            ).pages
            return localPages.enumerated().map { index, page in
                IosCbzPage(
                    pageIndex: page.pageIndex,
                    resourceHref: page.resourceHref,
                    mediaType: page.mediaType,
                    width: page.width,
                    height: page.height,
                    title: serverHints.indices.contains(index) ? serverHints[index].title : page.title
                )
            }
        }
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
    private static let logger = Logger(subsystem: "com.ermao.library", category: "MobileReader")

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
            record(failure.code, stage: "bootstrap")
            state = .failure(failure.code)
        } catch {
            record(.networkUnavailable, stage: "bootstrap")
            state = .failure(.networkUnavailable)
        }
    }

    var hasDownloadedArtifact: Bool { request.managedDownloadRecordID != nil }

    func retry() async {
        started = false
        state = .loading
        do {
            state = .ready(try await composition.bootstrap(
                request
            ))
            started = true
        } catch let failure as IosReaderFailure {
            record(failure.code, stage: "retry")
            state = .failure(failure.code)
        } catch {
            record(.networkUnavailable, stage: "retry")
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
                displayTitle: request.displayTitle,
                initialTargetPayload: request.initialTargetPayload
            )))
            started = true
        } catch let failure as IosReaderFailure {
            record(failure.code, stage: "read_online")
            state = .failure(failure.code)
        } catch {
            record(.networkUnavailable, stage: "read_online")
            state = .failure(.networkUnavailable)
        }
    }

    private func record(_ code: IosReaderFailureCode, stage: String) {
        let entry = request.managedDownloadRecordID == nil ? "work_detail" : "download_center"
        Self.logger.error(
            "reader_error platform=ios format=unknown entry=\(entry, privacy: .public) stage=\(stage, privacy: .public) code=\(code.rawValue, privacy: .public)"
        )
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
                ProgressView("reader.loading.publication")
                    .accessibilityIdentifier("reader.bootstrap.loading")
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
                    }
                    Button("common.close") { dismiss() }
                }
                .padding(24)
                .accessibilityIdentifier("reader.bootstrap.failure.\(code.rawValue)")
            }
        }
        .task { await host.start() }
    }
}
