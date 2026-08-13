import Foundation

/// Keeps the server-authoritative page count available for verified offline artifacts.
/// The fingerprint is part of the key, so replacing a PDF can never inherit stale bounds.
final class IosPdfPageCountStore {
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func save(pageCount: Int, sourceID: String, fingerprint: IosContentFingerprint) {
        guard pageCount > 0 else { return }
        defaults.set(pageCount, forKey: key(sourceID: sourceID, fingerprint: fingerprint))
    }

    func load(sourceID: String, fingerprint: IosContentFingerprint) -> Int? {
        let value = defaults.integer(forKey: key(sourceID: sourceID, fingerprint: fingerprint))
        return value > 0 ? value : nil
    }

    private func key(sourceID: String, fingerprint: IosContentFingerprint) -> String {
        let identity = "\(sourceID)|\(fingerprint.originalFileHash)|\(fingerprint.parserVersion)|\(fingerprint.normalizationVersion)"
        return "reader.pdf.page-count.\(Data(identity.utf8).base64EncodedString())"
    }
}
