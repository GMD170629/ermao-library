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
    @State private var activePanel: ReaderPanel?
    @State private var closingFailure = false
    @State private var sliderValue = 0.0
    @State private var sliderIsEditing = false

    var body: some View {
        ZStack {
            palette.background.ignoresSafeArea()
            content
            if session.controlsVisible,
               session.phase == .reading || session.phase == .background {
                controls.transition(.opacity)
            }
            if session.resumePrompt != nil || session.restoreWarning != nil {
                resumeNotice
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                    .zIndex(2)
            }
        }
        .animation(.easeInOut(duration: UIAccessibility.isReduceMotionEnabled ? 0 : 0.18), value: session.controlsVisible)
        .accessibilityAction(named: Text("reader.controls.show")) { session.showControls() }
        .statusBarHidden(!session.controlsVisible)
        .task {
            await session.open()
            await session.verifyRestoredLocationAfterPresentation()
            updateIdleTimer()
        }
        .onDisappear { UIApplication.shared.isIdleTimerDisabled = false }
        .onChange(of: session.progress) { value in
            if !sliderIsEditing { sliderValue = value }
        }
        .onChange(of: session.preferences) { _ in
            session.applyPreferences()
            updateIdleTimer()
        }
        .onChange(of: colorScheme) { _ in
            if session.preferences.themeMode == .system { session.applyPreferences() }
        }
        .onChange(of: scenePhase) { phase in
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
        .sheet(item: $activePanel) { panel in
            switch panel {
            case .contents: ReaderTOCSheet(session: session)
            case .notes: ReaderNotesSheet(session: session)
            case .appearance: ReaderAppearanceSheet(session: session)
            case .settings: ReaderSettingsSheet(session: session)
            }
        }
        .alert(String(localized: "reader.save.failure.title"), isPresented: $closingFailure) {
            Button(String(localized: "common.ok"), role: .cancel) {}
        } message: { Text("reader.save.failure.message") }
        .alert(
            String(localized: "reader.error.title"),
            isPresented: Binding(
                get: { session.presentationError != nil && !closingFailure },
                set: { _ in session.dismissPresentationError() }
            )
        ) {
            Button(String(localized: "common.ok"), role: .cancel) {}
        } message: { Text(session.presentationError?.localizedDescription ?? "") }
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
            format: String(localized: "reader.resume.prompt.format"),
            locale: .current,
            time,
            position
        )
    }

    @ViewBuilder
    private var content: some View {
        switch session.phase {
        case .opening:
            ProgressView("reader.opening").tint(palette.accent)
        case let .failed(code):
            VStack(spacing: 16) {
                Image(systemName: "exclamationmark.triangle").font(.largeTitle)
                Text("reader.error.title").font(.headline)
                Text(code.localizedDescription).multilineTextAlignment(.center)
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

    private var controls: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Button(action: close) {
                    Image(systemName: "chevron.backward").frame(width: 44, height: 44)
                }
                .accessibilityLabel(Text("reader.close"))

                VStack(spacing: 2) {
                    Text(session.chapterTitle ?? session.displayTitle)
                        .font(.headline).lineLimit(1)
                    if session.chapterTitle != nil {
                        Text(session.displayTitle).font(.caption).lineLimit(1).foregroundStyle(palette.secondary)
                    }
                }
                .frame(maxWidth: .infinity)

                Button { Task { await session.toggleCurrentBookmark() } } label: {
                    Image(systemName: session.currentBookmarkActive ? "bookmark.fill" : "bookmark")
                        .frame(width: 44, height: 44)
                }
                .disabled(session.navigator == nil)
                .accessibilityLabel(Text("reader.bookmark.quick"))
            }
            .padding(.horizontal, 8)
            .background(palette.surface)
            .overlay(alignment: .bottom) { Divider().overlay(palette.divider) }

            Spacer(minLength: 0)

            VStack(spacing: 8) {
                HStack(spacing: 10) {
                    Button { Task { await session.goPrevious() } } label: {
                        Image(systemName: "backward.end").frame(width: 44, height: 44)
                    }
                    .accessibilityLabel(Text("reader.previous.chapter"))

                    Slider(value: $sliderValue, in: 0 ... 1) { editing in
                        sliderIsEditing = editing
                        if !editing { Task { await session.goToProgression(sliderValue) } }
                    }
                    .tint(palette.accent)
                    .accessibilityLabel(Text("reader.progress"))

                    Button { Task { await session.goNext() } } label: {
                        Image(systemName: "forward.end").frame(width: 44, height: 44)
                    }
                    .accessibilityLabel(Text("reader.next.chapter"))
                }

                HStack {
                    progressLabel
                    Spacer()
                    if session.preferences.showClock { ReaderClockView() }
                }
                .font(.caption.monospacedDigit())
                .foregroundStyle(palette.secondary)

                HStack(spacing: 0) {
                    ReaderControlButton(title: "reader.toc", systemImage: "list.bullet") { activePanel = .contents }
                    ReaderControlButton(title: "reader.notes", systemImage: "bookmark") { activePanel = .notes }
                    ReaderControlButton(title: "reader.appearance", systemImage: "textformat.size") { activePanel = .appearance }
                    ReaderControlButton(title: "reader.settings", systemImage: "gearshape") { activePanel = .settings }
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
            .padding(.bottom, 6)
            .background(palette.surface)
            .overlay(alignment: .top) { Divider().overlay(palette.divider) }
        }
        .foregroundStyle(palette.foreground)
    }

    @ViewBuilder
    private var progressLabel: some View {
        switch session.preferences.progressStyle {
        case .hidden: EmptyView()
        case .position: Text("\(Int((session.progress * 100).rounded())) / 100")
        case .remaining:
            Text(String(
                format: String(localized: "reader.progress.remaining.format"),
                Int(((1 - session.progress) * 100).rounded())
            ))
        case .auto, .percent: Text(session.progress, format: .percent.precision(.fractionLength(0)))
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
            do {
                try await session.close()
                UIApplication.shared.isIdleTimerDisabled = false
                dismiss()
            } catch { closingFailure = true }
        }
    }
}

private enum ReaderPanel: String, Identifiable {
    case contents, notes, appearance, settings
    var id: String { rawValue }
}

private struct ReaderPalette {
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

private struct ReaderControlButton: View {
    let title: LocalizedStringKey
    let systemImage: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 3) {
                Image(systemName: systemImage).font(.title3)
                Text(title).font(.caption2)
            }
            .frame(maxWidth: .infinity, minHeight: 44)
        }
        .accessibilityLabel(Text(title))
    }
}

private struct ReaderClockView: View {
    var body: some View {
        TimelineView(.periodic(from: .now, by: 60)) { context in
            Text(context.date, format: .dateTime.hour().minute())
        }
        .accessibilityLabel(Text("reader.clock"))
    }
}

private struct ReaderTOCSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var session: IosReflowableReaderSession

    var body: some View {
        NavigationStack {
            Group {
                if session.tableOfContents.isEmpty {
                    ReaderEmptyState(title: "reader.toc.empty", systemImage: "list.bullet")
                } else {
                    List(session.tableOfContents) { entry in
                        Button {
                            Task { await session.goToTOCEntry(entry); dismiss() }
                        } label: {
                            HStack {
                                Text(entry.title).padding(.leading, CGFloat(entry.depth) * 16)
                                Spacer()
                                if entry.title == session.chapterTitle {
                                    Image(systemName: "location.fill").foregroundStyle(.tint)
                                }
                            }
                            .foregroundStyle(.primary)
                        }
                    }
                }
            }
            .navigationTitle("reader.toc")
            .toolbar { closeToolbar }
        }
        .presentationDetents([.medium, .large])
    }

    @ToolbarContentBuilder private var closeToolbar: some ToolbarContent {
        ToolbarItem(placement: .confirmationAction) { Button("common.done") { dismiss() } }
    }
}

private struct ReaderNotesSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var session: IosReflowableReaderSession
    @State private var tab = 0

    var body: some View {
        NavigationStack {
            VStack {
                Picker("reader.notes", selection: $tab) {
                    Text("reader.bookmarks").tag(0)
                    Text("reader.annotations").tag(1)
                }
                .pickerStyle(.segmented)
                .padding()
                .disabled(tab == 1 || !session.capabilities.annotations)
                if tab == 0 {
                    if session.bookmarkSyncPending {
                        Text("reader.bookmarks.pending").font(.caption).foregroundStyle(.tint)
                    }
                    if session.bookmarks.isEmpty {
                        ReaderEmptyState(title: "reader.bookmarks.empty", systemImage: "bookmark")
                    } else {
                        List(session.bookmarks) { bookmark in
                            HStack {
                                Button {
                                    Task { await session.goToBookmark(id: bookmark.id); dismiss() }
                                } label: {
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(bookmark.label).lineLimit(1)
                                        Text(bookmark.percent / 100, format: .percent.precision(.fractionLength(0)))
                                            .font(.caption).foregroundStyle(.secondary)
                                    }
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                }
                                Button(role: .destructive) { session.removeBookmark(id: bookmark.id) } label: {
                                    Image(systemName: "trash")
                                }
                                .accessibilityLabel(Text("reader.bookmark.remove"))
                            }
                        }
                    }
                } else {
                    ReaderEmptyState(title: "reader.annotations", systemImage: "highlighter")
                }
            }
            .navigationTitle("reader.notes")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("common.done") { dismiss() } }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

private struct ReaderAppearanceSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var session: IosReflowableReaderSession

    var body: some View {
        NavigationStack {
            Form {
                Section("reader.settings.theme") {
                    Picker("reader.settings.theme", selection: $session.preferences.theme) {
                        ForEach(IosReaderTheme.allCases) { theme in
                            Text(verbatim: localizedReaderOption("reader.theme.\(theme.rawValue)"))
                                .tag(theme)
                        }
                    }
                    .pickerStyle(.segmented)
                    Toggle("reader.theme.system", isOn: Binding(
                        get: { session.preferences.themeMode == .system },
                        set: { session.preferences.themeMode = $0 ? .system : .manual }
                    ))
                }
                Section("reader.settings.typography") {
                    ReaderValueSlider(
                        title: "reader.settings.fontSize",
                        value: Binding(
                            get: { Double(session.preferences.fontSize) },
                            set: { session.preferences.fontSize = Int($0.rounded()) }
                        ),
                        range: 14 ... 30,
                        step: 1,
                        valueText: "\(session.preferences.fontSize)"
                    )
                    ReaderValueSlider(
                        title: "reader.settings.lineHeight",
                        value: $session.preferences.lineHeight,
                        range: 1.4 ... 2.4,
                        step: 0.1,
                        valueText: session.preferences.lineHeight.formatted(.number.precision(.fractionLength(1)))
                    )
                    Picker("reader.settings.fontFamily", selection: $session.preferences.fontFamily) {
                        ForEach(IosReaderFontFamily.allCases) { font in
                            Text(verbatim: localizedReaderOption("reader.font.\(font.rawValue)"))
                                .tag(font)
                        }
                    }
                    Picker("reader.settings.fontWeight", selection: $session.preferences.fontWeight) {
                        Text("400").tag(400); Text("500").tag(500); Text("700").tag(700)
                    }
                    ReaderValueSlider(
                        title: "reader.settings.letterSpacing",
                        value: $session.preferences.letterSpacing,
                        range: 0 ... 0.08,
                        step: 0.01,
                        valueText: session.preferences.letterSpacing.formatted(.number.precision(.fractionLength(2)))
                    )
                    Picker("reader.settings.pageMargin", selection: $session.preferences.pageMargin) {
                        ForEach(IosReaderPageMargin.allCases) { margin in
                            Text(verbatim: localizedReaderOption("reader.margin.\(margin.rawValue)"))
                                .tag(margin)
                        }
                    }
                }
            }
            .navigationTitle("reader.appearance")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("common.done") { dismiss() } } }
        }
        .presentationDetents([.large])
    }
}

private struct ReaderSettingsSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var session: IosReflowableReaderSession

    var body: some View {
        NavigationStack {
            Form {
                Section("reader.settings.interface") {
                    Picker("reader.settings.progressStyle", selection: $session.preferences.progressStyle) {
                        ForEach(IosReaderProgressStyle.allCases) { style in
                            Text(verbatim: localizedReaderOption("reader.progressStyle.\(style.rawValue)"))
                                .tag(style)
                        }
                    }
                    Toggle("reader.settings.showClock", isOn: $session.preferences.showClock)
                    Toggle("reader.settings.keepAwake", isOn: $session.preferences.keepScreenAwake)
                }
                Section("reader.settings.navigation") {
                    Picker("reader.settings.tapZones", selection: $session.preferences.tapZones) {
                        ForEach(IosReaderTapZones.allCases) { zones in
                            Text(verbatim: localizedReaderOption("reader.tapZones.\(zones.rawValue)"))
                                .tag(zones)
                        }
                    }
                    Toggle("reader.settings.swipe", isOn: $session.preferences.swipePageTurn).disabled(true)
                    Toggle("reader.settings.keyboard", isOn: $session.preferences.keyboardPageTurn)
                    Toggle("reader.settings.volumeKeys", isOn: $session.preferences.volumeKeyPageTurn).disabled(true)
                    Picker("reader.settings.pageTurnAnimation", selection: $session.preferences.pageTurnAnimation) {
                        Text("reader.animation.slide").tag("slide")
                    }
                    .disabled(true)
                }
                Section("reader.settings.layout") {
                    Picker("reader.settings.readingMode", selection: $session.preferences.readingMode) {
                        Text("reader.mode.paged").tag(IosReaderReadingMode.paged)
                        Text("reader.mode.scroll").tag(IosReaderReadingMode.continuousScroll)
                    }
                    Picker("reader.settings.spread", selection: $session.preferences.spreadMode) {
                        ForEach(IosReaderSpreadMode.allCases) { spread in
                            Text(verbatim: localizedReaderOption("reader.spread.\(spread.rawValue)"))
                                .tag(spread)
                        }
                    }
                    LabeledContent("reader.settings.pageWidth", value: "\(session.preferences.pageWidth)")
                        .disabled(true)
                }
                Section("reader.settings.paragraph") {
                    ReaderValueSlider(
                        title: "reader.settings.paragraphIndent",
                        value: $session.preferences.paragraphIndent,
                        range: 0 ... 4,
                        step: 0.5,
                        valueText: session.preferences.paragraphIndent.formatted(.number.precision(.fractionLength(1)))
                    )
                    ReaderValueSlider(
                        title: "reader.settings.paragraphSpacing",
                        value: $session.preferences.paragraphSpacing,
                        range: 0 ... 1.5,
                        step: 0.1,
                        valueText: session.preferences.paragraphSpacing.formatted(.number.precision(.fractionLength(1)))
                    )
                    Picker("reader.settings.textAlignment", selection: $session.preferences.textAlignment) {
                        ForEach(IosReaderTextAlignment.allCases) { alignment in
                            Text(verbatim: localizedReaderOption("reader.alignment.\(alignment.rawValue)"))
                                .tag(alignment)
                        }
                    }
                }
                Section("reader.settings.optimization") {
                    Toggle("reader.settings.smartOptimization", isOn: $session.preferences.smartOptimization).disabled(true)
                    Toggle("reader.settings.deduplicateIndent", isOn: $session.preferences.deduplicateIndent).disabled(true)
                    Toggle("reader.settings.indentUnindented", isOn: $session.preferences.indentUnindented).disabled(true)
                }
                Section("reader.settings.advanced") {
                    Toggle("reader.settings.publisherStyles", isOn: $session.preferences.preservePublisherStyles).disabled(true)
                    Toggle("reader.settings.publisherColors", isOn: $session.preferences.allowPublisherColors).disabled(true)
                    Toggle("reader.settings.publisherFonts", isOn: $session.preferences.allowPublisherFonts).disabled(true)
                }
                Section {
                    Button("reader.settings.reset", role: .destructive) { session.resetPreferences() }
                }
            }
            .navigationTitle("reader.settings")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("common.done") { dismiss() } } }
        }
        .presentationDetents([.large])
    }
}

private struct ReaderValueSlider: View {
    let title: LocalizedStringKey
    @Binding var value: Double
    let range: ClosedRange<Double>
    let step: Double
    let valueText: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack { Text(title); Spacer(); Text(valueText).foregroundStyle(.secondary) }
            Slider(value: $value, in: range, step: step)
        }
        .accessibilityElement(children: .combine)
    }
}

private struct ReaderEmptyState: View {
    let title: LocalizedStringKey
    let systemImage: String

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: systemImage).font(.largeTitle)
            Text(title).multilineTextAlignment(.center)
        }
        .foregroundStyle(.secondary)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(24)
    }
}
