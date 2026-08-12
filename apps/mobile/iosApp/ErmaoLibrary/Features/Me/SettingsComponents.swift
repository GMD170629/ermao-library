import SwiftUI
import UIKit

struct SettingsAvatarView: View {
    let data: Data?
    let displayName: String
    var size: CGFloat = 64

    @Environment(\.appTheme) private var theme

    var body: some View {
        Group {
            if let data, let image = UIImage(data: data) {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                Text(initials)
                    .appTextStyle(.headline)
                    .foregroundStyle(theme.actionAccent)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(theme.accentSoft)
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
        .overlay(Circle().stroke(theme.divider, lineWidth: 1))
        .accessibilityHidden(true)
    }

    private var initials: String {
        let trimmed = displayName.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.first.map { String($0).uppercased() } ?? "?"
    }
}

struct SettingsRowLabel: View {
    let titleKey: String
    let systemImage: String

    @Environment(\.appTheme) private var theme

    var body: some View {
        Label {
            Text(LocalizedStringKey(titleKey))
                .foregroundStyle(theme.textPrimary)
        } icon: {
            Image(systemName: systemImage)
                .foregroundStyle(theme.textSecondary)
        }
    }
}

private struct SettingsListSurfaceModifier: ViewModifier {
    @Environment(\.appTheme) private var theme

    func body(content: Content) -> some View {
        content
            .scrollContentBackground(.hidden)
            .background(theme.canvas)
            .tint(theme.actionAccent)
    }
}

private struct SettingsAlertModifier: ViewModifier {
    @ObservedObject var viewModel: SettingsViewModel

    func body(content: Content) -> some View {
        content.alert(item: alertBinding) { alert in
            Alert(
                title: Text(LocalizedStringKey(alert.titleKey)),
                message: Text(LocalizedStringKey(alert.messageKey)),
                dismissButton: .default(Text("common.ok")) {
                    viewModel.dismissAlert()
                }
            )
        }
    }

    private var alertBinding: Binding<SettingsAlert?> {
        Binding(
            get: { viewModel.alert },
            set: { value in
                if value == nil { viewModel.dismissAlert() }
            }
        )
    }
}

extension View {
    func settingsListSurface() -> some View {
        modifier(SettingsListSurfaceModifier())
    }

    func settingsAlert(viewModel: SettingsViewModel) -> some View {
        modifier(SettingsAlertModifier(viewModel: viewModel))
    }
}
