import Foundation
import XCTest
@preconcurrency import ErmaoShared
@testable import ErmaoLibrary

@MainActor
final class DownloadStoreTests: XCTestCase {
    func testLiveStylesResourceTransferDiagnostic() async throws {
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
        let resource = BookResource(
            id: "imp_2dfdb3d04f8b7238152bec2373f57213b5681dc2",
            bookID: "imp_8a0849cd61b719a802a30f1d655a0e4bc05ecf3b",
            sourceNodeID: "imp_0e42263b2877d99f6ae9387edf572c2d8f777d7e",
            title: "Styles",
            format: "EPUB",
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
        let gatewayResult = try await gateway.load(context: sharedContext, resourceId: resource.id)
        if let failure = gatewayResult as? DownloadBootstrapFailure {
            XCTFail("bootstrap \(failure.error.code): \(failure.error.diagnosticMessage ?? "no diagnostic")")
            return
        }
        let bootstrap = try await transfer.prepare(context: context, resourceID: resource.id)
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ManagedDownloadStore(rootDirectory: root)
        let record = try await store.enqueue(
            namespace: context.namespaceKey,
            book: BookCard(
                id: "imp_8a0849cd61b719a802a30f1d655a0e4bc05ecf3b",
                title: "Styles",
                author: "Agatha Christie",
                cover: nil,
                progress: nil,
                availableMediaKinds: [.ebook]
            ),
            resource: resource,
            assetID: bootstrap.assetID,
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
        _ = try await makeRecord(store: store, namespace: "server|one|1", resourceID: "one")
        _ = try await makeRecord(store: store, namespace: "server|two|1", resourceID: "two")

        try await store.removeNamespace("server|one|1")

        let firstNamespaceRecords = try await store.records(namespace: "server|one|1")
        let secondNamespaceRecords = try await store.records(namespace: "server|two|1")
        XCTAssertTrue(firstNamespaceRecords.isEmpty)
        XCTAssertEqual(secondNamespaceRecords.map(\.resourceID), ["two"])
    }

    func testSameResourceAndAssetIdentityReusesQueuedRecord() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let original = try await makeRecord(store: store)
        let resource = BookResource(
            id: original.resourceID,
            bookID: original.bookID,
            sourceNodeID: "source-node-ebook",
            title: "Resource",
            format: "EPUB",
            sizeLabel: "4 bytes",
            progress: nil,
            isReadable: true,
            isSelected: true
        )

        let replacement = try await store.enqueue(
            namespace: namespace,
            book: BookCard(
                id: "book",
                title: "Book",
                author: "Author",
                cover: nil,
                progress: nil,
                availableMediaKinds: [.ebook]
            ),
            resource: resource,
            assetID: original.assetID,
            readerType: .reflowable,
            expectedBytes: 4
        )

        XCTAssertEqual(replacement.id, original.id)
        let records = try await store.records(namespace: namespace)
        XCTAssertEqual(records.count, 1)
    }

    func testChangedAssetIdentityReplacesResourceRecord() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let original = try await makeRecord(store: store)
        let resource = BookResource(
            id: original.resourceID,
            bookID: original.bookID,
            sourceNodeID: "source-node-new",
            title: "Resource",
            format: "EPUB",
            sizeLabel: "4 bytes",
            progress: nil,
            isReadable: true,
            isSelected: true
        )

        let replacement = try await store.enqueue(
            namespace: namespace,
            book: BookCard(
                id: "book",
                title: "Book",
                author: "Author",
                cover: nil,
                progress: nil,
                availableMediaKinds: [.ebook]
            ),
            resource: resource,
            assetID: "asset-new",
            readerType: .reflowable,
            expectedBytes: 4
        )

        XCTAssertNotEqual(replacement.id, original.id)
        XCTAssertEqual(replacement.assetID, "asset-new")
    }

    func testAssetIdentityPersistsAndGroupsResourcesBelowBook() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let first = try await makeRecord(store: store, resourceID: "resource-1", assetID: "asset-1")
        let second = try await makeRecord(store: store, resourceID: "resource-2", assetID: "asset-2")
        let firstCompleted = try await complete(first, in: store)
        let secondCompleted = try await complete(second, in: store)

        let reloaded = try await store.records(namespace: namespace)
        XCTAssertEqual(Set(reloaded.map(\.assetID)), ["asset-1", "asset-2"])

        let groups = ManagedDownloadGrouping.completed(
            records: [firstCompleted, secondCompleted],
            query: "Book"
        )
        XCTAssertEqual(groups.count, 1)
        XCTAssertEqual(groups.single?.resources.count, 2)
        XCTAssertEqual(groups.single?.resources.flatMap(\.records).count, 2)
    }

    func testDownloadLocalizationKeepsStorageAndImplicitVersionKeys() throws {
        let catalog = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("ErmaoLibrary/Resources/Localizable.xcstrings")
        let json = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(contentsOf: catalog)) as? [String: Any]
        )
        let strings = try XCTUnwrap(json["strings"] as? [String: Any])
        XCTAssertNotNil(strings["downloads.storage.used"])
        XCTAssertNotNil(strings["downloads.version.implicit"])
    }

    func testCatalogWithoutAssetIdentityIsDiscarded() async throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ManagedDownloadStore(rootDirectory: root)
        let record = try await makeRecord(store: store)
        let encoded = try JSONEncoder().encode(record)
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        object.removeValue(forKey: "assetID")
        let legacyData = try JSONSerialization.data(withJSONObject: object)

        XCTAssertThrowsError(try JSONDecoder().decode(ManagedDownloadRecord.self, from: legacyData))
    }

    func testOnlyCompletedVerifiedArtifactSkipsDownloadTransition() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let queued = try await makeRecord(store: store)
        XCTAssertNil(ManagedReaderAccessPolicy.verifiedLocalHandoff(
            record: queued,
            resourceID: queued.resourceID
        ))

        let completed = try await complete(queued, in: store)
        let handoff = ManagedReaderAccessPolicy.verifiedLocalHandoff(
            record: completed,
            resourceID: completed.resourceID
        )

        XCTAssertEqual(handoff?.source, .verifiedLocal(recordID: completed.id))
        XCTAssertEqual(ManagedReaderAccessPolicy.completedRecord(
            records: [completed],
            recordID: completed.id
        )?.id, completed.id)
    }

    private func waitUntil(
        timeout: TimeInterval = 1,
        _ condition: @MainActor () -> Bool
    ) async throws {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if condition() { return }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("timed out waiting for download catalog to load")
    }

    private var namespace: String { "server|user|1" }

    private func makeRecord(
        store: ManagedDownloadStore,
        namespace: String? = nil,
        resourceID: String = "resource",
        assetID: String = "asset"
    ) async throws -> ManagedDownloadRecord {
        try await store.enqueue(
            namespace: namespace ?? self.namespace,
            book: BookCard(
                id: "book",
                title: "Book",
                author: "Author",
                cover: nil,
                progress: nil,
                availableMediaKinds: [.ebook]
            ),
            resource: BookResource(
                id: resourceID,
                bookID: "book",
                sourceNodeID: "source-node-ebook",
                title: "Resource",
                format: "EPUB",
                sizeLabel: "4 bytes",
                progress: nil,
                isReadable: true,
                isSelected: true
            ),
            assetID: assetID,
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
