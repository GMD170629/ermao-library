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
                if navigationFailed { Text("reader.navigation.failed").foregroundStyle(.red) }
                if session.canUndoControlBookmark {
                    Button("common.undo") { session.undoControlBookmark() }
                }
                HStack(spacing: 8) {
                    Button { Task { await session.goPrevious() } } label: {
                        Image(systemName: "backward.end").frame(width: 44, height: 44)
                    }.accessibilityLabel(Text("reader.previous")).accessibilityIdentifier("reader.previous")
                    Slider(value: $sliderValue, in: 0 ... 1) { editing in
                        sliderIsEditing = editing
                        if !editing { Task { navigationFailed = !(await session.seekControlProgress(sliderValue)) } }
                    }.tint(palette.accent).accessibilityLabel(Text("reader.progress")).accessibilityIdentifier("reader.progress")
                    Button { Task { await session.goNext() } } label: {
                        Image(systemName: "forward.end").frame(width: 44, height: 44)
                    }.accessibilityLabel(Text("reader.next")).accessibilityIdentifier("reader.next")
                }
                HStack {
                    progressLabel
                    Spacer()
                    if editor.draft.showClock { ReaderClockView() }
                }.font(.caption.monospacedDigit()).foregroundStyle(palette.secondary)
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
            case .appearance: ReaderAppearanceSheet(session: session, editor: editor)
            case .settings: ReaderSettingsSheet(session: session, editor: editor)
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

    @ViewBuilder private var progressLabel: some View {
        switch editor.draft.progressStyle {
        case .hidden: EmptyView()
        case .position: Text(session.controlPosition)
        case .remaining:
            Text(String(format: String(localized: "reader.progress.remaining.format"), locale: .current, Int(((1 - session.progress) * 100).rounded())))
        case .auto, .percent: Text(session.progress, format: .percent.precision(.fractionLength(0)))
        }
    }
}

struct ReaderFixedLayoutSettings: View {
    @ObservedObject var editor: IosReaderPreferenceEditor
    let morphology: ErmaoShared.ReaderMorphology
    var body: some View {
        Section("reader.settings.layout") {
            if morphology == .comic {
                Picker("reader.settings.readingMode", selection: editor.binding(\.comicFlow)) {
                    Text("reader.mode.paged").tag(IosComicFlow.paginated)
                    Text("reader.mode.scroll").tag(IosComicFlow.scrolled)
                }
                Picker("reader.settings.spread", selection: editor.binding(\.comicSpread)) {
                    Text("reader.spread.single").tag(IosComicSpread.single)
                    Text("reader.spread.double").tag(IosComicSpread.double)
                }
                Picker("reader.settings.comicDirection", selection: editor.binding(\.comicDirection)) {
                    Text(verbatim: "LTR").tag(IosComicDirection.ltr)
                    Text(verbatim: "RTL").tag(IosComicDirection.rtl)
                }
                Toggle("reader.settings.coverSingle", isOn: editor.binding(\.comicCoverSingle))
                Picker("reader.settings.pageGap", selection: editor.binding(\.comicPageGap)) {
                    ForEach([0, 8, 16, 24], id: \.self) { Text($0, format: .number).tag($0) }
                }
            } else {
                LabeledContent("reader.settings.pdfZoom", value: editor.draft.pdfZoom.formatted(.percent))
                Picker("reader.settings.pdfFit", selection: editor.binding(\.pdfFit)) {
                    Text("reader.settings.pdfFit.page").tag(IosPdfFit.page)
                    Text("reader.settings.pdfFit.width").tag(IosPdfFit.width)
                }
                Picker("reader.settings.pdfRotation", selection: editor.binding(\.pdfRotation)) {
                    ForEach([0, 90, 180, 270], id: \.self) { Text($0, format: .number).tag($0) }
                }
                Picker("reader.settings.pdfCrop", selection: editor.binding(\.pdfCropMargins)) {
                    Text("reader.settings.pdfCrop.off").tag(IosPdfCropMargins.off)
                    Text("reader.settings.pdfCrop.auto").tag(IosPdfCropMargins.auto)
                }
            }
        }.disabled(true)
    }
}
