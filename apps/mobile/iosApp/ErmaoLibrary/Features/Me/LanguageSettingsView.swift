import SwiftUI

struct LanguageSettingsView: View {
    @ObservedObject var viewModel: SettingsViewModel

    @Environment(\.appTheme) private var theme
    @State private var pendingLocale: SettingsLocale?

    var body: some View {
        SettingsScreen("settings.language.title") {
            Section {
                ForEach(SettingsLocale.allCases) { locale in
                    Button {
                        pendingLocale = locale
                        Task {
                            _ = await viewModel.updateLocale(locale)
                            pendingLocale = nil
                        }
                    } label: {
                        HStack(spacing: .space1Half) {
                            Text(LocalizedStringKey(locale.titleKey))
                                .foregroundStyle(theme.textPrimary)
                            Spacer(minLength: .space1)
                            if viewModel.snapshot.locale == locale {
                                Image(systemName: "checkmark")
                                    .foregroundStyle(theme.brandAccent)
                                    .accessibilityHidden(true)
                            }
                            if pendingLocale == locale && viewModel.isWorking(.updatingLocale) {
                                ProgressView()
                                    .accessibilityLabel(Text("common.loading"))
                            }
                        }
                        .frame(minHeight: SettingsMetrics.rowContentMinimumHeight)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .listRowInsets(SettingsMetrics.rowInsets)
                    .disabled(viewModel.isBusy || viewModel.snapshot.locale == locale)
                    .accessibilityValue(
                        viewModel.snapshot.locale == locale
                            ? Text("common.selected")
                            : Text("")
                    )
                }
            } footer: {
                Text("settings.language.footer")
            }
        }
        .settingsAlert(viewModel: viewModel)
    }
}
