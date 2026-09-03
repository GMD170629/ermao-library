import SwiftUI

struct MetadataProvidersView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<[MetadataProvider]> = .idle
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme
    @Environment(\.administrativeNavigate) private var navigate

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { providers in
            SettingsList {
                Section(copy[.provider]) {
                    ForEach(Array(providers.enumerated()), id: \.element.id) { index, provider in
                        HStack {
                            Text("\(index + 1)")
                                .foregroundStyle(theme.textSecondary)
                                .frame(width: SettingsMetrics.iconSlotSize, alignment: .center)
                            Button { navigate(.metadataProvider(providerID: provider.id)) } label: {
                                VStack(alignment: .leading) {
                                    Text(providerName(provider)).appTextStyle(.headline)
                                    HStack {
                                        AdministrativeStatusLabel(title: providerStatus(provider), status: provider.status == .available ? .good : provider.status == .unavailable ? .failed : .neutral)
                                        if let milliseconds = provider.responseMilliseconds { Text(duration(milliseconds)).font(.caption).foregroundStyle(theme.textSecondary) }
                                    }
                                }
                            }
                            .buttonStyle(.plain)
                            Toggle("", isOn: Binding(get: { provider.enabled }, set: { enabled in toggle(provider, enabled) })).labelsHidden()
                        }
                        .frame(minHeight: SettingsMetrics.rowContentMinimumHeight)
                        .listRowInsets(SettingsMetrics.rowInsets)
                        .alignmentGuide(.listRowSeparatorLeading) { _ in SettingsMetrics.horizontalInset + SettingsMetrics.iconSlotSize + SettingsMetrics.iconTitleSpacing }
                    }
                }
                Section { Button(copy[.testProviders]) { testAll(providers) }.frame(maxWidth: .infinity) }
            }
        }.navigationTitle(copy[.providersTitle]).navigationBarTitleDisplayMode(.inline).refreshable { await loadAsync() }.task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func providerStatus(_ provider: MetadataProvider) -> String { switch provider.status { case .available: copy[.available]; case .unavailable: copy[.unavailable]; case .untested: copy[.unknown] } }
    private func providerName(_ provider: MetadataProvider) -> String {
        switch provider.id {
        case "douban": copy[.providerDouban]
        case "bangumi": copy[.providerBangumi]
        case "ai": copy[.providerAI]
        default: provider.displayName
        }
    }
    private func duration(_ milliseconds: Int) -> String {
        Measurement(value: Double(milliseconds), unit: UnitDuration.milliseconds)
            .formatted(.measurement(width: .abbreviated).locale(Locale(identifier: copy.locale.rawValue)))
    }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; state = await store.load(scope: "providers") { try await store.client.loadMetadataProviders() } }
    private func toggle(_ provider: MetadataProvider, _ enabled: Bool) { Task { let result = await store.performValue(id: "provider-toggle-\(provider.id)") { try await store.client.setMetadataProviderEnabled(id: provider.id, enabled: enabled) }; if case .success = result { await loadAsync() } } }
    private func testAll(_ providers: [MetadataProvider]) { Task { for provider in providers where provider.enabled { let result = await store.performValue(id: "provider-test-\(provider.id)", success: .connected) { try await store.client.testMetadataProvider(id: provider.id) }; if case .success = result { continue } else { break } }; await loadAsync() } }
}

struct MetadataProviderDetailView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    let providerID: String
    @State private var state: AdministrativeLoadState<MetadataProviderConfiguration> = .idle
    @State private var configuration: MetadataProviderConfiguration?
    @State private var tested: MetadataProvider?
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { _ in
            if let binding = Binding($configuration) {
                SettingsForm {
                    Section(copy[.provider]) {
                        SettingsValueRow(LocalizedStringKey(copy[.provider]), value: providerName(binding.wrappedValue.provider))
                    }
                    Section(copy[.connectionTest]) {
                        ForEach(binding.wrappedValue.values.keys.sorted(), id: \.self) { key in
                            editableField(key, binding: binding)
                        }
                    }
                    if let tested {
                        Section(copy[.connectionTest]) {
                            AdministrativeStatusLabel(title: tested.status == .available ? copy[.connected] : copy[.unavailable], status: tested.status == .available ? .good : .failed)
                            if let milliseconds = tested.responseMilliseconds {
                                SettingsValueRow(LocalizedStringKey(copy[.responseTime]), value: duration(milliseconds))
                            }
                        }
                    }
                }
            }
        }.navigationTitle(copy[.providerConfigurationTitle]).navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if let configuration {
                ToolbarItemGroup(placement: .confirmationAction) {
                    Menu {
                        Button(copy[.saveAndTest]) { saveAndTest(configuration) }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                    .disabled(store.operationInFlight != nil)
                    AdministrativeToolbarAction(
                        title: copy[.saveConfiguration],
                        working: store.operationInFlight == "save-provider"
                    ) { save(configuration) }
                }
            }
        }
        .task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    @ViewBuilder private func editableField(_ key: String, binding: Binding<MetadataProviderConfiguration>) -> some View {
        let value = binding.wrappedValue.values[key] ?? .empty
        let title = fieldTitle(key)
        switch value {
        case let .toggle(current):
            SettingsToggleRow(
                verbatim: title,
                isOn: Binding(
                    get: { if case let .toggle(value) = binding.wrappedValue.values[key] { value } else { current } },
                    set: { binding.wrappedValue.values[key] = .toggle($0) }
                )
            )
        case let .integer(current):
            SettingsTextInputRow(verbatim: title) {
                TextField(
                    title,
                    value: Binding(get: { if case let .integer(value) = binding.wrappedValue.values[key] { value } else { current } }, set: { binding.wrappedValue.values[key] = .integer($0) }),
                    format: .number
                )
                .keyboardType(.numberPad)
            }
        case let .decimal(current):
            SettingsTextInputRow(verbatim: title) {
                TextField(
                    title,
                    value: Binding(get: { if case let .decimal(value) = binding.wrappedValue.values[key] { value } else { current } }, set: { binding.wrappedValue.values[key] = .decimal($0) }),
                    format: .number
                )
                .keyboardType(.decimalPad)
            }
        case let .textList(current):
            SettingsTextInputRow(verbatim: title) {
                TextField(
                    title,
                    text: Binding(get: { if case let .textList(value) = binding.wrappedValue.values[key] { value.joined(separator: ", ") } else { current.joined(separator: ", ") } }, set: { binding.wrappedValue.values[key] = .textList($0.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }) })
                )
            }
        case let .text(current):
            SettingsTextInputRow(verbatim: title) {
                TextField(
                    title,
                    text: Binding(get: { if case let .text(value) = binding.wrappedValue.values[key] { value } else { current } }, set: { binding.wrappedValue.values[key] = .text($0) })
                )
                .textInputAutocapitalization(.never)
            }
        case .empty:
            SettingsTextInputRow(LocalizedStringKey(copy[.keepSecretHint])) {
                SecureField(
                    LocalizedStringKey(copy[.keepSecretHint]),
                    text: Binding(get: { binding.wrappedValue.secretReplacements[key] ?? "" }, set: { binding.wrappedValue.secretReplacements[key] = $0 })
                )
            }
        }
    }
    private func fieldTitle(_ key: String) -> String {
        switch key {
        case "baseUrl": copy[.apiBaseURL]
        case "apiKey": copy[.apiKey]
        case "userAgent": copy[.userAgent]
        case "accessToken": copy[.accessToken]
        case "model": copy[.model]
        default: copy[.configurationItem]
        }
    }
    private func providerName(_ provider: MetadataProvider) -> String {
        switch provider.id {
        case "douban": copy[.providerDouban]
        case "bangumi": copy[.providerBangumi]
        case "ai": copy[.providerAI]
        default: provider.displayName
        }
    }
    private func duration(_ milliseconds: Int) -> String {
        Measurement(value: Double(milliseconds), unit: UnitDuration.milliseconds)
            .formatted(.measurement(width: .abbreviated).locale(Locale(identifier: copy.locale.rawValue)))
    }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; let loaded = await store.load(scope: "provider-\(providerID)") { try await store.client.loadMetadataProviderConfiguration(id: providerID) }; state = loaded; if case let .loaded(value) = loaded { configuration = value } }
    private func save(_ value: MetadataProviderConfiguration) { Task { let result = await store.performValue(id: "save-provider") { try await store.client.saveMetadataProviderConfiguration(value) }; if case let .success(updated) = result { configuration = updated; state = .loaded(updated) } } }
    private func saveAndTest(_ value: MetadataProviderConfiguration) { Task { let saveResult = await store.performValue(id: "save-provider") { try await store.client.saveMetadataProviderConfiguration(value) }; guard case let .success(updated) = saveResult else { return }; configuration = updated; let testResult = await store.performValue(id: "test-provider", success: .connected) { try await store.client.testMetadataProvider(id: providerID) }; if case let .success(result) = testResult { tested = result } } }
}
