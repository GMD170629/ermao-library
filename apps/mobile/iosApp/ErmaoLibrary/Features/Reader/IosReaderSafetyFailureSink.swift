import Foundation
@preconcurrency import ErmaoShared

/// Keeps the first typed safety failure attached to one Readium opening, including lazy reads.
/// Readium resources can be consumed on background executors, so the sink is explicitly locked.
final class IosReaderSafetyFailureSink: @unchecked Sendable {
    private let lock = NSLock()
    private var firstFailure: Error?
    private var disposed = false

    func record(
        _ error: Error,
        resourceRole: IosEpubResourceRole = .optionalResource
    ) {
        guard let securityError = error as? IosPublicationSecurityError else {
            return
        }
        guard case .rejected = securityError else { return }
        lock.lock()
        defer { lock.unlock() }
        guard !disposed else { return }
        apply(securityError, resourceRole: resourceRole)
    }

    private func apply(_ error: IosPublicationSecurityError, resourceRole: IosEpubResourceRole) {
        guard case let .rejected(ruleId, errorCode) = error else { return }
        guard ErmaoShared.PublicKt.readerSafetyRuleActionOrNull(ruleId: ruleId) != nil else {
            if firstFailure == nil { firstFailure = error }
            return
        }
        let implementationCodes = [
            ErmaoShared.PublicKt.readerSafetyEngineAlgorithmUnsupported(ruleId: ruleId).errorCode,
            ErmaoShared.PublicKt.readerSafetyPlatformAlgorithmUnsupported(ruleId: ruleId).errorCode,
        ]
        if implementationCodes.contains(errorCode) {
            if firstFailure == nil { firstFailure = error }
            return
        }
        // Resolve the action for the actual resource role. A rule whose publication
        // default is REJECT can intentionally become BLOCK_RESOURCE for an optional
        // asset; using the static rule action here would poison the whole opening.
        let contextualAction = ErmaoShared.PublicKt.readerSafetyEvaluateRuleDecision(
            format: "EPUB",
            resourceRole: resourceRole.rawValue,
            ruleId: ruleId,
            enforcementAvailable: true,
            canIsolate: resourceRole == .optionalResource
        ).action
        guard contextualAction != "BLOCK_RESOURCE" else { return }
        if firstFailure == nil { firstFailure = error }
    }

    func throwIfPresent() throws {
        lock.lock()
        let failure = firstFailure
        lock.unlock()
        if let failure { throw failure }
    }

    func clear() {
        lock.lock()
        disposed = true
        firstFailure = nil
        lock.unlock()
    }
}
