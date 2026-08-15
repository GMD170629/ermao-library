import Foundation
import XCTest
@preconcurrency import ErmaoShared
@testable import ErmaoLibrary

@MainActor
final class DownloadStoreTests: XCTestCase {
    func testLiveStylesVolumeTransferDiagnostic() async throws {
        let profileID = "03139ac0-7820-4e10-9f9e-73f177327398"
        let context = ContentRequestContext(
            profileID: profileID,
            profileDisplayName: "192.168.18.228",
            serverIdentity: "server_d25920669ac94839b6ee9a7054d4dc00",
            userID: "py_543d36db186e4ddca6210e5eee51adb0",
            authorizationVersion: 1,
            baseURL: "http://192.168.18.228:3000",
            acceptsInsecureTLS: false
        )
        let cookieStore = KeychainCookiePayloadStore()
        XCTAssertNotNil(try cookieStore.load(profileID: profileID), "The live device session cookie must be available")
        let transfer = SharedManagedDownloadTransfer(cookieStore: cookieStore)
        let volume = WorkVolume(
            id: "imp_2dfdb3d04f8b7238152bec2373f57213b5681dc2",
            mediaVersionID: "imp_0e42263b2877d99f6ae9387edf572c2d8f777d7e",
            title: "Styles",
            formatLabel: "EPUB",
            sizeLabel: nil,
            progress: nil,
            isReadable: true,
            isSelected: true
        )
        let gateway = IosCompositionKt.createIosDownloadsGateway(
            cookieStore: cookieStore,
            profileId: context.profileID,
            displayName: context.profileDisplayName,
            baseUrl: context.baseURL,
            serverIdentity: context.serverIdentity,
            acceptsInsecureTls: context.acceptsInsecureTLS
        )
        let sharedContext = PublicKt.createDownloadRequestContext(
            profileId: context.profileID,
            displayName: context.profileDisplayName,
            baseUrl: context.baseURL,
            serverIdentity: context.serverIdentity,
            acceptsInsecureTls: context.acceptsInsecureTLS,
            userId: context.userID,
            authorizationVersion: context.authorizationVersion
        )
        let gatewayResult = try await gateway.load(context: sharedContext, volumeId: volume.id)
        if let failure = gatewayResult as? DownloadBootstrapResultFailure {
            XCTFail("bootstrap \(failure.error.code): \(failure.error.diagnosticMessage ?? "no diagnostic")")
            return
        }
        let bootstrap = try await transfer.prepare(context: context, volumeID: volume.id)
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ManagedDownloadStore(rootDirectory: root)
        let record = try await store.enqueue(
            namespace: context.namespaceKey,
            work: WorkCard(
                id: "imp_8a0849cd61b719a802a30f1d655a0e4bc05ecf3b",
                title: "Styles",
                author: "Agatha Christie",
                cover: nil,
                progress: nil,
                availableMediaKinds: [.ebook]
            ),
            volume: volume,
            mediaVersionID: bootstrap.mediaVersionID,
            mediaKind: bootstrap.mediaKind,
            readerType: bootstrap.readerType,
            expectedBytes: bootstrap.expectedBytes
        )
        let destination = try await store.destination(for: record)
        let receipt = try await transfer.download(
            ManagedDownloadRequest(context: context, record: record, destination: destination)
        ) { _ in }
        let attributes = try FileManager.default.attributesOfItem(atPath: destination.partialFileURL.path)
        let actualBytes = try XCTUnwrap((attributes[.size] as? NSNumber)?.int64Value)
        XCTAssertEqual(actualBytes, bootstrap.expectedBytes)
        XCTAssertEqual(receipt.receivedBytes, actualBytes)
        let completed = try await store.publish(record: record, destination: destination, receipt: receipt)
        XCTAssertTrue(completed.isVerifiedOfflineCopy)
    }

    func testPublishRequiresCompleteVerifiedPartialFile() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let record = try await makeRecord(store: store)
        let destination = try await store.destination(for: record)
        try Data([1, 2, 3]).write(to: destination.partialFileURL)

        do {
            _ = try await store.publish(
                record: record,
                destination: destination,
                receipt: ManagedDownloadReceipt(
                    receivedBytes: 3,
                    expectedBytes: 4
                )
            )
            XCTFail("A partial file must never be published as completed")
        } catch let error as ManagedDownloadTransferError {
            XCTAssertEqual(error, .invalidResponse)
        }

        let loaded = try await store.records(namespace: namespace)
        XCTAssertEqual(loaded.single?.state, .queued)
        XCTAssertEqual(loaded.single?.verification, .pending)
        XCTAssertFalse(FileManager.default.fileExists(atPath: destination.partialFileURL.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: destination.finalFileURL.path))
    }

    func testPublishAtomicallyMovesContentThenMarksManifestVerified() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let record = try await makeRecord(store: store)
        let destination = try await store.destination(for: record)
        try Data([1, 2, 3, 4]).write(to: destination.partialFileURL)

        let completed = try await store.publish(
            record: record,
            destination: destination,
            receipt: ManagedDownloadReceipt(
                receivedBytes: 4,
                expectedBytes: 4
            )
        )

        XCTAssertTrue(completed.isVerifiedOfflineCopy)
        XCTAssertFalse(FileManager.default.fileExists(atPath: destination.partialFileURL.path))
        XCTAssertEqual(try Data(contentsOf: destination.finalFileURL), Data([1, 2, 3, 4]))
        let loaded = try await store.records(namespace: namespace)
        XCTAssertTrue(loaded.single?.isVerifiedOfflineCopy == true)
        let localFileURL = await store.fileURL(for: completed)
        XCTAssertEqual(
            localFileURL?.resolvingSymlinksInPath(),
            destination.finalFileURL.resolvingSymlinksInPath()
        )
    }

    func testReloadInvalidatesCompletedManifestWhenLocalFileIsMissing() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let record = try await makeRecord(store: store)
        let destination = try await store.destination(for: record)
        try Data([1, 2, 3, 4]).write(to: destination.partialFileURL)
        let completed = try await store.publish(
            record: record,
            destination: destination,
            receipt: ManagedDownloadReceipt(
                receivedBytes: 4,
                expectedBytes: 4
            )
        )
        try FileManager.default.removeItem(at: destination.finalFileURL)

        let loaded = try await store.records(namespace: namespace)

        XCTAssertEqual(loaded.single?.id, completed.id)
        XCTAssertEqual(loaded.single?.state, .failedTerminal)
        XCTAssertEqual(loaded.single?.verification, .invalid)
        XCTAssertEqual(loaded.single?.stableErrorCode, "DOWNLOAD_LOCAL_FILE_INVALID")
    }

    func testNamespacesRemainIsolatedAndCanBePurgedIndependently() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        _ = try await makeRecord(store: store, namespace: "server|one|1", volumeID: "one")
        _ = try await makeRecord(store: store, namespace: "server|two|1", volumeID: "two")

        try await store.removeNamespace("server|one|1")

        let firstNamespaceRecords = try await store.records(namespace: "server|one|1")
        let secondNamespaceRecords = try await store.records(namespace: "server|two|1")
        XCTAssertTrue(firstNamespaceRecords.isEmpty)
        XCTAssertEqual(secondNamespaceRecords.map(\.volumeID), ["two"])
    }

    func testSameVolumeIdentityReusesQueuedRecord() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let original = try await makeRecord(store: store)
        let volume = WorkVolume(
            id: original.volumeID,
            mediaVersionID: "media-version-ebook",
            title: "Volume",
            formatLabel: "EPUB",
            sizeLabel: "4 bytes",
            progress: nil,
            isReadable: true,
            isSelected: true
        )

        let replacement = try await store.enqueue(
            namespace: namespace,
            work: WorkCard(
                id: "work",
                title: "Work",
                author: "Author",
                cover: nil,
                progress: nil,
                availableMediaKinds: [.ebook]
            ),
            volume: volume,
            mediaVersionID: volume.mediaVersionID,
            mediaKind: .ebook,
            readerType: .reflowable,
            expectedBytes: 4
        )

        XCTAssertEqual(replacement.id, original.id)
        let records = try await store.records(namespace: namespace)
        XCTAssertEqual(records.count, 1)
    }

    func testChangedMediaVersionIdentityReplacesVolumeRecord() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let original = try await makeRecord(store: store)
        let volume = WorkVolume(
            id: original.volumeID,
            mediaVersionID: "media-version-new",
            title: "Volume",
            formatLabel: "EPUB",
            sizeLabel: "4 bytes",
            progress: nil,
            isReadable: true,
            isSelected: true
        )

        let replacement = try await store.enqueue(
            namespace: namespace,
            work: WorkCard(
                id: "work",
                title: "Work",
                author: "Author",
                cover: nil,
                progress: nil,
                availableMediaKinds: [.ebook]
            ),
            volume: volume,
            mediaVersionID: volume.mediaVersionID,
            mediaKind: .ebook,
            readerType: .reflowable,
            expectedBytes: 4
        )

        XCTAssertNotEqual(replacement.id, original.id)
        XCTAssertEqual(replacement.mediaVersionID, "media-version-new")
    }

    func testRealMediaVersionIdentityPersistsAndGroupsVolumesBelowWork() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let first = try await makeRecord(store: store, volumeID: "volume-1")
        let second = try await makeRecord(store: store, volumeID: "volume-2")
        let firstCompleted = try await complete(first, in: store)
        let secondCompleted = try await complete(second, in: store)

        let reloaded = try await store.records(namespace: namespace)
        XCTAssertEqual(Set(reloaded.compactMap(\.mediaVersionID)), ["media-version-ebook"])

        let groups = ManagedDownloadGrouping.completed(
            records: [firstCompleted, secondCompleted],
            query: "Work"
        )
        XCTAssertEqual(groups.count, 1)
        XCTAssertEqual(groups.single?.mediaVersions.count, 1)
        XCTAssertEqual(groups.single?.mediaVersions.single?.mediaVersionID, "media-version-ebook")
        XCTAssertEqual(groups.single?.mediaVersions.single?.records.count, 2)
    }

    func testLegacyManifestRecordWithoutMediaVersionRemainsDecodable() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let record = try await makeRecord(store: store)
        let encoded = try JSONEncoder().encode(record)
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        object.removeValue(forKey: "mediaVersionID")
        let legacyData = try JSONSerialization.data(withJSONObject: object)

        let decoded = try JSONDecoder().decode(ManagedDownloadRecord.self, from: legacyData)

        XCTAssertNil(decoded.mediaVersionID)
        XCTAssertEqual(decoded.effectiveMediaVersionID, "legacy-volume:\(record.volumeID)")
    }

    func testOnlyCompletedVerifiedArtifactSkipsDownloadTransition() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let queued = try await makeRecord(store: store)
        XCTAssertNil(ManagedReaderAccessPolicy.verifiedLocalHandoff(
            record: queued,
            volumeID: queued.volumeID
        ))

        let completed = try await complete(queued, in: store)
        let handoff = ManagedReaderAccessPolicy.verifiedLocalHandoff(
            record: completed,
            volumeID: completed.volumeID
        )

        XCTAssertEqual(handoff?.source, .verifiedLocal(recordID: completed.id))
        XCTAssertEqual(ManagedReaderAccessPolicy.completedRecord(
            records: [completed],
            recordID: completed.id
        )?.id, completed.id)
    }

    private var namespace: String { "server|user|1" }

    private func makeRecord(
        store: ManagedDownloadStore,
        namespace: String? = nil,
        volumeID: String = "volume"
    ) async throws -> ManagedDownloadRecord {
        try await store.enqueue(
            namespace: namespace ?? self.namespace,
            work: WorkCard(
                id: "work",
                title: "Work",
                author: "Author",
                cover: nil,
                progress: nil,
                availableMediaKinds: [.ebook]
            ),
            volume: WorkVolume(
                id: volumeID,
                mediaVersionID: "media-version-ebook",
                title: "Volume",
                formatLabel: "EPUB",
                sizeLabel: "4 bytes",
                progress: nil,
                isReadable: true,
                isSelected: true
            ),
            mediaVersionID: "media-version-ebook",
            mediaKind: .ebook,
            readerType: .reflowable,
            expectedBytes: 4
        )
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("ermao-download-tests-\(UUID().uuidString)", isDirectory: true)
    }

    private func complete(
        _ record: ManagedDownloadRecord,
        in store: ManagedDownloadStore
    ) async throws -> ManagedDownloadRecord {
        let destination = try await store.destination(for: record)
        try Data([1, 2, 3, 4]).write(to: destination.partialFileURL)
        return try await store.publish(
            record: record,
            destination: destination,
            receipt: ManagedDownloadReceipt(
                receivedBytes: 4,
                expectedBytes: 4
            )
        )
    }
}

private extension Array {
    var single: Element? { count == 1 ? first : nil }
}
