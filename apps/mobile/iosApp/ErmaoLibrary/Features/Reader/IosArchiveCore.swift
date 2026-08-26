import Foundation
import ErmaoArchiveCore

struct IosArchiveCoreFailure: Error, Sendable {
    let stableCode: String
    let detail: String
}

struct IosArchiveCorePage: Equatable, Sendable {
    let index: Int
    let path: String
    let sizeBytes: Int64
}

final class IosArchiveCore: @unchecked Sendable {
    private let lock = NSLock()
    private var handle: OpaquePointer?
    let pages: [IosArchiveCorePage]

    init(fileURL: URL) throws {
        let values = try fileURL.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
        guard values.isRegularFile == true, values.isSymbolicLink != true else {
            throw IosArchiveCoreFailure(stableCode: "ARCHIVE_OPEN_FAILED", detail: "Archive file is missing")
        }
        var opened: OpaquePointer?
        var error = ermao_archive_error()
        let limits = ermao_archive_limits(
            maximum_entries: 10_000,
            maximum_page_bytes: 64 * 1_024 * 1_024,
            maximum_expanded_bytes: 4 * 1_024 * 1_024 * 1_024
        )
        let result = fileURL.withUnsafeFileSystemRepresentation { path in
            path.map { ermao_archive_open($0, limits, &opened, &error) } ?? 0
        }
        guard result == 1, let opened else { throw Self.failure(error) }
        handle = opened
        do {
            let count = ermao_archive_page_count(opened)
            guard count > 0, count <= 10_000 else {
                throw IosArchiveCoreFailure(
                    stableCode: "ARCHIVE_ENTRY_LIMIT_EXCEEDED",
                    detail: "Archive page count is invalid"
                )
            }
            var indexed: [IosArchiveCorePage] = []
            indexed.reserveCapacity(count)
            for index in 0 ..< count {
                var path: UnsafePointer<CChar>?
                var size: Int64 = 0
                var pageError = ermao_archive_error()
                guard ermao_archive_page_info(opened, index, &path, &size, &pageError) == 1,
                      let path, size > 0 else { throw Self.failure(pageError) }
                indexed.append(
                    IosArchiveCorePage(index: index, path: String(cString: path), sizeBytes: size)
                )
            }
            pages = indexed
        } catch {
            ermao_archive_close(opened)
            handle = nil
            throw error
        }
    }

    deinit { close() }

    func readPage(at index: Int) throws -> Data {
        lock.lock()
        defer { lock.unlock() }
        guard let handle, pages.indices.contains(index) else {
            throw IosArchiveCoreFailure(stableCode: "ARCHIVE_PAGE_OUT_OF_RANGE", detail: "Archive page is unavailable")
        }
        let size = pages[index].sizeBytes
        guard size > 0, size <= Int64(Int.max) else {
            throw IosArchiveCoreFailure(stableCode: "ARCHIVE_PAGE_LIMIT_EXCEEDED", detail: "Archive page is too large")
        }
        var bytes = Data(count: Int(size))
        var written = 0
        var error = ermao_archive_error()
        let success = bytes.withUnsafeMutableBytes { buffer in
            ermao_archive_read_page(handle, index, buffer.baseAddress, buffer.count, &written, &error)
        }
        guard success == 1, written == bytes.count else { throw Self.failure(error) }
        return bytes
    }

    func close() {
        lock.lock()
        defer { lock.unlock() }
        guard let handle else { return }
        self.handle = nil
        ermao_archive_close(handle)
    }

    static var version: String { String(cString: ermao_archive_version()) }

    private static func failure(_ error: ermao_archive_error) -> IosArchiveCoreFailure {
        var codeBytes = error.code
        var messageBytes = error.message
        let codeCapacity = MemoryLayout.size(ofValue: codeBytes)
        let messageCapacity = MemoryLayout.size(ofValue: messageBytes)
        let code = withUnsafePointer(to: &codeBytes) { pointer in
            pointer.withMemoryRebound(to: CChar.self, capacity: codeCapacity) {
                String(cString: $0)
            }
        }
        let detail = withUnsafePointer(to: &messageBytes) { pointer in
            pointer.withMemoryRebound(to: CChar.self, capacity: messageCapacity) {
                String(cString: $0)
            }
        }
        return IosArchiveCoreFailure(
            stableCode: code.isEmpty ? "ARCHIVE_ERROR" : code,
            detail: detail.isEmpty ? "Archive operation failed" : detail
        )
    }
}
