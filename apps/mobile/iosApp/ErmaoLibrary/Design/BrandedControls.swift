import SwiftUI

struct PrimaryActionButton: View {
    let title: LocalizedStringKey
    let systemImage: String?
    let isWorking: Bool
    let isDisabled: Bool
    let action: () -> Void

    @Environment(\.appTheme) private var theme

    init(
        _ title: LocalizedStringKey,
        systemImage: String? = nil,
        isWorking: Bool = false,
        isDisabled: Bool = false,
        action: @escaping () -> Void
    ) {
        self.title = title
        self.systemImage = systemImage
        self.isWorking = isWorking
        self.isDisabled = isDisabled
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            ZStack {
                Group {
                    if let systemImage {
                        Label(title, systemImage: systemImage)
                    } else {
                        Text(title)
                    }
                }
                .appTextStyle(.button)
                .opacity(isWorking ? 0 : 1)
                if isWorking {
                    ProgressView()
                        .tint(theme.onAction)
                        .accessibilityLabel(Text("common.loading"))
                }
            }
            .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget)
            .contentShape(Rectangle())
        }
        .buttonStyle(.borderedProminent)
        .buttonBorderShape(
            .roundedRectangle(radius: CGFloat(GeneratedDesignTokens.Radii.control))
        )
        .tint(theme.actionAccent)
        .foregroundStyle(theme.onAction)
        .disabled(isDisabled || isWorking)
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
