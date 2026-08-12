import SwiftUI

struct LanguageSettingsView: View {
    @ObservedObject var viewModel: SettingsViewModel

    @Environment(\.appTheme) private var theme

    var body: some View {
        List {
            Section {
                ForEach(SettingsLocale.allCases) { locale in
                    Button {
                        Task { await viewModel.updateLocale(locale) }
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
                            if viewModel.isWorking(.updatingLocale) {
                                ProgressView()
                                    .accessibilityLabel(Text("common.loading"))
                            }
                        }
                        .frame(minHeight: .iosMinimumTouchTarget)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(viewModel.isBusy && !viewModel.isWorking(.updatingLocale))
                    .accessibilityValue(
                        viewModel.snapshot.locale == locale
                            ? Text("common.selected")
                            : Text("")
                    )
                }
            } footer: {
                Text("settings.language.footer")
            }
            .listRowBackground(theme.surface)
        }
        .listStyle(.insetGrouped)
        .settingsListSurface()
        .settingsAlert(viewModel: viewModel)
        .navigationTitle("settings.language.title")
        .navigationBarTitleDisplayMode(.inline)
    }
}
