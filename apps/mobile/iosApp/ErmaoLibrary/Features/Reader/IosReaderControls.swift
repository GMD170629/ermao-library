import SwiftUI
@preconcurrency import ErmaoShared

struct IosReaderControls<Session: IosReaderControlSession>: View {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.scenePhase) private var scenePhase
    @ObservedObject var session: Session
    @StateObject private var editor: IosReaderPreferenceEditor
    let onClose: () -> Void
    @State private var sliderValue = 0.0
    @State private var sliderIsEditing = false
    @State private var navigationFailed = false
    @State private var trigger: IosReaderPanel?
    @AccessibilityFocusState private var focusedPanel: IosReaderPanel?
    @FocusState private var keyboardPanel: IosReaderPanel?

    init(session: Session, onClose: @escaping () -> Void) {
        self.session = session
        self.onClose = onClose
        _editor = StateObject(wrappedValue: IosReaderPreferenceEditor(preferences: session.preferences, apply: { updated in
            await session.applyControlPreferences(updated)
        }))
    }

    private var palette: ReaderPalette {
        ReaderPalette(theme: editor.draft.resolvedTheme(for: colorScheme == .dark ? .dark : .light))
    }

    private func physicalTurn(
        _ side: ErmaoShared.ReaderPhysicalHorizontalSide
    ) -> ErmaoShared.ReaderPageTurnDirection {
        ErmaoShared.ReaderNavigationPolicy.shared.physicalHorizontalPageTurn(
            side: side,
            readingProgression: editor.draft.readingProgression.shared
        )
    }

    private var leftChapter: IosReaderTocEntry? {
        physicalTurn(.left) == .previous
            ? session.controlAdjacentChapters.previous
            : session.controlAdjacentChapters.next
    }

    private var rightChapter: IosReaderTocEntry? {
        physicalTurn(.right) == .previous
            ? session.controlAdjacentChapters.previous
            : session.controlAdjacentChapters.next
    }

    private func activate(_ side: ErmaoShared.ReaderPhysicalHorizontalSide) async {
        if session.controlMorphology == .reflowable {
            guard let chapter = side == .left ? leftChapter : rightChapter else { return }
            navigationFailed = !(await session.goToTOCEntry(chapter))
        } else if side == .left {
            await session.goPrevious()
        } else {
            await session.goNext()
        }
    }

    private func progressControlLabel(_ side: ErmaoShared.ReaderPhysicalHorizontalSide) -> String {
        guard session.controlMorphology == .reflowable else {
            return side == .left ? "reader.previous" : "reader.next"
        }
        return physicalTurn(side) == .previous ? "reader.previous.chapter" : "reader.next.chapter"
    }

    private var toolbar: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Button { Task { await editor.flush(); onClose() } } label: {
                    Image(systemName: "chevron.backward").frame(width: 44, height: 44)
                }.accessibilityLabel(Text("reader.close")).accessibilityIdentifier("reader.close")
                VStack(spacing: 2) {
                    Text(session.chapterTitle ?? session.displayTitle).font(.headline).lineLimit(1)
                    if session.chapterTitle != nil { Text(session.displayTitle).font(.caption).lineLimit(1) }
                }.frame(maxWidth: .infinity)
                Group {
                    Button { Task { await session.toggleCurrentBookmark() } } label: {
                        Image(systemName: session.currentBookmarkActive ? "bookmark.fill" : "bookmark").frame(width: 44, height: 44)
                    }.accessibilityLabel(Text("reader.bookmark.quick"))
                        .disabled(!session.isEnabled(.bookmarks))
                }
                if session.controlMorphology == .pdf {
                    Button { session.zoomControl(-1) } label: { Image(systemName: "minus.magnifyingglass").frame(width: 44, height: 44) }
                        .accessibilityLabel(Text("reader.pdf.zoom.out"))
                    Button { session.zoomControl(0) } label: { Image(systemName: "arrow.down.right.and.arrow.up.left").frame(width: 44, height: 44) }
                        .accessibilityLabel(Text("reader.pdf.zoom.fit"))
                    Button { session.zoomControl(1) } label: { Image(systemName: "plus.magnifyingglass").frame(width: 44, height: 44) }
                        .accessibilityLabel(Text("reader.pdf.zoom.in"))
                }
            }.padding(.horizontal, 8).background(palette.surface)
            Spacer(minLength: 0)
            VStack(spacing: 8) {
                if navigationFailed {
                    Text("reader.navigation.failed")
                        .foregroundStyle(.red)
                        .accessibilityIdentifier("reader.navigation.failed")
                }
                if session.canUndoControlBookmark {
                    Button("common.undo") { session.undoControlBookmark() }
                }
                HStack(spacing: 8) {
                    Button { Task { await activate(.left) } } label: {
                        Image(systemName: "chevron.left").frame(width: 44, height: 44)
                    }.accessibilityLabel(Text(LocalizedStringKey(progressControlLabel(.left))))
                        .accessibilityIdentifier(progressControlLabel(.left))
                        .disabled(session.controlMorphology == .reflowable && leftChapter == nil)
                    Slider(value: $sliderValue, in: 0 ... 1) { editing in
                        sliderIsEditing = editing
                        if !editing { Task { navigationFailed = !(await session.seekControlProgress(sliderValue)) } }
                    }.tint(palette.accent).accessibilityLabel(Text("reader.progress")).accessibilityIdentifier("reader.progress")
                    Button { Task { await activate(.right) } } label: {
                        Image(systemName: "chevron.right").frame(width: 44, height: 44)
                    }.accessibilityLabel(Text(LocalizedStringKey(progressControlLabel(.right))))
                        .accessibilityIdentifier(progressControlLabel(.right))
                        .disabled(session.controlMorphology == .reflowable && rightChapter == nil)
                }
                HStack(spacing: 0) {
                    panelButton(.contents, title: "reader.toc", image: "list.bullet")
                    panelButton(.bookmarks, title: "reader.bookmarks", image: "bookmark")
                        .disabled(!session.isEnabled(.bookmarks))
                    panelButton(.appearance, title: "reader.appearance", image: "textformat.size")
                    panelButton(.settings, title: "reader.settings", image: "gearshape")
                }
            }.padding(.horizontal, 16).padding(.vertical, 8).background(palette.surface)
        }
        .foregroundStyle(palette.foreground)
        .tint(palette.accent)
    }

    var body: some View {
        ZStack {
            if session.controlsVisible { toolbar }
        }
        .onAppear { sliderValue = session.progress }
        .task(id: scenePhase) { if scenePhase == .background { await editor.flush() } }
        .onChange(of: session.progress) { _, value in if !sliderIsEditing { sliderValue = value } }
        .onChange(of: editor.draft.keepScreenAwake) { _, value in UIApplication.shared.isIdleTimerDisabled = value }
        .sheet(item: $session.activeControlPanel, onDismiss: {
            focusedPanel = trigger
            keyboardPanel = trigger
        }) { panel in
            switch panel {
            case .contents: ReaderTOCSheet(session: session)
            case .bookmarks: ReaderNotesSheet(session: session)
            case .appearance: ReaderPreferenceSheet(session: session, editor: editor, panel: "appearance")
            case .settings: ReaderPreferenceSheet(session: session, editor: editor, panel: "settings")
            }
        }
    }

    private func panelButton(_ panel: IosReaderPanel, title: LocalizedStringKey, image: String) -> some View {
        ReaderControlButton(title: title, systemImage: image) {
            trigger = panel
            session.activeControlPanel = panel
        }
        .accessibilityIdentifier(panel == .contents ? "reader.toc" : "reader.\(panel.rawValue)")
        .accessibilityFocused($focusedPanel, equals: panel)
        .focused($keyboardPanel, equals: panel)
    }

}

struct IosReaderContentStatusLayout<Session: IosReaderControlSession, Content: View>: View {
    @ObservedObject var session: Session
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(spacing: 0) {
            content().frame(maxHeight: .infinity)
            if session.controlReady &&
                (session.preferences.progressStyle != .hidden || session.preferences.showClock) {
                IosReaderPassiveStatus(session: session)
                    .opacity(session.controlsVisible ? 0 : 1)
                    .accessibilityHidden(session.controlsVisible)
            }
        }
    }
}

private struct IosReaderPassiveStatus<Session: IosReaderControlSession>: View {
    @Environment(\.colorScheme) private var colorScheme
    @ObservedObject var session: Session

    private var palette: ReaderPalette {
        ReaderPalette(theme: session.preferences.resolvedTheme(for: colorScheme == .dark ? .dark : .light))
    }

    var body: some View {
        HStack(spacing: 12) {
            progressLabel
            Spacer(minLength: 12)
            if session.preferences.showClock { ReaderClockView() }
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 20)
        .padding(.vertical, 6)
        .font(.caption.monospacedDigit())
        .foregroundStyle(palette.secondary)
        .background(palette.background)
        .allowsHitTesting(false)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("reader.passive.status")
    }

    @ViewBuilder private var progressLabel: some View {
        switch session.preferences.progressStyle {
        case .hidden: EmptyView()
        case .position: Text(session.controlPosition)
        case .remaining:
            Text(String(
                format: String(localized: "reader.progress.remaining.format"),
                locale: .current,
                Int(((1 - session.progress) * 100).rounded())
            ))
        case .auto, .percent:
            Text(session.progress, format: .percent.precision(.fractionLength(0)))
        }
    }
}
