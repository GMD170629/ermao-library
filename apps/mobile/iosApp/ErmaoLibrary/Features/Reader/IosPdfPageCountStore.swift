import Foundation

/// Keeps the server-authoritative page count available for verified offline artifacts.
final class IosPdfPageCountStore {
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func save(pageCount: Int, resourceID: String) {
        guard pageCount > 0 else { return }
        defaults.set(pageCount, forKey: key(resourceID: resourceID))
    }

    func load(resourceID: String) -> Int? {
        let value = defaults.integer(forKey: key(resourceID: resourceID))
        return value > 0 ? value : nil
    }

    private func key(resourceID: String) -> String {
        "reader.pdf.page-count.\(Data(resourceID.utf8).base64EncodedString())"
    }
}
