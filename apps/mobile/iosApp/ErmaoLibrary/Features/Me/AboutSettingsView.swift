import SwiftUI

struct AboutSettingsView: View {
    @ObservedObject var viewModel: SettingsViewModel

    @Environment(\.appTheme) private var theme

    var body: some View {
        List {
            Section("settings.about.app.section") {
                LabeledContent("settings.about.version") {
                    Text(viewModel.snapshot.app.version)
                        .foregroundStyle(theme.textSecondary)
                        .textSelection(.enabled)
                }
                LabeledContent("settings.about.build") {
                    Text(viewModel.snapshot.app.build)
                        .foregroundStyle(theme.textSecondary)
                        .textSelection(.enabled)
                }
            }
            .listRowBackground(theme.surface)

            Section("settings.about.server.section") {
                LabeledContent("settings.about.serverName") {
                    Text(viewModel.snapshot.server.displayName)
                        .foregroundStyle(theme.textSecondary)
                        .multilineTextAlignment(.trailing)
                        .textSelection(.enabled)
                }
                LabeledContent("settings.about.serverVersion") {
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
            .listRowBackground(theme.surface)
        }
        .listStyle(.insetGrouped)
        .settingsListSurface()
        .settingsAlert(viewModel: viewModel)
        .navigationTitle("settings.about.title")
        .navigationBarTitleDisplayMode(.inline)
        .task { await viewModel.loadServerVersionIfNeeded() }
    }
}
