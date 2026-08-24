import SwiftUI

struct ServerCompatibilityCopy: Equatable {
    let titleKey: String
    let messageKey: String

    static func resolve(reasonCode: String?) -> ServerCompatibilityCopy {
        switch reasonCode {
        case "CLIENT_UPDATE_REQUIRED":
            ServerCompatibilityCopy(
                titleKey: "server.compatibility.appUpdate.title",
                messageKey: "server.compatibility.appUpdate.message"
            )
        case "UNSUPPORTED_PROTOCOL_VERSION", "UNSUPPORTED_READER_SCHEMA",
             "UNSUPPORTED_LIBRARY_SCHEMA", "COOKIE_SESSION_REQUIRED", "READER_V4_REQUIRED",
             "BOOK_RESOURCE_ASSET_REQUIRED", "MOBILE_DOWNLOADS_REQUIRED":
            ServerCompatibilityCopy(
                titleKey: "server.compatibility.serverUpdate.title",
                messageKey: "server.compatibility.serverUpdate.message"
            )
        default:
            ServerCompatibilityCopy(
                titleKey: "server.compatibility.invalidResponse.title",
                messageKey: "server.compatibility.invalidResponse.message"
            )
        }
    }
}

struct IncompatibleServerView: View {
    @ObservedObject var store: SessionStore
    let chooseAnotherServer: () -> Void
    @Environment(\.appTheme) private var theme

    private var copy: ServerCompatibilityCopy {
        .resolve(reasonCode: store.snapshot.reasonCode)
    }

    var body: some View {
        ScrollView {
            VStack(spacing: .space3) {
                Spacer(minLength: .space4)
                Image(systemName: "exclamationmark.shield")
                    .font(.system(.largeTitle, design: .default, weight: .semibold))
                    .foregroundStyle(.yellow)
                    .accessibilityHidden(true)
                Text(LocalizedStringKey(copy.titleKey))
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
                Text(LocalizedStringKey(copy.messageKey))
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
