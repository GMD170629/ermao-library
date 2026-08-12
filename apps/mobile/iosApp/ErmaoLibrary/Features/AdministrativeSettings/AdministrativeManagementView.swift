import SwiftUI

struct AdministrativeManagementView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme
    @Environment(\.administrativeNavigate) private var navigate

    var body: some View {
        List {
            if case let .loaded(summary) = store.summary {
                group(copy[.librarySection], rows: libraryRows(summary))
                group(copy[.organizeSection], rows: organizationRows(summary))
                group(copy[.serviceSection], rows: serviceRows(summary))
                group(copy[.systemSection], rows: systemRows(summary))
            } else if case let .failed(failure) = store.summary {
                Section {
                    AdministrativeEmptyView(title: copy[.requestFailed], systemImage: "exclamationmark.triangle", detail: store.failureMessage(failure), actionTitle: copy[.retry]) { Task { await store.loadSummary(force: true) } }
                }
                .listRowBackground(theme.surface)
            } else {
                Section {
                    HStack { Spacer(); ProgressView(copy[.loading]); Spacer() }
                        .frame(minHeight: 160)
                }
                .listRowBackground(theme.surface)
            }
        }
        .listStyle(.insetGrouped)
        .administrativeListSurface()
        .navigationTitle(copy[.managementTitle])
        .navigationBarTitleDisplayMode(.inline)
        .refreshable { await store.loadSummary(force: true) }
        .task { await store.loadSummary() }
        .onDisappear { store.cancelPendingRequests() }
        .administrativeNotice(store: store)
    }

    @ViewBuilder
    private func group(_ title: String, rows: [ManagementRow]) -> some View {
        if !rows.isEmpty {
            Section(title) {
                ForEach(rows) { row in
                    Button { navigate(row.route) } label: {
                        Label {
                            HStack {
                                Text(row.title)
                                Spacer(minLength: .space1)
                                if let value = row.value {
                                    Text(value).foregroundStyle(row.warning ? .red : theme.textSecondary)
                                        .multilineTextAlignment(.trailing)
                                }
                                if row.good { Circle().fill(.green).frame(width: 7, height: 7).accessibilityHidden(true) }
                                Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(theme.textSecondary)
                            }
                        } icon: {
                            Image(systemName: row.icon).foregroundStyle(theme.textSecondary)
                        }
                    }
                    .buttonStyle(.plain)
                    .frame(minHeight: .iosMinimumTouchTarget)
                }
            }
            .listRowBackground(theme.surface)
        }
    }

    private func libraryRows(_ summary: AdministrativeManagementSummary) -> [ManagementRow] {
        guard store.permissions.canManageSystem else { return [] }
        return [
            .init(copy[.librarySources], "folder", .librarySources, "\(summary.librarySourceCount) · \(summary.monitoredSourceCount)"),
            .init(copy[.importTasks], "arrow.down.to.line", .importTasks, summary.activeImportCount == 0 ? copy[.completed] : "\(summary.activeImportCount) \(copy[.active])"),
            .init(copy[.importPreferences], "slider.horizontal.3", .importPreferences, summary.automaticImportEnabled ? copy[.enabled] : copy[.disabled])
        ]
    }

    private func organizationRows(_ summary: AdministrativeManagementSummary) -> [ManagementRow] {
        guard store.permissions.canManageSystem else { return [] }
        return [
            .init(copy[.organizeQueue], "sparkles", .organizeQueue, "\(summary.pendingOrganizeCount) \(copy[.pending])"),
            .init(copy[.duplicateCategories], "square.3.layers.3d", .duplicateWorks, "\(summary.duplicateGroupCount)"),
            .init(copy[.metadataProviders], "person.text.rectangle", .metadataProviders, "\(summary.availableProviderCount)/\(summary.providerCount) \(copy[.available])")
        ]
    }

    private func serviceRows(_ summary: AdministrativeManagementSummary) -> [ManagementRow] {
        var rows: [ManagementRow] = [
            .init(copy[.emailKindle], "envelope", .emailAndKindle, summary.smtpEnabled ? copy[.enabled] : copy[.disabled]),
            .init(copy[.kindleQueue], "paperplane", .kindleQueue, summary.failedKindleCount > 0 ? "\(summary.failedKindleCount) \(copy[.failed])" : nil, warning: summary.failedKindleCount > 0)
        ]
        if store.permissions.isAdmin {
            rows.insert(.init(copy[.usersPermissions], "person.2", .users, "\(summary.userCount)"), at: 0)
        }
        if store.permissions.canManageSystem {
            rows.append(.init(copy[.opds], "globe", .opds, summary.opdsRunning ? copy[.running] : copy[.stopped], good: summary.opdsRunning))
        }
        return rows
    }

    private func systemRows(_ summary: AdministrativeManagementSummary) -> [ManagementRow] {
        guard store.permissions.canManageSystem else {
            return []
        }
        let healthValue = summary.componentCount == 0 ? nil : "\(summary.healthyComponentCount)/\(summary.componentCount) \(copy[.healthy])"
        let logValue = "\(summary.logBytes.administrativeByteCount) / \(summary.logLimitBytes.administrativeByteCount)"
        return [
            .init(copy[.backups], "externaldrive", .backups, summary.latestBackupAt?.administrativeFormatted(locale: copy.locale)),
            .init(copy[.workDetailOrder], "arrow.up.arrow.down", .workDetailOrder, nil),
            .init(copy[.systemHealth], "waveform.path.ecg", .health, healthValue, good: summary.componentCount > 0 && summary.healthyComponentCount == summary.componentCount),
            .init(copy[.systemLogs], "doc.text", .logs, logValue)
        ]
    }
}

private struct ManagementRow: Identifiable {
    var id: AdministrativeSettingsRoute { route }
    let title: String
    let icon: String
    let route: AdministrativeSettingsRoute
    let value: String?
    let warning: Bool
    let good: Bool

    init(_ title: String, _ icon: String, _ route: AdministrativeSettingsRoute, _ value: String?, warning: Bool = false, good: Bool = false) {
        self.title = title
        self.icon = icon
        self.route = route
        self.value = value
        self.warning = warning
        self.good = good
    }
}
