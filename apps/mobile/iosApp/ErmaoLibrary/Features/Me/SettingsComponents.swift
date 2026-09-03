import SwiftUI
import UIKit

enum SettingsMetrics {
    static let rowMinimumHeight = CGFloat(GeneratedDesignTokens.Settings.rowMinimumHeight)
    static let horizontalInset = CGFloat(GeneratedDesignTokens.Settings.horizontalInset)
    static let verticalInset = CGFloat(GeneratedDesignTokens.Settings.verticalInset)
    static let iconSlotSize = CGFloat(GeneratedDesignTokens.Settings.iconSlotSize)
    static let iconSize = CGFloat(GeneratedDesignTokens.Settings.iconSize)
    static let iconTitleSpacing = CGFloat(GeneratedDesignTokens.Settings.iconTitleSpacing)
    static let trailingSlotWidth = CGFloat(GeneratedDesignTokens.Settings.trailingSlotWidth)
    static let sectionSpacing = CGFloat(GeneratedDesignTokens.Settings.sectionSpacing)
    static let sectionHeaderBottomSpacing = CGFloat(GeneratedDesignTokens.Settings.sectionHeaderBottomSpacing)
    static let identityAvatarSize = CGFloat(GeneratedDesignTokens.Settings.identityAvatarSize)
    static let identityMinimumHeight = CGFloat(GeneratedDesignTokens.Settings.identityMinimumHeight)
    static let bottomActionHeight = CGFloat(GeneratedDesignTokens.Settings.bottomActionHeight)
    static let rowContentMinimumHeight = max(0, rowMinimumHeight - (verticalInset * 2))
    static let identityContentMinimumHeight = max(0, identityMinimumHeight - (verticalInset * 2))
    static let separatorLeading = iconSlotSize + iconTitleSpacing

    static var rowInsets: EdgeInsets {
        EdgeInsets(
            top: verticalInset,
            leading: horizontalInset,
            bottom: verticalInset,
            trailing: horizontalInset
        )
    }
}

enum SettingsColors {
    static let rowBackground = Color(uiColor: .systemGroupedBackground)
}

struct SettingsAvatarView: View {
    let data: Data?
    var size: CGFloat = 64

    @Environment(\.appTheme) private var theme

    var body: some View {
        Group {
            if let data, let image = UIImage(data: data) {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                Image("BrandMark")
                    .resizable()
                    .scaledToFill()
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
        .overlay(Circle().stroke(theme.divider, lineWidth: 1))
        .accessibilityHidden(true)
    }
}

struct SettingsToolbarAction: View {
    let title: Text
    var working = false
    var disabled = false
    let action: @MainActor () -> Void

    init(
        _ titleKey: LocalizedStringKey,
        working: Bool = false,
        disabled: Bool = false,
        action: @escaping @MainActor () -> Void
    ) {
        title = Text(titleKey)
        self.working = working
        self.disabled = disabled
        self.action = action
    }

    init(
        verbatim title: String,
        working: Bool = false,
        disabled: Bool = false,
        action: @escaping @MainActor () -> Void
    ) {
        self.title = Text(verbatim: title)
        self.working = working
        self.disabled = disabled
        self.action = action
    }

    var body: some View {
        let unavailable = disabled || working
        Button(action: action) {
            if working {
                ProgressView()
                    .controlSize(.small)
            } else {
                Image(systemName: "checkmark")
                    .accessibilityHidden(true)
            }
        }
        .accessibilityLabel(title)
        .opacity(disabled && !working ? 0.32 : 1)
        .disabled(unavailable)
    }
}

struct SettingsRowLabel: View {
    let titleKey: String
    let systemImage: String

    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: SettingsMetrics.iconTitleSpacing) {
            SettingsIcon(systemImage: systemImage)
            Text(LocalizedStringKey(titleKey))
                .font(.body)
                .foregroundStyle(theme.textPrimary)
        }
    }
}

struct SettingsIcon: View {
    let systemImage: String

    @Environment(\.appTheme) private var theme

    var body: some View {
        Image(systemName: systemImage)
            .font(.system(size: SettingsMetrics.iconSize, weight: .medium))
            .symbolRenderingMode(.monochrome)
            .foregroundStyle(theme.textSecondary)
            .frame(width: SettingsMetrics.iconSlotSize, height: SettingsMetrics.iconSlotSize)
            .accessibilityHidden(true)
    }
}

struct SettingsChevron: View {
    @Environment(\.appTheme) private var theme

    var body: some View {
        Image(systemName: "chevron.forward")
            .font(.caption.weight(.semibold))
            .foregroundStyle(theme.textTertiary)
            .frame(width: SettingsMetrics.trailingSlotWidth)
            .accessibilityHidden(true)
    }
}

struct SettingsSectionHeader: View {
    let title: Text

    @Environment(\.appTheme) private var theme

    init(_ titleKey: LocalizedStringKey) {
        title = Text(titleKey)
    }

    init(verbatim title: String) {
        self.title = Text(verbatim: title)
    }

    var body: some View {
        title
            .font(.footnote.weight(.semibold))
            .foregroundStyle(theme.textSecondary)
            .textCase(nil)
            .padding(.bottom, SettingsMetrics.sectionHeaderBottomSpacing)
    }
}

struct SettingsSection<Content: View>: View {
    private let title: Text?
    private let content: Content

    init(_ titleKey: LocalizedStringKey? = nil, @ViewBuilder content: () -> Content) {
        title = titleKey.map { Text($0) }
        self.content = content()
    }

    var body: some View {
        Section {
            content
        } header: {
            if let title {
                SettingsSectionHeaderContent(title: title)
            }
        }
    }
}

private struct SettingsSectionHeaderContent: View {
    let title: Text

    @Environment(\.appTheme) private var theme

    var body: some View {
        title
            .font(.footnote.weight(.semibold))
            .foregroundStyle(theme.textSecondary)
            .textCase(nil)
            .padding(.bottom, SettingsMetrics.sectionHeaderBottomSpacing)
    }
}

struct SettingsNavigationRow: View {
    let title: Text
    let status: Text?
    let systemImage: String
    let action: @MainActor () -> Void

    @Environment(\.appTheme) private var theme
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(
        _ titleKey: LocalizedStringKey,
        statusKey: LocalizedStringKey? = nil,
        systemImage: String,
        action: @escaping @MainActor () -> Void
    ) {
        title = Text(titleKey)
        status = statusKey.map { Text($0) }
        self.systemImage = systemImage
        self.action = action
    }

    init(
        _ titleKey: LocalizedStringKey,
        status: String?,
        systemImage: String,
        action: @escaping @MainActor () -> Void
    ) {
        title = Text(titleKey)
        self.status = status.map { Text(verbatim: $0) }
        self.systemImage = systemImage
        self.action = action
    }

    init(
        verbatim title: String,
        status: String? = nil,
        systemImage: String,
        action: @escaping @MainActor () -> Void
    ) {
        self.title = Text(verbatim: title)
        self.status = status.map { Text(verbatim: $0) }
        self.systemImage = systemImage
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            HStack(spacing: SettingsMetrics.iconTitleSpacing) {
                SettingsIcon(systemImage: systemImage)
                if dynamicTypeSize.isAccessibilitySize, let status {
                    VStack(alignment: .leading, spacing: .spaceHalf) {
                        title
                            .font(.body)
                            .foregroundStyle(theme.textPrimary)
                        status
                            .font(.subheadline)
                            .foregroundStyle(theme.textSecondary)
                            .lineLimit(2)
                    }
                    Spacer(minLength: .space1)
                } else {
                    title
                        .font(.body)
                        .foregroundStyle(theme.textPrimary)
                        .lineLimit(1)
                    Spacer(minLength: .space1)
                    if let status {
                        status
                            .font(.subheadline)
                            .foregroundStyle(theme.textSecondary)
                            .lineLimit(1)
                            .truncationMode(.tail)
                            .multilineTextAlignment(.trailing)
                    }
                }
                SettingsChevron()
            }
            .frame(minHeight: SettingsMetrics.rowContentMinimumHeight)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .listRowInsets(SettingsMetrics.rowInsets)
        .alignmentGuide(.listRowSeparatorLeading) { _ in
            SettingsMetrics.separatorLeading
        }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
    }
}

struct SettingsValueRow: View {
    let title: Text
    let value: Text
    let systemImage: String?

    @Environment(\.appTheme) private var theme
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(_ titleKey: LocalizedStringKey, value: String, systemImage: String? = nil) {
        title = Text(titleKey)
        self.value = Text(verbatim: value)
        self.systemImage = systemImage
    }

    init(verbatim title: String, value: String, systemImage: String? = nil) {
        self.title = Text(verbatim: title)
        self.value = Text(verbatim: value)
        self.systemImage = systemImage
    }

    var body: some View {
        HStack(alignment: .center, spacing: SettingsMetrics.iconTitleSpacing) {
            if let systemImage {
                SettingsIcon(systemImage: systemImage)
            }
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: .spaceHalf) {
                    title.font(.body).foregroundStyle(theme.textPrimary)
                    value.font(.subheadline).foregroundStyle(theme.textSecondary)
                }
                Spacer(minLength: 0)
            } else {
                title.font(.body).foregroundStyle(theme.textPrimary)
                Spacer(minLength: .space1)
                value
                    .font(.subheadline)
                    .foregroundStyle(theme.textSecondary)
                    .lineLimit(2)
                    .multilineTextAlignment(.trailing)
            }
        }
        .frame(minHeight: SettingsMetrics.rowContentMinimumHeight)
        .listRowInsets(SettingsMetrics.rowInsets)
        .alignmentGuide(.listRowSeparatorLeading) { _ in
            systemImage == nil ? 0 : SettingsMetrics.separatorLeading
        }
    }
}

struct SettingsPickerRow<SelectionValue: Hashable, Options: View>: View {
    let title: Text
    let systemImage: String?
    @Binding var selection: SelectionValue
    let options: Options

    init(
        _ titleKey: LocalizedStringKey,
        systemImage: String? = nil,
        selection: Binding<SelectionValue>,
        @ViewBuilder options: () -> Options
    ) {
        title = Text(titleKey)
        self.systemImage = systemImage
        _selection = selection
        self.options = options()
    }

    var body: some View {
        let separatorLeading = systemImage == nil ? 0 : SettingsMetrics.separatorLeading
        Picker(selection: $selection) {
            options
        } label: {
            HStack(spacing: SettingsMetrics.iconTitleSpacing) {
                if let systemImage {
                    SettingsIcon(systemImage: systemImage)
                }
                title.font(.body)
            }
        }
        .frame(minHeight: SettingsMetrics.rowContentMinimumHeight)
        .listRowInsets(SettingsMetrics.rowInsets)
        .alignmentGuide(.listRowSeparatorLeading) { _ in
            separatorLeading
        }
    }
}

struct SettingsToggleRow: View {
    let title: Text
    let systemImage: String?
    @Binding var isOn: Bool

    init(_ titleKey: LocalizedStringKey, systemImage: String? = nil, isOn: Binding<Bool>) {
        title = Text(titleKey)
        self.systemImage = systemImage
        _isOn = isOn
    }

    init(verbatim title: String, systemImage: String? = nil, isOn: Binding<Bool>) {
        self.title = Text(verbatim: title)
        self.systemImage = systemImage
        _isOn = isOn
    }

    var body: some View {
        Toggle(isOn: $isOn) {
            HStack(spacing: SettingsMetrics.iconTitleSpacing) {
                if let systemImage {
                    SettingsIcon(systemImage: systemImage)
                }
                title.font(.body)
            }
        }
        .frame(minHeight: SettingsMetrics.rowContentMinimumHeight)
        .listRowInsets(SettingsMetrics.rowInsets)
        .alignmentGuide(.listRowSeparatorLeading) { _ in
            systemImage == nil ? 0 : SettingsMetrics.separatorLeading
        }
    }
}

struct SettingsFieldRow<Field: View>: View {
    let label: Text
    let field: Field

    init(_ labelKey: LocalizedStringKey, @ViewBuilder field: () -> Field) {
        label = Text(labelKey)
        self.field = field()
    }

    init(verbatim label: String, @ViewBuilder field: () -> Field) {
        self.label = Text(verbatim: label)
        self.field = field()
    }

    var body: some View {
        LabeledContent {
            field
        } label: {
            label.font(.body)
        }
        .frame(minHeight: SettingsMetrics.rowContentMinimumHeight)
        .listRowInsets(SettingsMetrics.rowInsets)
        .alignmentGuide(.listRowSeparatorLeading) { _ in 0 }
    }
}

/// A settings form row for editable text values.
///
/// Text input controls in settings use the trailing edge so values line up
/// across a form while labels and supporting copy retain the system leading
/// alignment. Keep this component for `TextField` and `SecureField` only;
/// pickers, toggles and other controls should use their dedicated row types.
struct SettingsTextInputRow<Field: View>: View {
    private let label: Text
    private let field: Field

    init(_ labelKey: LocalizedStringKey, @ViewBuilder field: () -> Field) {
        label = Text(labelKey)
        self.field = field()
    }

    init(verbatim label: String, @ViewBuilder field: () -> Field) {
        self.label = Text(verbatim: label)
        self.field = field()
    }

    var body: some View {
        LabeledContent {
            field
                .multilineTextAlignment(.trailing)
        } label: {
            label.font(.body)
        }
        .frame(minHeight: SettingsMetrics.rowContentMinimumHeight)
        .listRowInsets(SettingsMetrics.rowInsets)
        .alignmentGuide(.listRowSeparatorLeading) { _ in 0 }
    }
}

/// Shared segmented control treatment for settings pages that contain more
/// than one independent form. The selected tab owns the trailing save action.
struct SettingsTabPicker<SelectionValue: Hashable, Options: View>: View {
    private let title: Text
    @Binding private var selection: SelectionValue
    private let options: Options

    init(
        _ titleKey: LocalizedStringKey,
        selection: Binding<SelectionValue>,
        @ViewBuilder options: () -> Options
    ) {
        title = Text(titleKey)
        _selection = selection
        self.options = options()
    }

    init(
        verbatim title: String,
        selection: Binding<SelectionValue>,
        @ViewBuilder options: () -> Options
    ) {
        self.title = Text(verbatim: title)
        _selection = selection
        self.options = options()
    }

    var body: some View {
        Picker(selection: $selection) {
            options
        } label: {
            title
        }
        .pickerStyle(.segmented)
        .frame(minHeight: SettingsMetrics.rowContentMinimumHeight)
        .listRowInsets(SettingsMetrics.rowInsets)
        .accessibilityLabel(title)
    }
}

struct SettingsActionRow: View {
    let title: Text
    let role: ButtonRole?
    let action: @MainActor () -> Void

    init(_ titleKey: LocalizedStringKey, role: ButtonRole? = nil, action: @escaping @MainActor () -> Void) {
        title = Text(titleKey)
        self.role = role
        self.action = action
    }

    init(verbatim title: String, role: ButtonRole? = nil, action: @escaping @MainActor () -> Void) {
        self.title = Text(verbatim: title)
        self.role = role
        self.action = action
    }

    var body: some View {
        Button(role: role, action: action) {
            title
                .font(.body)
                .frame(maxWidth: .infinity, minHeight: SettingsMetrics.rowContentMinimumHeight, alignment: .leading)
                .contentShape(Rectangle())
        }
        .listRowInsets(SettingsMetrics.rowInsets)
        .alignmentGuide(.listRowSeparatorLeading) { _ in 0 }
    }
}

struct SettingsLoadingState: View {
    let title: LocalizedStringKey

    var body: some View {
        ProgressView(title)
            .frame(maxWidth: .infinity, minHeight: 160)
    }
}

struct SettingsEmptyState: View {
    let title: Text
    let systemImage: String

    var body: some View {
        ContentUnavailableView {
            Label { title } icon: { Image(systemName: systemImage) }
        }
    }
}

struct SettingsErrorState: View {
    let title: Text
    let message: Text?
    let retryTitle: Text
    let retry: @MainActor () -> Void

    var body: some View {
        ContentUnavailableView {
            Label { title } icon: { Image(systemName: "exclamationmark.triangle") }
        } description: {
            message
        } actions: {
            Button(action: retry) { retryTitle }
                .buttonStyle(.bordered)
        }
    }
}

struct SettingsBottomActionBar: View {
    let title: Text
    var destructive = false
    var working = false
    var disabled = false
    let action: @MainActor () -> Void

    @Environment(\.appTheme) private var theme

    init(
        _ titleKey: LocalizedStringKey,
        destructive: Bool = false,
        working: Bool = false,
        disabled: Bool = false,
        action: @escaping @MainActor () -> Void
    ) {
        title = Text(titleKey)
        self.destructive = destructive
        self.working = working
        self.disabled = disabled
        self.action = action
    }

    init(
        verbatim title: String,
        destructive: Bool = false,
        working: Bool = false,
        disabled: Bool = false,
        action: @escaping @MainActor () -> Void
    ) {
        self.title = Text(verbatim: title)
        self.destructive = destructive
        self.working = working
        self.disabled = disabled
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            ZStack {
                title.font(.body.weight(.semibold)).opacity(working ? 0 : 1)
                if working { ProgressView().tint(theme.onAction) }
            }
            .frame(maxWidth: .infinity, minHeight: SettingsMetrics.bottomActionHeight)
        }
        .buttonStyle(.borderedProminent)
        .tint(destructive ? .red : theme.actionAccent)
        .disabled(disabled || working)
        .padding(.horizontal, SettingsMetrics.horizontalInset)
        .padding(.vertical, .space1)
        .background(.bar)
    }
}

struct SettingsScreen<Content: View>: View {
    let title: LocalizedStringKey
    var titleDisplayMode: NavigationBarItem.TitleDisplayMode = .inline
    let content: Content

    init(
        _ title: LocalizedStringKey,
        titleDisplayMode: NavigationBarItem.TitleDisplayMode = .inline,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.titleDisplayMode = titleDisplayMode
        self.content = content()
    }

    var body: some View {
        SettingsList { content }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(titleDisplayMode)
    }
}

struct SettingsList<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        List {
            content
                .listRowBackground(SettingsColors.rowBackground)
        }
        .settingsListSurface()
    }
}

struct SettingsForm<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        Form {
            content
                .listRowBackground(SettingsColors.rowBackground)
        }
        .settingsListSurface()
    }
}

private struct SettingsPageSurfaceModifier: ViewModifier {
    @Environment(\.appTheme) private var theme

    func body(content: Content) -> some View {
        content
            .foregroundStyle(theme.textPrimary)
            .background(theme.canvas.ignoresSafeArea())
    }
}

private struct SettingsListSurfaceModifier: ViewModifier {
    @Environment(\.appTheme) private var theme

    func body(content: Content) -> some View {
        content
            .listStyle(.insetGrouped)
            .listSectionSpacing(.custom(SettingsMetrics.sectionSpacing))
            .contentMargins(.bottom, .space2, for: .scrollContent)
            .scrollContentBackground(.hidden)
            .settingsPageSurface()
            .tint(theme.actionAccent)
    }
}

private struct SettingsAlertModifier: ViewModifier {
    @ObservedObject var viewModel: SettingsViewModel

    func body(content: Content) -> some View {
        content.alert(item: alertBinding) { alert in
            Alert(
                title: Text(LocalizedStringKey(alert.titleKey)),
                message: alertMessage(alert),
                dismissButton: .default(Text("common.ok")) {
                    viewModel.dismissAlert()
                }
            )
        }
    }

    private func alertMessage(_ alert: SettingsAlert) -> Text {
        let message = Text(LocalizedStringKey(alert.messageKey))
        guard let referenceCode = alert.referenceCode else { return message }
        return message + Text("\n\n") + Text("settings.error.referenceCode") + Text(verbatim: ": \(referenceCode)")
    }

    private var alertBinding: Binding<SettingsAlert?> {
        Binding(
            get: { viewModel.alert },
            set: { value in
                if value == nil { viewModel.dismissAlert() }
            }
        )
    }
}

extension View {
    func settingsPageSurface() -> some View {
        modifier(SettingsPageSurfaceModifier())
    }

    func settingsListSurface() -> some View {
        modifier(SettingsListSurfaceModifier())
    }

    func settingsAlert(viewModel: SettingsViewModel) -> some View {
        modifier(SettingsAlertModifier(viewModel: viewModel))
    }
}
