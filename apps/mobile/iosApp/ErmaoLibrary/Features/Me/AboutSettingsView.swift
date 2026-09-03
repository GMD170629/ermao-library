import SwiftUI

struct AboutSettingsView: View {
    @ObservedObject var viewModel: SettingsViewModel

    @Environment(\.appTheme) private var theme

    var body: some View {
        SettingsScreen("settings.about.title") {
            SettingsSection("settings.about.app.section") {
                SettingsValueRow("settings.about.version", value: viewModel.snapshot.app.version)
                SettingsValueRow("settings.about.build", value: viewModel.snapshot.app.build)
            }

            SettingsSection("settings.about.server.section") {
                SettingsValueRow("settings.about.serverName", value: viewModel.snapshot.server.displayName)
                SettingsFieldRow("settings.about.serverVersion") {
                    if viewModel.serverVersionState == .loading {
                        ProgressView()
                            .accessibilityLabel(Text("settings.about.serverVersion.loading"))
                    } else if let version = viewModel.snapshot.server.version {
                        Text(version)
                            .foregroundStyle(theme.textSecondary)
                            .textSelection(.enabled)
                    } else {
                        VStack(alignment: .trailing, spacing: .spaceHalf) {
                            Text("settings.about.unavailable")
                                .foregroundStyle(theme.textTertiary)
                            Button("common.retry") {
                                Task { await viewModel.loadServerVersionIfNeeded(force: true) }
                            }
                            .buttonStyle(.plain)
                            .foregroundStyle(theme.actionAccent)
                            .frame(minHeight: .iosMinimumTouchTarget)
                            .accessibilityHint(Text("settings.about.serverVersion.retry.hint"))
                        }
                    }
                }
            }
        }
        .settingsAlert(viewModel: viewModel)
        .task { await viewModel.loadServerVersionIfNeeded() }
    }
}
