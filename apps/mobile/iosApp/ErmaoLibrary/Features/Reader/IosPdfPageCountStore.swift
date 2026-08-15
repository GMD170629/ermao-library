import Foundation

/// Keeps the server-authoritative page count available for verified offline artifacts.
final class IosPdfPageCountStore {
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func save(pageCount: Int, sourceID: String) {
        guard pageCount > 0 else { return }
        defaults.set(pageCount, forKey: key(sourceID: sourceID))
    }

    func load(sourceID: String) -> Int? {
        let value = defaults.integer(forKey: key(sourceID: sourceID))
        return value > 0 ? value : nil
    }

    private func key(sourceID: String) -> String {
        "reader.pdf.page-count.\(Data(sourceID.utf8).base64EncodedString())"
    }
}
