import CryptoKit
import Foundation

@MainActor
final class ReaderPOCStore: ObservableObject {
    enum LoadState {
        case idle
        case loading
        case loaded(LoadedFixture)
        case failed(String)
    }

    struct LoadedFixture {
        let descriptor: FixtureDescriptor
        let result: MobiPublicationResult
        let publicationBuildMilliseconds: Double
        let performanceGrade: TechnicalGrade
        let fingerprint: LocatorPublicationFingerprint
    }

    @Published private(set) var selectedFixtureID = FixtureCatalog.all.first?.id
    @Published private(set) var state: LoadState = .idle
    @Published private(set) var eventLog: [String] = []

    private let factory: MobiPublicationFactory

    init(factory: MobiPublicationFactory = MobiPublicationFactory()) {
        self.factory = factory
        log("libmobi \(NativeMobiExtractor.libmobiVersion); Readium 3.11.0")
    }

    func select(_ descriptor: FixtureDescriptor) {
        selectedFixtureID = descriptor.id
        state = .idle
    }

    func load(_ descriptor: FixtureDescriptor) async {
        guard let url = descriptor.bundledURL() else {
            state = .failed(String(format: String(localized: "error.fixtureMissing"), descriptor.filename))
            log("Missing fixture: \(descriptor.filename)")
            return
        }

        state = .loading
        log("Opening \(descriptor.filename)")
        let clock = ContinuousClock()
        let started = clock.now
        do {
            let sourceData = try Data(contentsOf: url, options: .mappedIfSafe)
            let sourceHash = SHA256.hash(data: sourceData).map { String(format: "%02x", $0) }.joined()
            let result = try await factory.open(url)
            let elapsed = started.duration(to: clock.now).milliseconds
            let threshold = descriptor.isLongChapter ? 8_000.0 : 2_000.0
            let grade: TechnicalGrade = elapsed <= threshold ? .pass : .degraded
            state = .loaded(LoadedFixture(
                descriptor: descriptor,
                result: result,
                publicationBuildMilliseconds: elapsed,
                performanceGrade: grade,
                fingerprint: LocatorPublicationFingerprint(
                    originalFileHash: sourceHash,
                    parser: NativeMobiExtractor.libmobiVersion,
                    normalization: NativeMobiExtractor.normalizationVersion
                )
            ))
            log("Built Publication in \(elapsed.formatted(.number.precision(.fractionLength(1)))) ms")
            log("Verified \(result.preflight.resourceCount) resources and \(result.preflight.verifiedReferenceCount) references")
            result.book.warnings.forEach { log("Warning [\($0.code.rawValue)]: \($0.message)") }
        } catch {
            state = .failed(error.localizedDescription)
            log("Failure: \(error.localizedDescription)")
        }
    }

    func log(_ message: String) {
        let timestamp = Date.now.formatted(date: .omitted, time: .standard)
        eventLog.append("[\(timestamp)] \(message)")
        if eventLog.count > 300 {
            eventLog.removeFirst(eventLog.count - 300)
        }
    }
}

enum TechnicalGrade: String, Codable, Sendable {
    case pass
    case degraded
    case fail
    case awaitingEvidence
}

private extension Duration {
    var milliseconds: Double {
        let components = self.components
        return Double(components.seconds) * 1_000 + Double(components.attoseconds) / 1e15
    }
}
