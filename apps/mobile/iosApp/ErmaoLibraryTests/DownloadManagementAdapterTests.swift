import Foundation
@preconcurrency import ErmaoShared
import XCTest
@testable import ErmaoLibrary

@MainActor
final class DownloadManagementAdapterTests: XCTestCase {
    private let namespace = "server|user|1"

    func testCatalogSizeKeepsUnknownTotalUnknown() {
        var download = record(id: "size", state: .paused)
        download.expectedBytes = 1_000
        download.receivedBytes = 400
        XCTAssertEqual(DownloadManagementAdapter.catalogResource(download).sizeBytes, 1_000)
        download.expectedBytes = nil
        XCTAssertNil(DownloadManagementAdapter.catalogResource(download).sizeBytes)
    }

    func testProjectsSharedManagementStatusMatrix() {
        let completed = completedRecord(id: "completed")
        let scenarios: [Scenario] = [
            Scenario(
                record: nil,
                active: false,
                available: true,
                expectedStatus: .notdownloaded,
                expectedActions: [.download]
            ),
            Scenario(
                record: nil,
                active: false,
                available: false,
                expectedStatus: .unavailable,
                expectedActions: []
            ),
            Scenario(
                record: record(id: "queued", state: .queued),
                active: false,
                available: true,
                expectedStatus: .queued,
                expectedActions: [.pause, .remove]
            ),
            Scenario(
                record: record(id: "downloading", state: .downloading),
                active: false,
                available: true,
                expectedStatus: .downloading,
                expectedActions: [.pause, .remove]
            ),
            Scenario(
                record: record(id: "paused", state: .paused),
                active: false,
                available: true,
                expectedStatus: .paused,
                expectedActions: [.resume, .remove]
            ),
            Scenario(
                record: record(id: "retryable", state: .failedRetryable),
                active: false,
                available: true,
                expectedStatus: .failedretryable,
                expectedActions: [.retry, .remove]
            ),
            Scenario(
                record: record(id: "terminal", state: .failedTerminal),
                active: false,
                available: true,
                expectedStatus: .failedterminal,
                expectedActions: [.remove]
            ),
            Scenario(
                record: completed,
                active: false,
                available: true,
                expectedStatus: .completed,
                expectedActions: [.open, .remove]
            ),
        ]

        for scenario in scenarios {
            let projected = DownloadManagementAdapter.project(
                resource: resource(isReadable: scenario.available),
                record: scenario.record,
                active: scenario.active
            )

            XCTAssertEqual(projected.status, scenario.expectedStatus)
            XCTAssertEqual(projected.actions, scenario.expectedActions)
        }
    }

    func testInvalidCompletedRecordProjectsToRetryableInvalidLocal() {
        var invalid = completedRecord(id: "invalid")
        invalid.state = .failedTerminal
        invalid.verification = .invalid
        invalid.stableErrorCode = "DOWNLOAD_LOCAL_FILE_INVALID"

        let projected = DownloadManagementAdapter.project(
            resource: resource(isReadable: true),
            record: invalid,
            active: false
        )

        XCTAssertEqual(projected.status, .invalidlocal)
        XCTAssertEqual(projected.actions, [.retry, .remove])
    }

    func testActiveOwnershipOverridesStalePausedRecord() {
        let projected = DownloadManagementAdapter.project(
            resource: resource(isReadable: true),
            record: record(id: "stale-paused", state: .paused),
            active: true
        )

        XCTAssertEqual(projected.status, .downloading)
        XCTAssertEqual(projected.actions, [.pause, .remove])
    }

    func testVerifiedCompletedArtifactRemainsOpenableWhenRemoteIsUnavailable() {
        let projected = DownloadManagementAdapter.project(
            resource: resource(isReadable: false),
            record: completedRecord(id: "offline-completed"),
            active: false
        )

        XCTAssertEqual(projected.status, .completed)
        XCTAssertEqual(projected.actions, [.open, .remove])
    }

    func testMismatchedSharedTaskIdentityFallsBackToNativeState() {
        var paused = record(id: "identity-fallback", state: .paused)
        paused.sharedTaskJSON = taskJSON(
            for: paused,
            taskResourceID: "another-resource",
            taskStatus: .completed
        )

        XCTAssertEqual(DownloadManagementAdapter.taskStatus(for: paused), .paused)
        let projected = DownloadManagementAdapter.project(
            resource: resource(isReadable: true),
            record: paused,
            active: false
        )
        XCTAssertEqual(projected.status, .paused)
        XCTAssertEqual(projected.actions, [.resume, .remove])
    }

    private struct Scenario {
        let record: ManagedDownloadRecord?
        let active: Bool
        let available: Bool
        let expectedStatus: DownloadManagementStatus
        let expectedActions: Set<DownloadManagementAction>
    }

    private func resource(isReadable: Bool) -> BookResource {
        BookResource(
            id: "resource",
            bookID: "book",
            sourceNodeID: "source-node",
            title: "Resource",
            format: "EPUB",
            sizeLabel: "4 bytes",
            progress: nil,
            isReadable: isReadable,
            isSelected: true
        )
    }

    private func record(
        id: String,
        state: ManagedDownloadState,
        verification: ManagedDownloadVerification = .pending,
        errorCode: String? = nil
    ) -> ManagedDownloadRecord {
        ManagedDownloadRecord(
            id: id,
            namespace: namespace,
            bookID: "book",
            bookTitle: "Book",
            bookAuthor: "Author",
            resourceID: "resource",
            resourceTitle: "Resource",
            assetID: "asset-\(id)",
            format: "EPUB",
            mimeType: "application/epub+zip",
            readerType: .reflowable,
            state: state,
            verification: verification,
            expectedBytes: 4,
            artifactKind: .singleOriginalAsset,
            receivedBytes: verification == .verified ? 4 : 0,
            localRelativePath: verification == .verified ? "content/\(id).epub" : nil,
            stableErrorCode: errorCode,
            createdAt: Date(timeIntervalSince1970: 1),
            updatedAt: Date(timeIntervalSince1970: 2),
            completedAt: verification == .verified ? Date(timeIntervalSince1970: 2) : nil,
            lastOpenedAt: nil
        )
    }

    private func completedRecord(id: String) -> ManagedDownloadRecord {
        var completed = record(
            id: id,
            state: .completed,
            verification: .verified
        )
        completed.sharedTaskJSON = taskJSON(for: completed)
        return completed
    }

    private func taskJSON(
        for record: ManagedDownloadRecord,
        taskResourceID: String? = nil,
        taskStatus: DownloadTaskStatus = .completed
    ) -> String {
        let descriptor = DownloadDescriptor(
            identity: DownloadIdentity(
                namespace: PublicKt.createDownloadNamespace(
                    serverIdentity: "server",
                    userId: "user",
                    authorizationVersion: 1
                ),
                bookId: record.bookID,
                resourceId: taskResourceID ?? record.resourceID,
                assetId: record.assetID
            ),
            bookTitle: record.bookTitle,
            bookAuthor: record.bookAuthor,
            coverApiPath: nil,
            resourceTitle: record.resourceTitle,
            format: record.format,
            readerType: .reflowable,
            source: DownloadSource(
                apiPath: "/api/assets/\(record.assetID)",
                mimeType: record.mimeType ?? "application/epub+zip",
                totalBytes: 4,
                sourceModifiedAtMillis: nil
            ),
            resourceIndex: nil,
            resourceSortOrder: nil,
            isDownloadable: true,
            artifactKind: .singleoriginalasset,
            members: []
        )
        let artifact = CompletedDownloadArtifact(
            descriptor: descriptor,
            localReference: record.localRelativePath ?? "content/\(record.id).epub",
            verifiedBytes: 4,
            completedAtEpochMillis: 2,
            lastOpenedAtEpochMillis: nil
        )
        return DownloadCatalogCodec.shared.encode(task: DownloadTask(
            id: record.id,
            descriptor: descriptor,
            status: taskStatus,
            transferredBytes: 4,
            failureCode: nil,
            artifact: artifact
        ))
    }
}
