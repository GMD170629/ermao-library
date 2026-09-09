import SwiftUI
import UIKit
@preconcurrency import ErmaoShared

@MainActor
struct OperationFeedbackAction: Identifiable {
    enum Role {
        case normal
        case cancel
        case destructive
    }

    let id: String
    let title: LocalizedStringKey
    let role: Role
    let accessibilityIdentifier: String?
    let perform: @MainActor () -> Void

    init(
        id: String,
        title: LocalizedStringKey,
        role: Role = .normal,
        accessibilityIdentifier: String? = nil,
        perform: @escaping @MainActor () -> Void
    ) {
        self.id = id
        self.title = title
        self.role = role
        self.accessibilityIdentifier = accessibilityIdentifier
        self.perform = perform
    }
}

@MainActor
struct OperationFeedbackItem: Identifiable {
    let id: UUID
    let message: String
    let kind: ErmaoShared.OperationFeedbackKind
    let actions: [OperationFeedbackAction]
}

@MainActor
final class OperationFeedbackPresenter: ObservableObject {
    @Published private(set) var current: OperationFeedbackItem?

    private var timerTask: Task<Void, Never>?
    private var timeoutMillis: Int64?
    private var completion: (@MainActor () -> Void)?
    private let sleep: @Sendable (UInt64) async throws -> Void
    private let voiceOverRunning: @MainActor @Sendable () -> Bool

    private(set) var lastScheduledTimeoutMillis: Int64?

    init(
        sleep: @escaping @Sendable (UInt64) async throws -> Void = { nanoseconds in
            try await Task.sleep(nanoseconds: nanoseconds)
        },
        voiceOverRunning: @escaping @MainActor @Sendable () -> Bool = {
            UIAccessibility.isVoiceOverRunning
        }
    ) {
        self.sleep = sleep
        self.voiceOverRunning = voiceOverRunning
    }

    deinit { timerTask?.cancel() }

    @discardableResult
    func present(
        message: String,
        kind: ErmaoShared.OperationFeedbackKind,
        actions: [OperationFeedbackAction] = [],
        retainedTimeoutMillis: Int64 = 5_000,
        onDismiss: @escaping @MainActor () -> Void = {}
    ) -> UUID? {
        // A success with controls is an actionable outcome. Keep it in the
        // retained priority/timing lane so a Close or Retry control is never
        // given the one-second success timeout.
        let effectiveKind = actions.isEmpty || kind != .success ? kind : .action
        if let current,
           !ErmaoShared.OperationFeedbackPolicy.shared.canReplace(current: current.kind, incoming: effectiveKind) {
            onDismiss()
            return nil
        }

        clear()
        completion = onDismiss
        let id = UUID()
        current = OperationFeedbackItem(id: id, message: message, kind: effectiveKind, actions: actions)

        let extendedForVoiceOver = voiceOverRunning()
        if extendedForVoiceOver {
            UIAccessibility.post(notification: .announcement, argument: message)
        }

        let policyTimeout = ErmaoShared.OperationFeedbackPolicy.shared.timeoutMillis(
            kind: effectiveKind,
            retainedTimeoutMillis: retainedTimeoutMillis
        )
        let timeoutMillis = extendedForVoiceOver ? max(policyTimeout, 3_000) : policyTimeout
        self.timeoutMillis = timeoutMillis
        lastScheduledTimeoutMillis = timeoutMillis
        return id
    }

    /// Starts the expiration clock after the overlay has had time to finish its
    /// insertion transition. This keeps a success fully visible for the full
    /// policy duration before SwiftUI fades it out.
    func markVisible(id: UUID, entranceDurationMillis: Int64 = 180) {
        guard current?.id == id, let timeoutMillis else { return }
        cancelTimer()
        guard timeoutMillis > 0, timeoutMillis < Int64.max else { return }
        let entranceNanoseconds = nanoseconds(for: max(0, entranceDurationMillis))
        guard let timeoutNanoseconds = nanoseconds(for: timeoutMillis) else { return }
        let sleep = self.sleep
        timerTask = Task { @MainActor [weak self] in
            do {
                if entranceDurationMillis > 0, let entranceNanoseconds {
                    try await sleep(entranceNanoseconds)
                }
                try await sleep(timeoutNanoseconds)
            } catch {
                return
            }
            guard !Task.isCancelled else { return }
            self?.dismiss(id: id)
        }
    }

    func dismiss(id: UUID) {
        guard current?.id == id else { return }
        cancelTimer()
        timeoutMillis = nil
        let onDismiss = completion
        completion = nil
        current = nil
        onDismiss?()
    }

    func clear() {
        if let id = current?.id { dismiss(id: id) }
        else { cancelTimer() }
    }

    private func cancelTimer() {
        timerTask?.cancel()
        timerTask = nil
    }

    private func nanoseconds(for milliseconds: Int64) -> UInt64? {
        let (value, overflow) = UInt64(milliseconds).multipliedReportingOverflow(by: 1_000_000)
        return overflow ? nil : value
    }
}

struct OperationFeedbackOverlay: View {
    @ObservedObject var presenter: OperationFeedbackPresenter
    let clearsOnDisappear: Bool

    @Environment(\.appTheme) private var theme
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    init(presenter: OperationFeedbackPresenter, clearsOnDisappear: Bool = true) {
        self.presenter = presenter
        self.clearsOnDisappear = clearsOnDisappear
    }

    var body: some View {
        Group {
            if let feedback = presenter.current {
                feedbackView(feedback)
                    .transition(.opacity)
            }
        }
        .animation(
            reduceMotion ? nil : .easeInOut(duration: 0.18),
            value: presenter.current?.id
        )
        .task(id: presenter.current?.id) {
            guard let id = presenter.current?.id else { return }
            presenter.markVisible(
                id: id,
                entranceDurationMillis: reduceMotion ? 0 : 180
            )
        }
        .onDisappear {
            if clearsOnDisappear {
                presenter.clear()
            }
        }
    }

    private func feedbackView(_ feedback: OperationFeedbackItem) -> some View {
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: .space1))
            : AnyLayout(HStackLayout(alignment: .center, spacing: .space1))

        return layout {
            HStack(alignment: .firstTextBaseline, spacing: .space1) {
                Image(systemName: iconName(for: feedback.kind))
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(iconColor(for: feedback.kind))
                    .accessibilityHidden(true)
                Text(feedback.message)
                    .appTextStyle(.callout)
                    .foregroundStyle(theme.textPrimary)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if !feedback.actions.isEmpty {
                actionButtons(feedback.actions, for: feedback.id)
            }
        }
        .padding(.horizontal, .space2)
        .padding(.vertical, .space1Half)
        .background(theme.surface, in: Capsule())
        .overlay {
            Capsule().stroke(theme.divider.opacity(0.65), lineWidth: 1)
        }
        .shadow(color: Color.black.opacity(0.12), radius: 10, y: 4)
        .padding(.horizontal, .space2)
        .padding(.bottom, .space2)
        .frame(maxWidth: dynamicTypeSize.isAccessibilitySize ? .infinity : nil, alignment: .leading)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("operation.feedback")
    }

    private func actionButtons(
        _ actions: [OperationFeedbackAction],
        for feedbackID: UUID
    ) -> some View {
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: .spaceHalf))
            : AnyLayout(HStackLayout(spacing: .space1))

        return layout {
            ForEach(actions) { action in
                Button(role: buttonRole(for: action.role)) {
                    action.perform()
                    presenter.dismiss(id: feedbackID)
                } label: {
                    Text(action.title)
                        .appTextStyle(.label)
                        .foregroundStyle(theme.actionAccent)
                        .frame(minHeight: .iosMinimumTouchTarget)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.borderless)
                .accessibilityIdentifier(action.accessibilityIdentifier ?? "operation.feedback.action.\(action.id)")
            }
        }
    }

    private func buttonRole(for role: OperationFeedbackAction.Role) -> ButtonRole? {
        switch role {
        case .normal: nil
        case .cancel: .cancel
        case .destructive: .destructive
        }
    }

    private func iconName(for kind: ErmaoShared.OperationFeedbackKind) -> String {
        switch kind {
        case .success: "checkmark.circle"
        case .partialsuccess: "exclamationmark.circle"
        case .failure: "exclamationmark.triangle"
        case .action: "info.circle"
        default: "info.circle"
        }
    }

    private func iconColor(for kind: ErmaoShared.OperationFeedbackKind) -> Color {
        switch kind {
        case .success: theme.brandAccent
        case .partialsuccess: theme.actionAccent
        case .failure: .red
        case .action: theme.textSecondary
        default: theme.textSecondary
        }
    }
}
