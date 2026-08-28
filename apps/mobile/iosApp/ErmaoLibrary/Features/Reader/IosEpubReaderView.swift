import Foundation
import ReadiumNavigator
import SwiftUI

func localizedReaderOption(_ key: String, bundle: Bundle = .main) -> String {
    bundle.localizedString(forKey: key, value: key, table: nil)
}

struct IosReflowableReaderView: View {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @ObservedObject var session: IosReflowableReaderSession
    var onRetry: () -> Void = {}

    var body: some View {
        ZStack {
            palette.background.ignoresSafeArea()
            content
            if session.phase == .reading || session.phase == .background {
                IosReaderControls(session: session, onClose: close)
            }
            if session.resumePrompt != nil || session.restoreWarning != nil {
                resumeNotice
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                    .zIndex(2)
            }
        }
        .animation(.easeInOut(duration: UIAccessibility.isReduceMotionEnabled ? 0 : 0.18), value: session.controlsVisible)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("reader.reflow.screen")
        .accessibilityAction(named: Text("reader.controls.show")) { session.showControls() }
        .statusBarHidden(!session.controlsVisible)
        .task {
            session.refreshSystemAppearance(colorScheme == .dark ? .dark : .light)
            await session.open()
            await session.verifyRestoredLocationAfterPresentation()
            updateIdleTimer()
        }
        .onDisappear { UIApplication.shared.isIdleTimerDisabled = false }
        .onChange(of: colorScheme) { _, _ in
            session.refreshSystemAppearance(colorScheme == .dark ? .dark : .light)
        }
        .onChange(of: scenePhase) { _, phase in
            Task {
                switch phase {
                case .background: await session.enterBackground()
                case .active:
                    session.becomeActive()
                    updateIdleTimer()
                default: break
                }
            }
        }
        .alert(
            String(localized: "reader.error.title"),
            isPresented: Binding(
                get: { session.presentationError != nil },
                set: { _ in session.dismissPresentationError() }
            )
        ) {
            Button(String(localized: "common.ok"), role: .cancel) {}
        } message: { Text(session.presentationError.map(session.failureDescription(for:)) ?? "") }
    }

    private var resumeNotice: some View {
        VStack {
            Spacer()
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: "clock.arrow.circlepath")
                    .foregroundStyle(palette.accent)
                    .padding(.top, 2)
                VStack(alignment: .leading, spacing: 8) {
                    if let prompt = session.resumePrompt {
                        Text(resumePromptText(prompt))
                            .font(.subheadline)
                            .foregroundStyle(palette.foreground)
                        if session.resumeActionFailed {
                            Text("reader.resume.returnFailed")
                                .font(.caption)
                                .foregroundStyle(palette.secondary)
                        }
                        Button("reader.resume.return") {
                            Task { await session.returnToResumeAlternative() }
                        }
                        .font(.subheadline.weight(.semibold))
                    } else {
                        Text("reader.restore.warning.message")
                            .font(.subheadline)
                            .foregroundStyle(palette.foreground)
                    }
                }
                Spacer(minLength: 4)
                Button {
                    if session.resumePrompt != nil {
                        session.dismissResumePrompt()
                    } else {
                        session.dismissRestoreWarning()
                    }
                } label: {
                    Image(systemName: "xmark").frame(width: 32, height: 32)
                }
                .accessibilityLabel(Text("common.close"))
            }
            .padding(14)
            .background(palette.surface)
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(palette.divider))
            .clipShape(RoundedRectangle(cornerRadius: 16))
            .padding(.horizontal, 16)
            .padding(.bottom, session.controlsVisible ? 178 : 20)
        }
        .animation(.easeInOut(duration: UIAccessibility.isReduceMotionEnabled ? 0 : 0.18), value: session.controlsVisible)
    }

    private func resumePromptText(_ prompt: IosReaderResumePrompt) -> String {
        let date = Date(timeIntervalSince1970: TimeInterval(prompt.capturedAtEpochMillis) / 1_000)
        let time = date.formatted(date: .abbreviated, time: .shortened)
        let trimmedChapter = prompt.chapterLabel?.trimmingCharacters(in: .whitespacesAndNewlines)
        let position = trimmedChapter.flatMap { $0.isEmpty ? nil : $0 }
            ?? String(format: "%d%%", Int(prompt.percent.rounded()))
        return String(
            format: String(localized: "reader.remote.notice.format"),
            locale: .current,
            position,
            time
        )
    }

    @ViewBuilder
    private var content: some View {
        switch session.phase {
        case .opening:
            ProgressView("reader.opening").tint(palette.accent).accessibilityIdentifier("reader.opening")
        case let .failed(code):
            VStack(spacing: 16) {
                Image(systemName: "exclamationmark.triangle").font(.largeTitle)
                Text("reader.error.title").font(.headline)
                Text(session.failureDescription(for: code))
                    .multilineTextAlignment(.center)
                    .accessibilityIdentifier("reader.open.failure.\(code.rawValue)")
                Button("reader.retry.open", action: onRetry)
                Button("common.close") { dismiss() }
            }
            .padding(24)
            .foregroundStyle(palette.foreground)
        default:
            if let navigator = session.navigator {
                ReadiumNavigatorHost(navigator: navigator).ignoresSafeArea()
            }
        }
    }

    private var palette: ReaderPalette {
        ReaderPalette(theme: session.preferences.resolvedTheme(for: colorScheme == .dark ? .dark : .light))
    }

    private func updateIdleTimer() {
        UIApplication.shared.isIdleTimerDisabled = session.preferences.keepScreenAwake
    }

    private func close() {
        Task {
            try? await session.close()
            UIApplication.shared.isIdleTimerDisabled = false
            dismiss()
        }
    }
}

struct ReaderPalette {
    let background: SwiftUI.Color
    let surface: SwiftUI.Color
    let foreground: SwiftUI.Color
    let secondary: SwiftUI.Color
    let divider: SwiftUI.Color
    let accent: SwiftUI.Color

    init(theme: IosReaderTheme) {
        let colors = theme.colors
        background = SwiftUI.Color(hex: colors.background)
        surface = background
        foreground = SwiftUI.Color(hex: colors.foreground)
        secondary = foreground.opacity(0.72)
        divider = foreground.opacity(0.16)
        accent = SwiftUI.Color(hex: colors.accent)
    }
}

private struct ReadiumNavigatorHost: UIViewControllerRepresentable {
    let navigator: EPUBNavigatorViewController
    func makeUIViewController(context: Context) -> EPUBNavigatorViewController { navigator }
    func updateUIViewController(_ uiViewController: EPUBNavigatorViewController, context: Context) {}
}
