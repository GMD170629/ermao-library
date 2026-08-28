import CryptoKit
import Foundation
import XCTest
import UIKit
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumShared
@testable import ErmaoLibrary

@MainActor
final class DownloadStoreTests: XCTestCase {
    func testOriginalPageSetPublishesAsOneVerifiedDirectoryArtifact() async throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ManagedDownloadStore(rootDirectory: root)
        let pageSize = CGSize(width: 320, height: 480)
        let rendererFormat = UIGraphicsImageRendererFormat()
        rendererFormat.scale = 1
        let pages = [UIColor.systemBlue, UIColor.systemOrange].enumerated().map { index, color in
            UIGraphicsImageRenderer(size: pageSize, format: rendererFormat).pngData { context in
                color.setFill()
                context.fill(CGRect(origin: .zero, size: pageSize))
                UIColor.white.setFill()
                context.fill(CGRect(x: 40, y: 80, width: 80 + index * 80, height: 200))
            }
        }
        let totalBytes = pages.reduce(0) { $0 + $1.count }
        let record = try await store.seedDownload(
            namespace: namespace,
            book: BookCard(id: "book", title: "Book", author: "Author", cover: nil, progress: nil),
            resource: BookResource(
                id: "image-resource", bookID: "book", sourceNodeID: "directory", title: "Pages",
                format: "IMAGE_DIR", sizeLabel: nil, progress: nil, isReadable: true, isSelected: true
            ),
            assetID: "page-set:image-resource",
            readerType: .comic,
            expectedBytes: Int64(totalBytes),
            artifactKind: .originalPageSet
        )
        let destination = try await store.destination(for: record)
        try FileManager.default.createDirectory(at: destination.partialFileURL, withIntermediateDirectories: true)
        for (index, page) in pages.enumerated() {
            try page.write(to: destination.partialFileURL.appendingPathComponent("page-\(index).png"))
        }
        let manifest: [String: Any] = [
            "contractVersion": 4,
            "artifactKind": "OriginalPageSet",
            "resourceId": "image-resource",
            "artifactId": "page-set:image-resource",
            "totalBytes": totalBytes,
            "members": pages.enumerated().map { index, page -> [String: Any] in [
                "assetId": "page-\(index)", "sequenceIndex": index, "mimeType": "image/png",
                "sizeBytes": page.count, "fileName": "page-\(index).png",
            ] },
        ]
        try JSONSerialization.data(withJSONObject: manifest).write(
            to: destination.partialFileURL.appendingPathComponent("bundle.json")
        )

        let completed = try await store.seedCompleted(
            record: record,
            destination: destination,
            receipt: CompletedFixtureBytes(receivedBytes: Int64(totalBytes), expectedBytes: Int64(totalBytes))
        )
        let resolvedLocalURL = await store.fileURL(for: completed)
        let localURL = try XCTUnwrap(resolvedLocalURL)
        let bundle = try IosImageDirectoryBundle(directory: localURL, expectedResourceID: "image-resource")

        XCTAssertTrue(completed.isVerifiedOfflineCopy)
        XCTAssertTrue((try localURL.resourceValues(forKeys: [.isDirectoryKey])).isDirectory == true)
        XCTAssertEqual(bundle.pages.map(\.resourceHref), ["pages/0", "pages/1"])
        let managed = IosManagedPublication(
            resourceID: "image-resource", displayTitle: "Pages", fileURL: localURL,
            byteCount: Int64(totalBytes), bookID: "book", assetID: "page-set:image-resource",
            namespace: namespace, sourceFormat: .imagedir
        )
        let opened = try IosImageDirectoryPublicationFactory().open(managed, pageTitleHints: bundle.pages)
        for (index, link) in opened.publication.readingOrder.enumerated() {
            let resource = try XCTUnwrap(opened.publication.get(link))
            let bytes = try await resource.read().get()
            XCTAssertEqual(bytes, pages[index], "Reader must return each original PAGE in order")
            let image = try XCTUnwrap(UIImage(data: bytes))
            XCTAssertEqual(image.size, pageSize)
            let attachment = XCTAttachment(image: image)
            attachment.name = "original-image-directory-page-\(index)"
            attachment.lifetime = .keepAlways
            add(attachment)
        }
        await opened.close()
    }

    func testManifestV3RecordMigratesToV4WithoutDeletingCompletedFile() async throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ManagedDownloadStore(rootDirectory: root)
        let record = try await makeRecord(store: store)
        let completed = try await complete(record, in: store)
        let namespaceDirectory = try XCTUnwrap(
            FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: [.isDirectoryKey])
                .first(where: { (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true })
        )
        let manifestURL = namespaceDirectory.appendingPathComponent("manifest.json")
        var manifest = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(contentsOf: manifestURL)) as? [String: Any]
        )
        manifest["contractVersion"] = 3
        try JSONSerialization.data(withJSONObject: manifest).write(to: manifestURL, options: .atomic)

        let migrated = try await store.records(namespace: namespace)

        XCTAssertEqual(migrated.single?.id, completed.id)
        XCTAssertEqual(migrated.single?.effectiveArtifactKind, .singleOriginalAsset)
        let migratedLocalURL = await store.fileURL(for: migrated.single!)
        XCTAssertNotNil(migratedLocalURL)
        let persisted = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(contentsOf: manifestURL)) as? [String: Any]
        )
        XCTAssertEqual(persisted["contractVersion"] as? Int, 4)
    }

    func testLiveStylesResourceTransferDiagnostic() async throws {
        let profileID = "03139ac0-7820-4e10-9f9e-73f177327398"
        let context = ContentRequestContext(
            profileID: profileID,
            profileDisplayName: "192.168.18.228",
            serverIdentity: "server_d25920669ac94839b6ee9a7054d4dc00",
            userID: "py_48e39b93790f4057995840a18f4302a3",
            authorizationVersion: 1,
            baseURL: "http://192.168.18.228:3000",
            acceptsInsecureTLS: false
        )
        let cookieStore = KeychainCookiePayloadStore()
        XCTAssertNotNil(try cookieStore.load(profileID: profileID), "The live device session cookie must be available")
        let transfer = SharedManagedDownloadTransfer(cookieStore: cookieStore)
        let resource = BookResource(
            id: "py_db7f936c9cda4a5a865892029c18d1ff",
            bookID: "py_75b1eb8b3f5c4a0386a7f06ffc956563",
            sourceNodeID: "py_c380d324fe7d4aa8ae579d6f6051fd86",
            title: "EPUB acceptance fixture",
            format: "EPUB",
            sizeLabel: nil,
            progress: nil,
            isReadable: true,
            isSelected: true
        )
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ManagedDownloadStore(rootDirectory: root)
        try await transfer.download(context: context, resourceID: resource.id, repository: store) { _ in }
        let records = try await store.records(namespace: context.namespaceKey)
        let completed = try XCTUnwrap(records.single)
        XCTAssertTrue(completed.isVerifiedOfflineCopy)
        let storedURL = await store.fileURL(for: completed)
        let file = try XCTUnwrap(storedURL)
        XCTAssertEqual(try file.resourceValues(forKeys: [.fileSizeKey]).fileSize, completed.expectedBytes.map(Int.init))
        // A repeated explicit request must reuse the same verified task and artifact.
        try await transfer.download(context: context, resourceID: resource.id, repository: store) { _ in }
        let repeated = try await store.records(namespace: context.namespaceKey)
        XCTAssertEqual(repeated.map(\.id), [completed.id])
    }

    func testLiveAzw3TransferPreservesOriginalBytesAndParses() async throws {
        let context = ContentRequestContext(
            profileID: "03139ac0-7820-4e10-9f9e-73f177327398",
            profileDisplayName: "192.168.18.228",
            serverIdentity: "server_d25920669ac94839b6ee9a7054d4dc00",
            userID: "py_48e39b93790f4057995840a18f4302a3",
            authorizationVersion: 1,
            baseURL: "http://192.168.18.228:3000",
            acceptsInsecureTLS: false
        )
        let cookieStore = KeychainCookiePayloadStore()
        XCTAssertNotNil(try cookieStore.load(profileID: context.profileID))
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
        if let failure = try await gateway.load(
            context: sharedContext,
            resourceId: "py_35ecd0b1eb7b4e90ad34f38fdbff4465"
        ) as? ErmaoShared.DownloadBootstrapResultFailure {
            XCTFail("bootstrap \(failure.error.code): \(failure.error.diagnosticMessage ?? "no diagnostic")")
            return
        }
        let transfer = SharedManagedDownloadTransfer(cookieStore: cookieStore)
        let resource = BookResource(
            id: "py_35ecd0b1eb7b4e90ad34f38fdbff4465",
            bookID: "py_a0469b0ed7a74bb382372f69d8895b54",
            sourceNodeID: "live-source-node",
            title: "Reader Sample 03",
            format: "AZW3",
            sizeLabel: nil,
            progress: nil,
            isReadable: true,
            isSelected: true
        )
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ManagedDownloadStore(rootDirectory: root)
        try await transfer.download(context: context, resourceID: resource.id, repository: store) { _ in }
        let records = try await store.records(namespace: context.namespaceKey)
        let completed = try XCTUnwrap(records.single)
        let storedURL = await store.fileURL(for: completed)
        let file = try XCTUnwrap(storedURL)
        XCTAssertEqual(completed.format, "AZW3")
        XCTAssertEqual(completed.mimeType, "application/vnd.amazon.ebook")
        XCTAssertEqual(file.pathExtension, "azw3")
        let bytes = try Data(contentsOf: file)
        XCTAssertEqual(Int64(bytes.count), completed.expectedBytes)
        XCTAssertEqual(
            SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined(),
            "528c43db8b2df3190dbf42f96fe6be68391d9239a186fb77d0670dda832863dc"
        )
        let book = try IosMobiBook.open(fileURL: file)
        let info = try await book.info()
        await book.close()
        XCTAssertGreaterThan(info.readingOrderCount, 0)
    }

    func testPublishRequiresCompleteVerifiedPartialFile() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let record = try await makeRecord(store: store)
        let destination = try await store.destination(for: record)
        try Data([1, 2, 3]).write(to: destination.partialFileURL)

        do {
            _ = try await store.seedCompleted(
                record: record,
                destination: destination,
                receipt: CompletedFixtureBytes(
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

        let completed = try await store.seedCompleted(
            record: record,
            destination: destination,
            receipt: CompletedFixtureBytes(
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
        let completed = try await store.seedCompleted(
            record: record,
            destination: destination,
            receipt: CompletedFixtureBytes(
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

    func testUpdatingCatalogProjectionPreservesTaskIdentity() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let original = try await makeRecord(store: store)
        var updated = original
        updated.receivedBytes = 2
        updated.state = .paused
        try await store.update(updated)
        let records = try await store.records(namespace: namespace)
        XCTAssertEqual(records.map(\.id), [original.id])
        XCTAssertEqual(records.single?.receivedBytes, 2)
        XCTAssertEqual(records.single?.state, .paused)
    }

    func testExactKindleFamilySourceFormatPreservesExtensionAndMime() async throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ManagedDownloadStore(rootDirectory: root)
        let resource = BookResource(
            id: "resource", bookID: "book", sourceNodeID: "source-node-kindle",
            title: "Resource", format: "AZW3", sizeLabel: "4 bytes",
            progress: nil, isReadable: true, isSelected: true
        )
        let book = BookCard(id: "book", title: "Book", author: nil, cover: nil, progress: nil)
        let exact = try await store.seedDownload(
            namespace: namespace,
            book: book,
            resource: resource,
            assetID: "asset",
            sourceFormat: "AZW3",
            mimeType: "application/vnd.amazon.ebook",
            readerType: .reflowable,
            expectedBytes: 4
        )
        let destination = try await store.destination(for: exact)

        XCTAssertEqual(exact.format, "AZW3")
        XCTAssertEqual(exact.mimeType, "application/vnd.amazon.ebook")
        XCTAssertEqual(destination.finalFileURL.lastPathComponent, "asset.azw3")
        let persisted = try await store.records(namespace: namespace)
        XCTAssertEqual(persisted.map(\.id), [exact.id])
    }

    func testLegacyUserDownloadIsPreservedWithoutGuessingItsFormat() async throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let encodedNamespace = Data(namespace.utf8).base64EncodedString()
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "+", with: "-")
        let namespaceDirectory = root.appendingPathComponent(encodedNamespace, isDirectory: true)
        let contentDirectory = namespaceDirectory.appendingPathComponent("content/legacy", isDirectory: true)
        try FileManager.default.createDirectory(at: contentDirectory, withIntermediateDirectories: true)
        let legacyURL = contentDirectory.appendingPathComponent("asset.kindle")
        try Data([1, 2, 3, 4]).write(to: legacyURL)
        let now = Date()
        let legacy = ManagedDownloadRecord(
            id: "legacy-record",
            namespace: namespace,
            bookID: "book",
            bookTitle: "Book",
            bookAuthor: nil,
            resourceID: "resource",
            resourceTitle: "Resource",
            assetID: "asset",
            format: "KINDLE",
            mimeType: nil,
            readerType: .reflowable,
            state: .completed,
            verification: .verified,
            expectedBytes: 4,
            artifactKind: .singleOriginalAsset,
            receivedBytes: 4,
            localRelativePath: "content/legacy/asset.kindle",
            stableErrorCode: nil,
            createdAt: now,
            updatedAt: now,
            completedAt: now,
            lastOpenedAt: nil
        )
        struct LegacyManifest: Encodable {
            let contractVersion: Int
            let records: [ManagedDownloadRecord]
        }
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        try encoder.encode(LegacyManifest(contractVersion: 4, records: [legacy])).write(
            to: namespaceDirectory.appendingPathComponent("manifest.json"),
            options: .atomic
        )
        let store = ManagedDownloadStore(rootDirectory: root)

        let records = try await store.records(namespace: namespace)
        XCTAssertEqual(records.map(\.id), [legacy.id])
        XCTAssertTrue(FileManager.default.fileExists(atPath: legacyURL.path))
        let persisted = try JSONSerialization.jsonObject(
            with: Data(contentsOf: namespaceDirectory.appendingPathComponent("manifest.json"))
        ) as? [String: Any]
        XCTAssertEqual((persisted?["records"] as? [Any])?.count, 1)
    }

    func testChangedAssetIdentityPreservesPreviousTask() async throws {
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

        let replacement = try await store.seedDownload(
            namespace: namespace,
            book: BookCard(
                id: "book",
                title: "Book",
                author: "Author",
                cover: nil,
                progress: nil
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
        for locale in ["en", "zh-Hans"] {
            let localizationPath = try XCTUnwrap(
                Bundle.main.path(forResource: locale, ofType: "lproj")
            )
            let bundle = try XCTUnwrap(Bundle(path: localizationPath))
            for key in ["downloads.storage.used", "downloads.version.implicit"] {
                let localized = bundle.localizedString(forKey: key, value: nil, table: nil)
                XCTAssertNotEqual(localized, key, "Missing \(key) in \(locale)")
                XCTAssertFalse(localized.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
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

    func testOfflineHandoffOnlyAcceptsCompletedVerifiedArtifacts() async throws {
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

    func testNativeReaderPolicyRequiresExactMobiFamilyFormatAndAcceptsAllComicArchives() {
        XCTAssertFalse(ReaderFormatSupport.shared.canReadOriginal(
            readerType: "reflowable",
            format: "KINDLE"
        ))
        for format in ["MOBI", "AZW", "AZW3", "PRC"] {
            XCTAssertTrue(
                ReaderFormatSupport.shared.canReadOriginal(readerType: "reflowable", format: format),
                "Expected exact native reflowable support for \(format)"
            )
        }
        for format in ["CBZ", "ZIP", "CBR", "RAR", "IMAGE_DIR"] {
            XCTAssertTrue(
                ReaderFormatSupport.shared.canReadOriginal(readerType: "comic", format: format),
                "Expected native comic support for \(format)"
            )
        }
    }

    func testKindleLibraryFamilyEntersBootstrapButNeverIdentifiesAnOfflineArtifact() {
        func handoff(_ source: ReaderHandoffSource, readerType: ManagedDownloadReaderType = .reflowable) -> ReaderHandoff {
            ReaderHandoff(
                bookID: "book", resourceID: "resource", assetID: nil,
                title: "Book", resourceTitle: "Resource", format: " kindle ",
                readerType: readerType, source: source
            )
        }
        XCTAssertTrue(ManagedReaderAccessPolicy.supportsNativeHandoff(handoff(.remoteStream)))
        XCTAssertFalse(ManagedReaderAccessPolicy.supportsNativeHandoff(handoff(.verifiedLocal(recordID: "record"))))
        XCTAssertFalse(ManagedReaderAccessPolicy.supportsNativeHandoff(handoff(.remoteStream, readerType: .audio)))
        XCTAssertFalse(ManagedReaderAccessPolicy.supportsNativeHandoff(handoff(.remoteStream, readerType: .comic)))
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
        try await store.seedDownload(
            namespace: namespace ?? self.namespace,
            book: BookCard(
                id: "book",
                title: "Book",
                author: "Author",
                cover: nil,
                progress: nil
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
        return try await store.seedCompleted(
            record: record,
            destination: destination,
            receipt: CompletedFixtureBytes(
                receivedBytes: 4,
                expectedBytes: 4
            )
        )
    }
}

private extension Array {
    var single: Element? { count == 1 ? first : nil }
}

// Storage fixtures create explicit persisted states; production transitions are tested through shared Downloads.
private struct CompletedFixtureBytes {
    let receivedBytes: Int64
    let expectedBytes: Int64?
}

private extension ManagedDownloadStore {
    func seedDownload(namespace: String, book: BookCard, resource: BookResource, assetID: String,
                      sourceFormat: String? = nil, mimeType: String? = nil,
                      readerType: ManagedDownloadReaderType, expectedBytes: Int64?,
                      artifactKind: ManagedDownloadArtifactKind = .singleOriginalAsset, now: Date = Date()) throws -> ManagedDownloadRecord {
        let record = ManagedDownloadRecord(id: UUID().uuidString, namespace: namespace,
            bookID: book.id, bookTitle: book.title, bookAuthor: book.author,
            resourceID: resource.id, resourceTitle: resource.title, assetID: assetID,
            format: sourceFormat ?? resource.format, mimeType: mimeType, readerType: readerType,
            state: .queued, verification: .pending, expectedBytes: expectedBytes, artifactKind: artifactKind,
            receivedBytes: 0, localRelativePath: nil, stableErrorCode: nil, createdAt: now, updatedAt: now,
            completedAt: nil, lastOpenedAt: nil)
        try update(record)
        return record
    }

    func seedCompleted(record: ManagedDownloadRecord, destination: ManagedDownloadDestination,
                       receipt: CompletedFixtureBytes, now: Date = Date()) throws -> ManagedDownloadRecord {
        let reference = try publishFile(record: record, destination: destination, verifiedBytes: receipt.receivedBytes)
        var fixture = record
        fixture.state = .completed
        fixture.verification = .verified
        fixture.localRelativePath = reference
        fixture.receivedBytes = receipt.receivedBytes
        fixture.completedAt = now
        try update(fixture)
        return fixture
    }
}
