import SwiftUI

struct IncompatibleServerView: View {
    @ObservedObject var store: SessionStore
    let chooseAnotherServer: () -> Void
    @Environment(\.appTheme) private var theme

    var body: some View {
        ScrollView {
            VStack(spacing: .space3) {
                Spacer(minLength: .space4)
                Image(systemName: "exclamationmark.shield")
                    .font(.system(.largeTitle, design: .default, weight: .semibold))
                    .foregroundStyle(.yellow)
                    .accessibilityHidden(true)
                Text("server.incompatible.title")
                    .appTextStyle(.title)
                    .multilineTextAlignment(.center)
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
                Text("server.incompatible.message")
                    .appTextStyle(.body)
                    .foregroundStyle(theme.textSecondary)
                    .multilineTextAlignment(.center)
                Spacer(minLength: .space4)
                PrimaryActionButton("server.other.action") {
                    store.dismissInfrastructureError()
                    chooseAnotherServer()
                }
                Button("server.retry.action") {
                    store.retry()
                }
                .frame(minHeight: .iosMinimumTouchTarget)
                Text("server.incompatible.footer")
                    .appTextStyle(.caption)
                    .foregroundStyle(theme.textTertiary)
                    .multilineTextAlignment(.center)
            }
            .frame(maxWidth: 520)
            .padding(.horizontal, .space2)
            .padding(.bottom, .space4)
            .frame(maxWidth: .infinity)
        }
        .navigationTitle("server.problem.navigationTitle")
        .navigationBarTitleDisplayMode(.inline)
        .navigationBarBackButtonHidden(true)
        .appCanvas()
    }
}
