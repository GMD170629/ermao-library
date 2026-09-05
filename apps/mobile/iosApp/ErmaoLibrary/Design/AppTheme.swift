import SwiftUI

struct AppTheme: Equatable, Sendable {
    let canvas: Color
    let surface: Color
    let surfaceRaised: Color
    let textPrimary: Color
    let textSecondary: Color
    let textTertiary: Color
    let divider: Color
    let brandAccent: Color
    let actionAccent: Color
    let accentSoft: Color
    let onAction: Color

    static let app = AppTheme(
        canvas: Color(hex: GeneratedDesignTokens.App.canvas),
        surface: Color(hex: GeneratedDesignTokens.App.surface),
        surfaceRaised: Color(hex: GeneratedDesignTokens.App.surfaceRaised),
        textPrimary: Color(hex: GeneratedDesignTokens.App.textPrimary),
        textSecondary: Color(hex: GeneratedDesignTokens.App.textSecondary),
        textTertiary: Color(hex: GeneratedDesignTokens.App.textTertiary),
        divider: Color(hex: GeneratedDesignTokens.App.divider),
        brandAccent: Color(hex: GeneratedDesignTokens.App.brandAccent),
        actionAccent: Color(hex: GeneratedDesignTokens.App.actionAccent),
        accentSoft: Color(hex: GeneratedDesignTokens.App.accentSoft),
        onAction: Color(hex: GeneratedDesignTokens.App.onAction)
    )
}

private struct AppThemeKey: EnvironmentKey {
    static let defaultValue = AppTheme.app
}

private struct SystemColorSchemeKey: EnvironmentKey {
    static let defaultValue = ColorScheme.light
}

extension EnvironmentValues {
    var appTheme: AppTheme {
        get { self[AppThemeKey.self] }
        set { self[AppThemeKey.self] = newValue }
    }

    var systemColorScheme: ColorScheme {
        get { self[SystemColorSchemeKey.self] }
        set { self[SystemColorSchemeKey.self] = newValue }
    }
}

extension View {
    func appCanvas() -> some View {
        modifier(AppCanvasModifier())
    }
}

private struct AppCanvasModifier: ViewModifier {
    @Environment(\.appTheme) private var theme

    func body(content: Content) -> some View {
        content
            .foregroundStyle(theme.textPrimary)
            .background(theme.canvas.ignoresSafeArea())
    }
}

extension CGFloat {
    static let spaceHalf = CGFloat(GeneratedDesignTokens.Spacing.space0_5)
    static let space1 = CGFloat(GeneratedDesignTokens.Spacing.space1)
    static let space1Half = CGFloat(GeneratedDesignTokens.Spacing.space1_5)
    static let space2 = CGFloat(GeneratedDesignTokens.Spacing.space2)
    static let space3 = CGFloat(GeneratedDesignTokens.Spacing.space3)
    static let space4 = CGFloat(GeneratedDesignTokens.Spacing.space4)
    static let space5 = CGFloat(GeneratedDesignTokens.Spacing.space5)
    static let space6 = CGFloat(GeneratedDesignTokens.Spacing.space6)
    static let iosMinimumTouchTarget = CGFloat(GeneratedDesignTokens.Accessibility.MinimumTouchTarget.ios)
}

enum AppTextRole: Sendable {
    case display
    case title
    case sectionTitle
    case headline
    case body
    case callout
    case label
    case caption
    case button

    var metrics: (size: CGFloat, lineHeight: CGFloat, weight: Double) {
        switch self {
        case .display:
            (
                CGFloat(GeneratedDesignTokens.Display.size),
                CGFloat(GeneratedDesignTokens.Display.lineHeight),
                GeneratedDesignTokens.Display.weight
            )
        case .title:
            (
                CGFloat(GeneratedDesignTokens.Title.size),
                CGFloat(GeneratedDesignTokens.Title.lineHeight),
                GeneratedDesignTokens.Title.weight
            )
        case .sectionTitle:
            (
                CGFloat(GeneratedDesignTokens.SectionTitle.size),
                CGFloat(GeneratedDesignTokens.SectionTitle.lineHeight),
                GeneratedDesignTokens.SectionTitle.weight
            )
        case .headline:
            (
                CGFloat(GeneratedDesignTokens.Headline.size),
                CGFloat(GeneratedDesignTokens.Headline.lineHeight),
                GeneratedDesignTokens.Headline.weight
            )
        case .body:
            (
                CGFloat(GeneratedDesignTokens.Body.size),
                CGFloat(GeneratedDesignTokens.Body.lineHeight),
                GeneratedDesignTokens.Body.weight
            )
        case .callout:
            (
                CGFloat(GeneratedDesignTokens.Callout.size),
                CGFloat(GeneratedDesignTokens.Callout.lineHeight),
                GeneratedDesignTokens.Callout.weight
            )
        case .label:
            (
                CGFloat(GeneratedDesignTokens.Label.size),
                CGFloat(GeneratedDesignTokens.Label.lineHeight),
                GeneratedDesignTokens.Label.weight
            )
        case .caption:
            (
                CGFloat(GeneratedDesignTokens.Caption.size),
                CGFloat(GeneratedDesignTokens.Caption.lineHeight),
                GeneratedDesignTokens.Caption.weight
            )
        case .button:
            (
                CGFloat(GeneratedDesignTokens.Button.size),
                CGFloat(GeneratedDesignTokens.Button.lineHeight),
                GeneratedDesignTokens.Button.weight
            )
        }
    }

    fileprivate var relativeTextStyle: Font.TextStyle {
        switch self {
        case .display: .largeTitle
        case .title: .title2
        case .sectionTitle: .title3
        case .headline: .headline
        case .body: .body
        case .callout: .callout
        case .label: .subheadline
        case .caption: .caption
        case .button: .body
        }
    }
}

extension View {
    func appTextStyle(_ role: AppTextRole) -> some View {
        modifier(AppTextStyleModifier(role: role))
    }
}

private struct AppTextStyleModifier: ViewModifier {
    private let tokenWeight: Double
    @ScaledMetric private var fontSize: CGFloat
    @ScaledMetric private var lineHeight: CGFloat

    init(role: AppTextRole) {
        tokenWeight = role.metrics.weight
        _fontSize = ScaledMetric(
            wrappedValue: role.metrics.size,
            relativeTo: role.relativeTextStyle
        )
        _lineHeight = ScaledMetric(
            wrappedValue: role.metrics.lineHeight,
            relativeTo: role.relativeTextStyle
        )
    }

    func body(content: Content) -> some View {
        content
            .font(.system(size: fontSize, weight: weight(for: tokenWeight)))
            .lineSpacing(max(0, lineHeight - fontSize))
    }

    private func weight(for numericWeight: Double) -> Font.Weight {
        switch numericWeight {
        case 700...: .bold
        case 600..<700: .semibold
        case 500..<600: .medium
        case ..<350: .light
        default: .regular
        }
    }
}

extension Color {
    init(hex: String) {
        let value = UInt64(hex.trimmingCharacters(in: CharacterSet(charactersIn: "#")), radix: 16) ?? 0
        self.init(
            .sRGB,
            red: Double((value >> 16) & 0xff) / 255,
            green: Double((value >> 8) & 0xff) / 255,
            blue: Double(value & 0xff) / 255,
            opacity: 1
        )
    }
}
