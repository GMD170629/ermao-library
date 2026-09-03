import Foundation

@MainActor
final class AdministrativeSettingsStore: ObservableObject {
    @Published private(set) var summary: AdministrativeLoadState<AdministrativeManagementSummary> = .idle
    @Published private(set) var operationInFlight: String?
    @Published private(set) var notice: AdministrativeNotice?
    @Published private(set) var directorySelection: AdministrativeDirectorySelection?

    let client: any AdministrativeSettingsClient
    let permissions: AdministrativePermission
    @Published private(set) var copy: AdministrativeCopyCatalog
    private let onUnauthorized: @MainActor @Sendable () -> Void
    private var generations: [String: Int] = [:]

    init(
        client: any AdministrativeSettingsClient,
        permissions: AdministrativePermission,
        locale: AdministrativeSettingsLocale,
        onUnauthorized: @escaping @MainActor @Sendable () -> Void
    ) {
        self.client = client
        self.permissions = permissions
        copy = AdministrativeCopyCatalog(locale: locale)
        self.onUnauthorized = onUnauthorized
    }

    func updateLocale(_ locale: AdministrativeSettingsLocale) {
        guard copy.locale != locale else { return }
        copy = AdministrativeCopyCatalog(locale: locale)
        notice = nil
    }

    func loadSummary(force: Bool = false) async {
        if !force, case .loaded = summary { return }
        let request = beginRequest(scope: "summary")
        summary = .loading
        do {
            let value = try await client.loadManagementSummary()
            guard isCurrent(request, scope: "summary") else { return }
            summary = .loaded(value)
        } catch is CancellationError {
            return
        } catch {
            guard isCurrent(request, scope: "summary") else { return }
            let failure = map(error)
            summary = .failed(failure)
            handle(failure)
        }
    }

    func perform(
        id: String,
        success: AdministrativeCopyKey = .saved,
        operation: @escaping @Sendable () async throws -> Void
    ) async -> Bool {
        let result: AdministrativeOperationResult<Void> = await performValue(id: id, success: success) {
            try await operation()
        }
        if case .success = result { return true }
        return false
    }

    func performValue<Value: Sendable>(
        id: String,
        success: AdministrativeCopyKey = .saved,
        operation: @escaping @Sendable () async throws -> Value
    ) async -> AdministrativeOperationResult<Value> {
        guard operationInFlight == nil else { return .cancelled }
        let request = beginRequest(scope: "operation")
        operationInFlight = id
        defer {
            if isCurrent(request, scope: "operation") { operationInFlight = nil }
        }
        do {
            let value = try await operation()
            guard isCurrent(request, scope: "operation") else { return .cancelled }
            notice = AdministrativeNotice(style: .success, message: copy[success])
            return .success(value)
        } catch is CancellationError {
            return .cancelled
        } catch {
            guard isCurrent(request, scope: "operation") else { return .cancelled }
            handle(map(error))
            return .failed
        }
    }

    func load<Value: Equatable & Sendable>(
        scope: String = "load",
        operation: @escaping @Sendable () async throws -> Value
    ) async -> AdministrativeLoadState<Value> {
        let request = beginRequest(scope: scope)
        do {
            let value = try await operation()
            guard isCurrent(request, scope: scope) else { return .idle }
            return .loaded(value)
        } catch is CancellationError {
            return .idle
        } catch {
            guard isCurrent(request, scope: scope) else { return .idle }
            let failure = map(error)
            handle(failure)
            return .failed(failure)
        }
    }

    func loadValue<Value: Sendable>(
        scope: String = "load",
        operation: @escaping @Sendable () async throws -> Value
    ) async -> Value? {
        let request = beginRequest(scope: scope)
        do {
            let value = try await operation()
            guard isCurrent(request, scope: scope) else { return nil }
            return value
        } catch is CancellationError {
            return nil
        } catch {
            guard isCurrent(request, scope: scope) else { return nil }
            handle(map(error))
            return nil
        }
    }

    func replaceNotice(_ notice: AdministrativeNotice?) {
        self.notice = notice
    }

    func cancelPendingRequests() {
        for scope in generations.keys { generations[scope, default: 0] += 1 }
        operationInFlight = nil
        Task { try? await client.invalidatePendingResponses() }
    }

    func selectServerDirectory(_ path: String, for purpose: ServerDirectoryPurpose) {
        directorySelection = AdministrativeDirectorySelection(purpose: purpose, path: path)
    }

    func consumeServerDirectorySelection(for purpose: ServerDirectoryPurpose) -> String? {
        guard directorySelection?.purpose == purpose else { return nil }
        defer { directorySelection = nil }
        return directorySelection?.path
    }

    func failureMessage(_ failure: AdministrativeFailure) -> String {
        switch failure.kind {
        case .validation: copy[.invalidInput]
        case .unauthorized: copy[.authorizationRequired]
        case .forbidden: copy[.permissionDenied]
        case .conflict: copy[.conflict]
        case .unavailable: copy[.temporarilyUnavailable]
        default: copy[.requestFailed]
        }
    }

    private func beginRequest(scope: String) -> Int {
        generations[scope, default: 0] += 1
        return generations[scope, default: 0]
    }

    private func isCurrent(_ request: Int, scope: String) -> Bool {
        request == generations[scope, default: 0] && !Task.isCancelled
    }

    private func map(_ error: Error) -> AdministrativeFailure {
        error as? AdministrativeFailure
            ?? AdministrativeFailure(kind: .transport, code: "transport")
    }

    private func handle(_ failure: AdministrativeFailure) {
        if failure.kind == .unauthorized {
            onUnauthorized()
        }
        notice = AdministrativeNotice(style: .error, message: failureMessage(failure))
    }
}

enum AdministrativeOperationResult<Value: Sendable>: Sendable {
    case success(Value)
    case failed
    case cancelled
}

struct AdministrativeNotice: Identifiable, Equatable, Sendable {
    enum Style: Equatable, Sendable { case success, error, information }
    let id = UUID()
    let style: Style
    let message: String

    static func == (lhs: AdministrativeNotice, rhs: AdministrativeNotice) -> Bool {
        lhs.style == rhs.style && lhs.message == rhs.message
    }
}
