import SwiftUI

struct PrimaryActionButton: View {
    let title: LocalizedStringKey
    let isWorking: Bool
    let isDisabled: Bool
    let action: () -> Void

    @Environment(\.appTheme) private var theme

    init(
        _ title: LocalizedStringKey,
        isWorking: Bool = false,
        isDisabled: Bool = false,
        action: @escaping () -> Void
    ) {
        self.title = title
        self.isWorking = isWorking
        self.isDisabled = isDisabled
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            ZStack {
                Text(title)
                    .appTextStyle(.button)
                    .opacity(isWorking ? 0 : 1)
                if isWorking {
                    ProgressView()
                        .tint(theme.onAction)
                        .accessibilityLabel(Text("common.loading"))
                }
            }
            .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget)
        }
        .buttonStyle(.plain)
        .foregroundStyle(theme.onAction)
        .background(
            theme.actionAccent,
            in: RoundedRectangle(cornerRadius: CGFloat(GeneratedDesignTokens.Radii.control))
        )
        .contentShape(Rectangle())
        .disabled(isDisabled || isWorking)
        .opacity(isDisabled ? 0.5 : 1)
        .accessibilityAddTraits(.isButton)
    }
}

struct ServerIdentityView: View {
    let profile: RuntimeServerProfile

    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: .space1Half) {
            Image(systemName: "server.rack")
                .font(.title2)
                .foregroundStyle(theme.textSecondary)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: .spaceHalf) {
                Text(profile.displayName)
                    .appTextStyle(.headline)
                Text(displayHost)
                    .appTextStyle(.label)
                    .foregroundStyle(theme.textSecondary)
                    .textSelection(.enabled)
            }
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(Text(accessibilityDescription))
    }

    private var displayHost: String {
        guard let url = URL(string: profile.baseURL), let host = url.host else {
            return profile.baseURL
        }
        let path = url.path == "/" ? "" : url.path
        return host + path
    }

    private var accessibilityDescription: String {
        String(
            format: String(localized: "server.identity.accessibility.format"),
            locale: .current,
            profile.displayName,
            displayHost
        )
    }
}
