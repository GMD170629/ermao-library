import SwiftUI

struct TLSRiskView: View {
    @ObservedObject var store: SessionStore
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appTheme) private var theme

    @State private var isShowingConfirmation = false

    var body: some View {
        ScrollView {
            VStack(spacing: .space3) {
                Image(systemName: "exclamationmark.shield")
                    .font(.system(.largeTitle, design: .default, weight: .semibold))
                    .foregroundStyle(.orange)
                    .accessibilityHidden(true)

                if let profile = store.snapshot.profile {
                    ServerIdentityView(profile: profile)
                } else {
                    VStack(spacing: .spaceHalf) {
                        Text(store.serverDisplayName)
                            .appTextStyle(.headline)
                        Text(store.serverBaseURL)
                            .appTextStyle(.label)
                            .foregroundStyle(theme.textSecondary)
                    }
                }

                VStack(spacing: .space1Half) {
                    Text("server.tls.risk.title")
                        .appTextStyle(.title)
                        .multilineTextAlignment(.center)
                    Text("server.tls.risk.message")
                        .appTextStyle(.body)
                        .foregroundStyle(theme.textSecondary)
                        .multilineTextAlignment(.center)
                    Text("server.tls.risk.guidance")
                        .appTextStyle(.body)
                        .foregroundStyle(theme.textSecondary)
                        .multilineTextAlignment(.center)
                }

                Spacer(minLength: .space4)

                Button("server.tls.edit.action") {
                    store.dismissInfrastructureError()
                    dismiss()
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .frame(maxWidth: .infinity)

                Button("server.tls.ignore.action", role: .destructive) {
                    isShowingConfirmation = true
                }
                .frame(minHeight: .iosMinimumTouchTarget)
            }
            .frame(maxWidth: 520)
            .padding(.horizontal, .space2)
            .padding(.vertical, .space4)
            .frame(maxWidth: .infinity)
        }
        .navigationTitle("server.tls.navigationTitle")
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog(
            "server.tls.confirm.title",
            isPresented: $isShowingConfirmation,
            titleVisibility: .visible
        ) {
            Button("server.tls.ignore.action", role: .destructive) {
                store.acceptInsecureTLS()
            }
            Button("common.cancel", role: .cancel) {}
        } message: {
            Text(confirmationMessage)
        }
        .appCanvas()
    }

    private var confirmationMessage: String {
        String(
            format: String(localized: "server.tls.confirm.message.format"),
            locale: .current,
            store.serverDisplayName
        )
    }
}
