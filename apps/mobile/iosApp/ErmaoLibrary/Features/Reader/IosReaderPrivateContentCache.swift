import Foundation

/// Coordinates destructive Reader-local cleanup for one authenticated
/// namespace. Every store below is either account-prefixed or explicitly
/// bound to the full namespace; there is intentionally no global clearAll.
struct IosReaderPrivateContentCache: PrivateContentCacheClearing, Sendable {
    private let managedPublications: IosManagedPublicationStore?

    init() {
        managedPublications = try? IosManagedPublicationStore()
    }

    func removeNamespace(_ namespace: String) async throws {
        try await managedPublications?.removeNamespace(namespace)
        try IosReaderLocalDatabase.purgeNamespace(namespace)
        try IosPdfRangeCache.clearNamespace(namespace)

        guard let (serverIdentity, userID) = accountComponents(namespace) else {
            throw IosReaderFailure(code: .persistenceFailed)
        }
        IosReaderNavigationCache().clear(
            serverIdentity: serverIdentity,
            userID: userID
        )
        IosReaderPreferencesStore.clearNamespace(
            serverIdentity: serverIdentity,
            userID: userID
        )
        IosReaderBookmarkStore.clearNamespace(
            serverIdentity: serverIdentity,
            userID: userID
        )
    }

    private func accountComponents(_ namespace: String) -> (String, String)? {
        let parts = namespace.split(separator: "|", maxSplits: 2, omittingEmptySubsequences: false)
        guard parts.count >= 2,
              !parts[0].isEmpty,
              !parts[1].isEmpty else { return nil }
        return (String(parts[0]), String(parts[1]))
    }
}
