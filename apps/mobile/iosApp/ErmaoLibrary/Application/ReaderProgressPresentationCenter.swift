import Combine
import Foundation
@preconcurrency import ErmaoShared

@MainActor
final class ReaderProgressPresentationCenter {
    static let shared = ReaderProgressPresentationCenter()

    private let subject = PassthroughSubject<ErmaoShared.ReaderProgressPresentationUpdate, Never>()

    var updates: AnyPublisher<ErmaoShared.ReaderProgressPresentationUpdate, Never> {
        subject.eraseToAnyPublisher()
    }

    func publish(_ update: ErmaoShared.ReaderProgressPresentationUpdate) {
        subject.send(update)
    }

    func publish(
        namespaceKey: String,
        bookID: String,
        resourceID: String,
        position: ErmaoShared.ReaderPositionReport,
        capturedAtEpochMillis: Int64
    ) {
        publish(ErmaoShared.PublicKt.createReaderProgressPresentationUpdate(
            namespaceKey: namespaceKey,
            bookId: bookID,
            resourceId: resourceID,
            position: position,
            capturedAtEpochMillis: capturedAtEpochMillis
        ))
    }

    /// Returns fresh-install Reader v5 presentation overlays without reading
    /// or interpreting Locator JSON. Missing/corrupt local records are isolated
    /// per resource so they cannot prevent the server-backed detail view from
    /// loading.
    func loadLocalUpdates(
        context: ContentRequestContext,
        bookID: String,
        resourceIDs: [String],
        deviceIdentity: IosReaderDeviceIdentity = IosReaderDeviceIdentity(),
        databaseURL: URL? = nil
    ) async -> [ErmaoShared.ReaderProgressPresentationUpdate] {
        let namespace = ErmaoShared.PublicKt.createReaderSyncNamespace(
            serverIdentity: context.serverIdentity,
            userId: context.userID,
            authorizationVersion: context.authorizationVersion
        )
        let clientID = deviceIdentity.stableDeviceId()
        var updates: [ErmaoShared.ReaderProgressPresentationUpdate] = []
        for resourceID in Set(resourceIDs) where !resourceID.isEmpty {
            let identity = ErmaoShared.PublicKt.createReaderLocalProgressIdentity(
                namespace: namespace,
                clientId: clientID,
                bookId: bookID,
                resourceId: resourceID
            )
            guard let database = try? IosReaderLocalDatabase(
                identity: identity,
                databaseURL: databaseURL
            ) else { continue }
            let local = try? await database.loadPosition(resourceId: resourceID)
            await database.close()
            guard let local else { continue }
            updates.append(ErmaoShared.PublicKt.createReaderProgressPresentationUpdate(
                namespaceKey: context.namespaceKey,
                bookId: bookID,
                resourceId: resourceID,
                position: local.position,
                capturedAtEpochMillis: local.capturedAtEpochMillis
            ))
        }
        return updates
    }
}
