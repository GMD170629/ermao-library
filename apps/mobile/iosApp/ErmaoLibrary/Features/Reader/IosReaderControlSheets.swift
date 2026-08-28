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

struct ReaderPreferenceSheet<Session: IosReaderControlSession>: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var session: Session
    @ObservedObject var editor: IosReaderPreferenceEditor
    let panel: String
    @State private var advanced = false

    private var sections: [ReaderSettingSection] {
        ReaderSettingsCatalog.shared.sections.filter { section in
            section.panel == panel && !settings(in: section).isEmpty
        }
    }

    private func settings(in section: ReaderSettingSection) -> [ReaderSettingDefinition] {
        ReaderSettingsCatalog.shared.settings.filter { $0.section == section.id && $0.formats.contains(session.controlMorphology) }
    }

    var body: some View {
        NavigationStack {
            Form {
                if editor.applyFailed { Text("reader.preferences.apply.failed").foregroundStyle(.red).accessibilityIdentifier("reader.preferences.failure") }
                ForEach(sections.filter { !$0.advanced && $0.id != "reset" }, id: \.id) { section in
                    catalogSection(section)
                }
                if panel == "settings" {
                    DisclosureGroup("reader.settings.advanced", isExpanded: $advanced) {
                        ForEach(sections.filter { $0.advanced }, id: \.id) { section in catalogSection(section) }
                    }
                    Button(LocalizedStringKey("reader.catalog.reset"), role: .destructive) { editor.reset() }
                }
            }
            .navigationTitle(panel == "appearance" ? "reader.appearance" : "reader.settings")
            .accessibilityIdentifier("reader.panel.\(panel)")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("common.done") { dismiss() }.accessibilityIdentifier("reader.panel.done") } }
        }
        .presentationDetents([.large])
    }

    @ViewBuilder private func catalogSection(_ section: ReaderSettingSection) -> some View {
        Section {
            ForEach(settings(in: section), id: \.id) { setting in settingRow(setting) }
        } header: {
            if !section.chinese.isEmpty { Text(LocalizedStringKey(section.key)) }
        }
    }

    @ViewBuilder private func settingRow(_ setting: ReaderSettingDefinition) -> some View {
        let available = setting.control.map { session.isEnabled($0) } ?? true
        let stored = editor.draft.settingValue(setting)
        let value = setting.options.first { option in
            option.value == stored || Double(option.value).map { $0 == Double(stored) } == true
        }?.value ?? stored
        let displayedValue = Double(value)?.formatted(.number.precision(.fractionLength(0 ... 4))) ?? value
        let fixedSwipe = setting.id == "swipePageTurn" && !available
        let binding = Binding(get: { value }, set: { editor.changeSetting(setting, value: $0) })
        VStack(alignment: .leading, spacing: 6) {
            if setting.kind == "toggle" {
                Toggle(LocalizedStringKey(setting.key), isOn: Binding(
                    get: { fixedSwipe || available && (stored == "true" || stored == "system") },
                    set: { editor.changeSetting(setting, value: setting.id == "themeMode" ? ($0 ? "system" : "manual") : String($0)) }
                )).disabled(!available)
            } else if setting.kind == "number" {
                ReaderValueSlider(
                    title: LocalizedStringKey(setting.key),
                    value: Binding(get: { Double(stored) ?? setting.minimum }, set: { number in
                        let value = setting.step >= 1 ? String(Int(number.rounded())) : String((number * 100).rounded() / 100)
                        editor.changeSetting(setting, value: value)
                    }),
                    range: setting.minimum ... setting.maximum,
                    step: setting.step,
                    valueText: (Double(stored) ?? 0).formatted(),
                    identifier: "reader.setting.\(setting.id)"
                ).disabled(!available)
            } else {
                Picker(LocalizedStringKey(setting.key), selection: binding) {
                    ForEach(setting.options, id: \.value) { option in
                        Text(LocalizedStringKey(option.key)).tag(option.value)
                            .disabled(setting.id == "letterSpacing" && (Double(option.value) ?? 0) < 0 && !session.isEnabled(.negativeletterspacing))
                    }
                    if !setting.options.contains(where: { $0.value == value }) {
                        Text(verbatim: displayedValue).tag(value)
                    }
                }.disabled(!available)
            }
            if setting.id == "pdfFit" { Text("reader.pdf.fit.unavailable").font(.caption).foregroundStyle(.secondary) }
            if fixedSwipe { Text("reader.settings.swipeFixed").font(.caption).foregroundStyle(.secondary) }
            if !available && !fixedSwipe {
                let contextual = setting.control.map { session.platformControlEnabled($0) } ?? false
                Text(String(format: String(localized: contextual ? "reader.settings.contextUnavailable" : "reader.catalog.unavailable"), localizedReaderOption(setting.key), displayedValue))
                    .font(.caption).foregroundStyle(.secondary)
            }
            if setting.id == "letterSpacing" && !session.isEnabled(.negativeletterspacing) {
                Text("reader.settings.negativeSpacingRetained").font(.caption).foregroundStyle(.secondary)
            }
            if setting.id == "fontFamily" { Text("reader.settings.fontMapping").font(.caption).foregroundStyle(.secondary) }
        }
        .accessibilityIdentifier(setting.id == "preservePublisherStyles" ? "reader.setting.publisherStyles" : "reader.setting.\(setting.id)")
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
