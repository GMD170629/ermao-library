import SwiftUI
import UIKit

struct AddServerView: View {
    @ObservedObject var store: SessionStore
    @Environment(\.appTheme) private var theme

    @FocusState private var focusedField: Field?

    private enum Field {
        case displayName
        case baseURL
    }

    private var isChecking: Bool {
        store.snapshot.phase == .checkingServer
    }

    private var isEditing: Bool { store.editingProfileID != nil }

    private var isInvalidAddress: Bool {
        store.snapshot.phase == .serverConnectionFailed &&
            store.snapshot.reasonCode == "INVALID_ADDRESS"
    }

    var body: some View {
        Form {
            Section {
                TextField("server.name.placeholder", text: $store.serverDisplayName)
                    .textContentType(.organizationName)
                    .focused($focusedField, equals: .displayName)
                    .submitLabel(.next)
                    .onSubmit { focusedField = .baseURL }
                    .accessibilityLabel(Text("server.name.label"))
                TextField("server.url.placeholder", text: $store.serverBaseURL)
                    .textContentType(.URL)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                    .autocorrectionDisabled()
                    .focused($focusedField, equals: .baseURL)
                    .submitLabel(.go)
                    .onSubmit(connectIfValid)
                    .accessibilityLabel(Text("server.url.label"))
                if isInvalidAddress {
                    Label("server.url.invalid", systemImage: "exclamationmark.circle.fill")
                        .appTextStyle(.caption)
                        .foregroundStyle(.red)
                        .onAppear {
                            UIAccessibility.post(
                                notification: .announcement,
                                argument: String(localized: "server.url.invalid")
                            )
                        }
                }
            } header: {
                Text("server.add.form.header")
            } footer: {
                Text("server.url.footer")
            }

            Section {
                LabeledContent {
                    Text("server.tls.recommended")
                        .foregroundStyle(theme.textSecondary)
                } label: {
                    Label("server.tls.system", systemImage: "checkmark.shield")
                        .foregroundStyle(theme.textPrimary)
                }
                if store.snapshot.phase == .serverConnectionFailed && !isInvalidAddress {
                    ConnectionFailureInlineView()
                } else if store.operationErrorCode != nil {
                    Label("common.operationFailed", systemImage: "exclamationmark.triangle.fill")
                        .appTextStyle(.caption)
                        .foregroundStyle(.red)
                }
            }

            Section {
                PrimaryActionButton(
                    isEditing
                        ? "server.save.action"
                        : store.snapshot.phase == .serverConnectionFailed
                        ? "server.retry.action"
                        : "server.check.action",
                    isWorking: isChecking,
                    isDisabled: !isFormValid,
                    action: connectIfValid
                )
                .listRowInsets(EdgeInsets())
                .listRowBackground(Color.clear)
            } footer: {
                Text("server.check.footer")
                    .frame(maxWidth: .infinity)
                    .multilineTextAlignment(.center)
            }
        }
        .scrollContentBackground(.hidden)
        .background(theme.canvas)
        .navigationTitle(isEditing ? "server.edit.title" : "server.add.title")
        .navigationBarTitleDisplayMode(.inline)
        .disabled(isChecking)
    }

    private var isFormValid: Bool {
        !store.serverDisplayName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
            !store.serverBaseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func connectIfValid() {
        guard isFormValid, !isChecking else { return }
        focusedField = nil
        store.connectServer()
    }
}

private struct ConnectionFailureInlineView: View {
    @Environment(\.appTheme) private var theme

    var body: some View {
        Label {
            VStack(alignment: .leading, spacing: .spaceHalf) {
                Text("server.unavailable.title")
                    .appTextStyle(.headline)
                    .foregroundStyle(theme.textPrimary)
                Text("server.unavailable.message")
                    .appTextStyle(.caption)
                    .foregroundStyle(theme.textSecondary)
            }
        } icon: {
            Image(systemName: "wifi.exclamationmark")
                .foregroundStyle(.orange)
        }
        .accessibilityElement(children: .combine)
        .onAppear {
            UIAccessibility.post(
                notification: .announcement,
                argument: String(localized: "server.unavailable.message")
            )
        }
    }
}
