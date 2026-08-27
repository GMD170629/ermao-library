import SwiftUI
@preconcurrency import ErmaoShared

struct ReaderControlButton: View {
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

struct ReaderClockView: View {
    var body: some View {
        TimelineView(.periodic(from: .now, by: 60)) { context in
            Text(context.date, format: .dateTime.hour().minute())
        }
        .accessibilityLabel(Text("reader.clock"))
    }
}

struct ReaderTOCSheet<Session: IosReaderControlSession>: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var session: Session
    @State private var pendingEntryID: String?
    @State private var navigationFailed = false

    var body: some View {
        NavigationStack {
            Group {
                if session.controlContents.isEmpty {
                    ReaderEmptyState(title: "reader.toc.empty", systemImage: "list.bullet")
                } else {
                    List {
                        if navigationFailed {
                            Text("reader.navigation.failed").foregroundStyle(.red)
                        }
                        ForEach(session.controlContents) { entry in
                        Button {
                            Task {
                                pendingEntryID = entry.id
                                navigationFailed = false
                                if await session.goToTOCEntry(entry) { dismiss() }
                                else { navigationFailed = true }
                                pendingEntryID = nil
                            }
                        } label: {
                            HStack {
                                Text(entry.title).padding(.leading, CGFloat(entry.depth) * 16)
                                Spacer()
                                if entry.title == session.chapterTitle {
                                    Image(systemName: "location.fill").foregroundStyle(.tint)
                                }
                                if pendingEntryID == entry.id { ProgressView() }
                            }
                            .foregroundStyle(.primary)
                        }
                        .disabled(pendingEntryID != nil)
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
        ToolbarItem(placement: .confirmationAction) { Button("common.done") { dismiss() }.accessibilityIdentifier("reader.panel.done") }
    }
}

struct ReaderNotesSheet<Session: IosReaderControlSession>: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var session: Session
    @State private var tab = 0
    @State private var navigationFailed = false

    var body: some View {
        NavigationStack {
            VStack {
                if navigationFailed { Text("reader.navigation.failed").foregroundStyle(.red) }
                Picker("reader.notes", selection: $tab) {
                    Text("reader.bookmarks").tag(0)
                    Text("reader.annotations").tag(1)
                }
                .pickerStyle(.segmented)
                .padding()
                .disabled(tab == 1 || !session.isEnabled(.annotations))
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
                                    Task {
                                        if await session.goToBookmark(id: bookmark.id) { dismiss() }
                                        else { navigationFailed = true }
                                    }
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
                ToolbarItem(placement: .confirmationAction) { Button("common.done") { dismiss() }.accessibilityIdentifier("reader.panel.done") }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

struct ReaderAppearanceSheet<Session: IosReaderControlSession>: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var session: Session
    @ObservedObject var editor: IosReaderPreferenceEditor

    var body: some View {
        NavigationStack {
            Form {
                if editor.applyFailed { Text("reader.preferences.apply.failed").foregroundStyle(.red).accessibilityIdentifier("reader.preferences.failure") }
                if editor.isApplying { ProgressView().accessibilityIdentifier("reader.preferences.applying") }
                Section("reader.settings.theme") {
                    Picker("reader.settings.theme", selection: Binding(
                        get: { editor.draft.theme },
                        set: { theme in editor.change { $0.theme = theme; $0.themeMode = .manual } }
                    )) {
                        ForEach(IosReaderTheme.allCases) { theme in
                            Text(verbatim: localizedReaderOption("reader.theme.\(theme.rawValue)"))
                                .tag(theme)
                        }
                    }
                    .pickerStyle(.segmented)
                    Toggle("reader.theme.system", isOn: Binding(
                        get: { editor.draft.themeMode == .system },
                        set: { value in editor.change { $0.themeMode = value ? .system : .manual } }
                    ))
                }
                if session.controlMorphology == .reflowable {
                Section("reader.settings.typography") {
                    ReaderValueSlider(
                        title: "reader.settings.fontSize",
                        value: Binding(
                            get: { Double(editor.draft.fontSize) },
                            set: { value in editor.change { $0.fontSize = Int(value.rounded()) } }
                        ),
                        range: 14 ... 30,
                        step: 1,
                        valueText: "\(editor.draft.fontSize)",
                        identifier: "reader.setting.fontSize"
                    )
                    .disabled(!session.isEnabled(.fontsize))
                    ReaderValueSlider(
                        title: "reader.settings.lineHeight",
                        value: editor.binding(\.lineHeight),
                        range: 1.4 ... 2.4,
                        step: 0.1,
                        valueText: editor.draft.lineHeight.formatted(.number.precision(.fractionLength(1)))
                    )
                    .disabled(!session.isEnabled(.lineheight))
                    .accessibilityIdentifier("reader.setting.lineHeight")
                    Picker("reader.settings.fontFamily", selection: editor.binding(\.fontFamily)) {
                        ForEach(IosReaderFontFamily.allCases) { font in
                            Text(verbatim: localizedReaderOption("reader.font.\(font.rawValue)"))
                                .tag(font)
                        }
                    }.disabled(!session.isEnabled(.fontfamily))
                    Text("reader.settings.fontMapping").font(.caption).foregroundStyle(.secondary)
                    Picker("reader.settings.fontWeight", selection: editor.binding(\.fontWeight)) {
                        Text("400").tag(400); Text("500").tag(500); Text("700").tag(700)
                    }.disabled(!session.isEnabled(.fontweight))
                    ReaderValueSlider(
                        title: "reader.settings.letterSpacing",
                        value: editor.binding(\.letterSpacing),
                        range: 0 ... 0.08,
                        step: 0.01,
                        valueText: editor.draft.letterSpacing.formatted(.number.precision(.fractionLength(2)))
                    )
                    .disabled(!session.isEnabled(.letterspacing))
                    if editor.draft.letterSpacing < 0 {
                        Text("reader.settings.negativeSpacingRetained").font(.caption).foregroundStyle(.secondary)
                    }
                    LabeledContent("reader.settings.negativeLetterSpacing", value: "−0.02").foregroundStyle(.secondary).disabled(true)
                    Picker("reader.settings.pageMargin", selection: editor.binding(\.pageMargin)) {
                        ForEach(IosReaderPageMargin.allCases) { margin in
                            Text(verbatim: localizedReaderOption("reader.margin.\(margin.rawValue)"))
                                .tag(margin)
                        }
                    }.disabled(!session.isEnabled(.pagemargins))
                }
                }
            }
            .navigationTitle("reader.appearance")
            .accessibilityIdentifier("reader.panel.appearance")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("common.done") { dismiss() }.accessibilityIdentifier("reader.panel.done") } }
        }
        .presentationDetents([.large])
    }
}

struct ReaderSettingsSheet<Session: IosReaderControlSession>: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var session: Session
    @ObservedObject var editor: IosReaderPreferenceEditor

    var body: some View {
        NavigationStack {
            Form {
                if editor.applyFailed { Text("reader.preferences.apply.failed").foregroundStyle(.red).accessibilityIdentifier("reader.preferences.failure") }
                if editor.isApplying { ProgressView().accessibilityIdentifier("reader.preferences.applying") }
                Section("reader.settings.interface") {
                    Picker("reader.settings.progressStyle", selection: editor.binding(\.progressStyle)) {
                        ForEach(IosReaderProgressStyle.allCases) { style in
                            Text(verbatim: localizedReaderOption("reader.progressStyle.\(style.rawValue)"))
                                .tag(style)
                        }
                    }
                    Toggle("reader.settings.showClock", isOn: editor.binding(\.showClock))
                    Toggle("reader.settings.keepAwake", isOn: editor.binding(\.keepScreenAwake))
                }
                Section("reader.settings.navigation") {
                    Picker("reader.settings.tapZones", selection: editor.binding(\.tapZones)) {
                        ForEach(IosReaderTapZones.allCases) { zones in
                            Text(verbatim: localizedReaderOption("reader.tapZones.\(zones.rawValue)"))
                                .tag(zones)
                        }
                    }
                    Toggle("reader.settings.gestureAnimation", isOn: .constant(true)).disabled(true)
                    Toggle("reader.settings.swipe", isOn: editor.binding(\.swipePageTurn)).disabled(true)
                    Toggle("reader.settings.keyboard", isOn: editor.binding(\.keyboardPageTurn)).disabled(!session.isEnabled(.keyboard))
                    Toggle("reader.settings.volumeKeys", isOn: editor.binding(\.volumeKeyPageTurn)).disabled(true)
                    Picker("reader.settings.pageTurnAnimation", selection: editor.binding(\.pageTurnAnimation)) {
                        Text("reader.animation.slide").tag("slide")
                        Text("reader.animation.off").tag("off")
                    }
                    .disabled(!session.isEnabled(.commandanimation))
                }
                if session.controlMorphology == .reflowable {
                Section("reader.settings.layout") {
                    Picker("reader.settings.readingMode", selection: editor.binding(\.readingMode)) {
                        Text("reader.mode.paged").tag(IosReaderReadingMode.paged)
                        Text("reader.mode.scroll").tag(IosReaderReadingMode.continuousScroll)
                    }.disabled(!session.isEnabled(.readingmode))
                    Picker("reader.settings.spread", selection: editor.binding(\.spreadMode)) {
                        ForEach([IosReaderSpreadMode.single, .double]) { spread in
                            Text(verbatim: localizedReaderOption("reader.spread.\(spread.rawValue)"))
                                .tag(spread)
                        }
                    }.disabled(!session.isEnabled(.spread))
                    LabeledContent("reader.settings.pageWidth", value: "\(editor.draft.pageWidth)")
                        .disabled(true)
                }
                Section("reader.settings.paragraph") {
                    ReaderValueSlider(
                        title: "reader.settings.paragraphIndent",
                        value: editor.binding(\.paragraphIndent),
                        range: 0 ... 4,
                        step: 0.5,
                        valueText: editor.draft.paragraphIndent.formatted(.number.precision(.fractionLength(1)))
                    )
                    .disabled(!session.isEnabled(.paragraphindent))
                    ReaderValueSlider(
                        title: "reader.settings.paragraphSpacing",
                        value: editor.binding(\.paragraphSpacing),
                        range: 0 ... 1.5,
                        step: 0.1,
                        valueText: editor.draft.paragraphSpacing.formatted(.number.precision(.fractionLength(1)))
                    )
                    .disabled(!session.isEnabled(.paragraphspacing))
                    Picker("reader.settings.textAlignment", selection: editor.binding(\.textAlignment)) {
                        ForEach(IosReaderTextAlignment.allCases) { alignment in
                            Text(verbatim: localizedReaderOption("reader.alignment.\(alignment.rawValue)"))
                                .tag(alignment)
                        }
                    }.disabled(!session.isEnabled(.textalignment))
                }
                Section("reader.settings.optimization") {
                    Toggle("reader.settings.smartOptimization", isOn: editor.binding(\.smartOptimization)).disabled(true)
                    Toggle("reader.settings.deduplicateIndent", isOn: editor.binding(\.deduplicateIndent)).disabled(true)
                    Toggle("reader.settings.indentUnindented", isOn: editor.binding(\.indentUnindented)).disabled(true)
                }
                Section("reader.settings.advanced") {
                    Toggle("reader.settings.publisherStyles", isOn: editor.binding(\.preservePublisherStyles)).disabled(!session.isEnabled(.publisherstyles)).accessibilityIdentifier("reader.setting.publisherStyles")
                    Toggle("reader.settings.publisherColors", isOn: editor.binding(\.allowPublisherColors)).disabled(true)
                    Toggle("reader.settings.publisherFonts", isOn: editor.binding(\.allowPublisherFonts)).disabled(true)
                }
                } else {
                    ReaderFixedLayoutSettings(editor: editor, morphology: session.controlMorphology)
                }
                Section {
                    Button("reader.settings.reset", role: .destructive) { editor.reset(morphology: session.controlMorphology) }
                }
            }
            .navigationTitle("reader.settings")
            .accessibilityIdentifier("reader.panel.settings")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("common.done") { dismiss() }.accessibilityIdentifier("reader.panel.done") } }
        }
        .presentationDetents([.large])
    }
}

struct ReaderValueSlider: View {
    let title: LocalizedStringKey
    @Binding var value: Double
    let range: ClosedRange<Double>
    let step: Double
    let valueText: String
    var identifier: String = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack { Text(title); Spacer(); Text(valueText).foregroundStyle(.secondary) }
            Slider(value: $value, in: range, step: step)
                .accessibilityLabel(Text(title))
                .accessibilityValue(Text(valueText))
                .accessibilityIdentifier(identifier)
        }
        .accessibilityElement(children: .contain)
    }
}

struct ReaderEmptyState: View {
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
