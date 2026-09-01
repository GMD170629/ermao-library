import Combine
import SwiftUI
@preconcurrency import ErmaoShared

/// Native presentation contract. No navigator or SDK object crosses this boundary.
@MainActor
protocol IosReaderControlSession: ObservableObject {
    var controlMorphology: ErmaoShared.ReaderMorphology { get }
    var controlReady: Bool { get }
    var activeControlPanel: IosReaderPanel? { get set }
    var controlsVisible: Bool { get set }
    var displayTitle: String { get }
    var chapterTitle: String? { get }
    var progress: Double { get }
    var controlPosition: String { get }
    var preferences: IosReaderPreferences { get }
    var controlContents: [IosReaderTocEntry] { get }
    var controlAdjacentChapters: IosReaderAdjacentChapters { get }
    var bookmarks: [IosReaderBookmarkRecord] { get }
    var bookmarkSyncPending: Bool { get }
    var currentBookmarkActive: Bool { get }
    func isEnabled(_ control: ErmaoShared.ReaderControl) -> Bool
    func applyControlPreferences(_ updated: IosReaderPreferences) async -> Bool
    func goPrevious() async
    func goNext() async
    func seekControlProgress(_ progress: Double) async -> Bool
    func goToTOCEntry(_ entry: IosReaderTocEntry) async -> Bool
    func toggleCurrentBookmark() async
    func removeBookmark(id: String)
    func goToBookmark(id: String) async -> Bool
    func undoControlBookmark()
    var canUndoControlBookmark: Bool { get }
    func zoomControl(_ direction: Int)
}

enum IosReaderPanel: String, Identifiable {
    case contents, bookmarks, appearance, settings
    var id: String { rawValue }
    var shared: ErmaoShared.ReaderPanel {
        switch self {
        case .contents: .contents
        case .bookmarks: .bookmarks
        case .appearance: .appearance
        case .settings: .settings
        }
    }
}

extension IosReaderControlSession {
    var chapterTitle: String? { nil }
    var bookmarks: [IosReaderBookmarkRecord] { [] }
    var controlAdjacentChapters: IosReaderAdjacentChapters { IosReaderAdjacentChapters() }
    var bookmarkSyncPending: Bool { false }
    var currentBookmarkActive: Bool { false }
    var canUndoControlBookmark: Bool { false }
    func undoControlBookmark() {}
    func toggleCurrentBookmark() async {}
    func removeBookmark(id: String) {}
    func goToBookmark(id: String) async -> Bool { false }
    func zoomControl(_ direction: Int) {}

    func platformControlEnabled(_ control: ErmaoShared.ReaderControl, unavailable: Set<ErmaoShared.ReaderControl> = []) -> Bool {
        guard let payload = try? preferences.canonicalJSON(),
              let sharedPreferences = try? ReaderPreferencesJson.shared.decode(payload: payload)
        else { return false }
        return ErmaoShared.ReaderSettingsCatalog.shared.resolveReaderControl(
            control: control, morphology: controlMorphology,
            capabilities: ErmaoShared.PublicKt.readerPlatformCapabilities(
                morphology: controlMorphology,
                volumeKeys: false,
                pdfZoom: controlMorphology == .pdf,
                pdfFit: false
            ),
            preferences: sharedPreferences, ready: controlReady,
            nativeUnavailable: unavailable
        ) == .available
    }

    func canApplyControlPreferences(_ updated: IosReaderPreferences) -> Bool {
        if updated == IosReaderPreferences() { return true }
        return updated.changedControls(from: preferences).allSatisfy(isEnabled)
    }

    func routeControlTap(fraction: CGFloat) {
        guard activeControlPanel == nil else { return }
        if preferences.tapZones == .disabled || (0.3 ... 0.7).contains(fraction) {
            controlsVisible.toggle()
            return
        }
        let previous = (fraction < 0.3) != (preferences.tapZones == .reversed)
        Task { if previous { await goPrevious() } else { await goNext() } }
    }
}

struct IosReaderAdjacentChapters: Equatable, Sendable {
    let previous: IosReaderTocEntry?
    let next: IosReaderTocEntry?

    init(previous: IosReaderTocEntry? = nil, next: IosReaderTocEntry? = nil) {
        self.previous = previous
        self.next = next
    }
}

func resolveIosReaderAdjacentChapters(
    entries: [IosReaderTocEntry],
    currentHref: String?,
    fragments: Set<String> = [],
    cssSelector: String? = nil,
    currentTitle: String? = nil
) -> IosReaderAdjacentChapters {
    guard !entries.isEmpty else { return IosReaderAdjacentChapters() }
    let titled = currentTitle.flatMap { title in
        entries.indices.filter { entries[$0].title == title }.only
    }
    let anchored = currentHref.flatMap { href in
        entries.indices.filter { index in
            guard let expected = entries[index].href else { return false }
            return ErmaoShared.PublicKt.matchesReaderNavigationHref(
                currentHref: href,
                expectedHref: expected,
                fragments: fragments,
                cssSelector: cssSelector
            )
        }.last
    }
    let sameResource = currentHref.flatMap { href in
        entries.indices.filter { index in
            entries[index].href?.substringBeforeFragment == href.substringBeforeFragment
        }.only
    }
    guard let currentIndex = titled ?? anchored ?? sameResource else {
        return IosReaderAdjacentChapters()
    }
    return IosReaderAdjacentChapters(
        previous: entries.indices.contains(currentIndex - 1) ? entries[currentIndex - 1] : nil,
        next: entries.indices.contains(currentIndex + 1) ? entries[currentIndex + 1] : nil
    )
}

private extension Collection {
    var only: Element? { count == 1 ? first : nil }
}

private extension String {
    var substringBeforeFragment: String { split(separator: "#", maxSplits: 1).first.map(String.init) ?? self }
}

/// One owned writer coalesces slider changes while retaining the final requested value.
@MainActor
final class IosReaderPreferenceEditor: ObservableObject {
    @Published private(set) var draft: IosReaderPreferences
    @Published private(set) var applyFailed = false
    private var committed: IosReaderPreferences
    private var pending: IosReaderPreferences?
    private var writer: Task<Void, Never>?
    private let apply: @MainActor (IosReaderPreferences) async -> Bool

    init(preferences: IosReaderPreferences, apply: @escaping @MainActor (IosReaderPreferences) async -> Bool) {
        draft = preferences
        committed = preferences
        self.apply = apply
    }

    func binding<Value>(_ key: WritableKeyPath<IosReaderPreferences, Value>) -> Binding<Value> {
        Binding(get: { self.draft[keyPath: key] }, set: { value in self.change { $0[keyPath: key] = value } })
    }

    func change(_ mutation: (inout IosReaderPreferences) -> Void) {
        mutation(&draft)
        pending = draft
        guard writer == nil else { return }
        writer = Task { [self] in
            while let requested = pending {
                pending = nil
                if await apply(requested) {
                    committed = requested
                    applyFailed = false
                } else {
                    // Do not replay a later draft based on a failed setting transaction.
                    pending = nil
                    draft = committed
                    applyFailed = true
                }
            }
            writer = nil
        }
    }

    func flush() async { await writer?.value }

    func changeSetting(_ setting: ReaderSettingDefinition, value: String) {
        do {
            let updated = try draft.changing(setting, value: value)
            change { $0 = updated }
        } catch { applyFailed = true }
    }

    func reset() { change { $0 = IosReaderPreferences() } }
}

extension IosReaderPreferences {
    func changedControls(from previous: Self) -> Set<ErmaoShared.ReaderControl> {
        let changes: [(Bool, ErmaoShared.ReaderControl)] = [
            (theme != previous.theme, .theme),
            (themeMode != previous.themeMode, .systemtheme),
            (progressStyle != previous.progressStyle, .progressstyle),
            (showClock != previous.showClock, .clock),
            (tapZones != previous.tapZones, .tapzones),
            (swipePageTurn != previous.swipePageTurn, .swipe),
            (keyboardPageTurn != previous.keyboardPageTurn, .keyboard),
            (volumeKeyPageTurn != previous.volumeKeyPageTurn, .volumekeys),
            (keepScreenAwake != previous.keepScreenAwake, .keepawake),
            (readingProgression != previous.readingProgression, .readingprogression),
            (writingMode != previous.writingMode, .writingmode),
            (fontSize != previous.fontSize, .fontsize),
            (lineHeight != previous.lineHeight, .lineheight),
            (pageWidth != previous.pageWidth, .pagewidth),
            (fontFamily != previous.fontFamily, .fontfamily),
            (fontWeight != previous.fontWeight, .fontweight),
            (pageMargin != previous.pageMargin, .pagemargins),
            (spreadMode != previous.spreadMode, .spread),
            (readingMode != previous.readingMode, .readingmode),
            (pageTurnAnimation != previous.pageTurnAnimation, .commandanimation),
            (paragraphIndent != previous.paragraphIndent, .paragraphindent),
            (paragraphSpacing != previous.paragraphSpacing, .paragraphspacing),
            (textAlignment != previous.textAlignment, .textalignment),
            (preservePublisherStyles != previous.preservePublisherStyles, .publisherstyles),
            (smartOptimization != previous.smartOptimization, .smartoptimization),
            (deduplicateIndent != previous.deduplicateIndent, .deduplicateindent),
            (indentUnindented != previous.indentUnindented, .indentunindented),
            (comicDirection != previous.comicDirection, .comicdirection),
            (comicZoom != previous.comicZoom, .comiczoom),
            (comicPageWidth != previous.comicPageWidth || pdfPageWidth != previous.pdfPageWidth, .pagewidth),
            (comicImageFit != previous.comicImageFit, .comicfit),
            (comicImageVariant != previous.comicImageVariant, .comicquality),
            (comicPageTurnAnimation != previous.comicPageTurnAnimation, .commandanimation),
            (comicFlow != previous.comicFlow, .readingmode),
            (comicSpread != previous.comicSpread, .spread),
            (comicPageGap != previous.comicPageGap, .comicpagegap),
            (comicCoverSingle != previous.comicCoverSingle, .comiccoversingle),
            (pdfZoom != previous.pdfZoom, .pdfzoom),
            (pdfFit != previous.pdfFit, .pdffit),
            (pdfRotation != previous.pdfRotation, .pdfrotation),
            (pdfCropMargins != previous.pdfCropMargins, .pdfcrop),
            (letterSpacing != previous.letterSpacing, letterSpacing < 0 ? .negativeletterspacing : .letterspacing),
        ]
        return Set(changes.filter { $0.0 }.map { $0.1 })
    }
}

/// Native editable field names adapt to the shared, validated storage contract.
extension IosReaderPreferences {
    private static let wireFields: [String: String] = [
        "appearance.theme": "theme",
        "appearance.themeMode": "themeMode",
        "comic.coverSingle": "comicCoverSingle",
        "comic.direction": "comicDirection",
        "comic.flow": "comicFlow",
        "comic.imageFit": "comicImageFit",
        "comic.imageVariant": "comicImageVariant",
        "comic.pageGap": "comicPageGap",
        "comic.pageTurnAnimation": "comicPageTurnAnimation",
        "comic.pageWidth": "comicPageWidth",
        "comic.spreadMode": "comicSpread",
        "comic.zoom": "comicZoom",
        "display.progressStyle": "progressStyle",
        "display.showClock": "showClock",
        "epub.flow": "readingMode",
        "epub.readingProgression": "readingProgression",
        "epub.writingMode": "writingMode",
        "epub.fontFamily": "fontFamily",
        "epub.fontSize": "fontSize",
        "epub.fontWeight": "fontWeight",
        "epub.letterSpacing": "letterSpacing",
        "epub.lineHeight": "lineHeight",
        "epub.optimization.deduplicateIndent": "deduplicateIndent",
        "epub.optimization.enabled": "smartOptimization",
        "epub.optimization.indentUnindented": "indentUnindented",
        "epub.pageMargin": "pageMargin",
        "epub.pageTurnAnimation": "pageTurnAnimation",
        "epub.pageWidth": "pageWidth",
        "epub.spreadMode": "spreadMode",
        "epub.typography.paragraphIndent": "paragraphIndent",
        "epub.typography.paragraphSpacing": "paragraphSpacing",
        "epub.typography.preservePublisherStyles": "preservePublisherStyles",
        "epub.typography.textAlign": "textAlignment",
        "interaction.keepScreenAwake": "keepScreenAwake",
        "interaction.keyboardPageTurn": "keyboardPageTurn",
        "interaction.swipePageTurn": "swipePageTurn",
        "interaction.tapZones": "tapZones",
        "interaction.volumeKeyPageTurn": "volumeKeyPageTurn",
        "pdf.cropMargins": "pdfCropMargins",
        "pdf.fit": "pdfFit",
        "pdf.pageWidth": "pdfPageWidth",
        "pdf.rotation": "pdfRotation",
        "pdf.zoom": "pdfZoom"
    ]

    func canonicalJSON() throws -> String {
        let flat = try JSONSerialization.jsonObject(with: JSONEncoder().encode(self)) as? [String: Any] ?? [:]
        let currentVersion = Int(ErmaoShared.ReaderPreferences.companion.SCHEMA_VERSION)
        var root: [String: Any] = ["schemaVersion": currentVersion, "pdf": ["flow": "paged"]]
        for (path, field) in Self.wireFields {
            var value = flat[field]
            if field == "readingMode" { value = readingMode == .paged ? "paginated" : "scrolled" }
            Self.setWireValue(value, parts: path.split(separator: ".").map(String.init), in: &root)
        }
        let data = try JSONSerialization.data(withJSONObject: root)
        guard let input = String(data: data, encoding: .utf8),
              let canonical = ReaderPreferencesJson.shared.canonicalizeOrNull(payload: input)
        else { throw CocoaError(.coderInvalidValue) }
        return canonical
    }

    init(canonicalJSON: String) throws {
        let root = try JSONSerialization.jsonObject(with: Data(canonicalJSON.utf8)) as? [String: Any] ?? [:]
        var flat = try JSONSerialization.jsonObject(with: JSONEncoder().encode(Self())) as? [String: Any] ?? [:]
        for (path, field) in Self.wireFields {
            var value: Any? = root
            for part in path.split(separator: ".") { value = (value as? [String: Any])?[String(part)] }
            if field == "readingMode", let flow = value as? String { value = flow == "paginated" ? "paged" : "continuousScroll" }
            if let value { flat[field] = value }
        }
        self = try JSONDecoder().decode(Self.self, from: JSONSerialization.data(withJSONObject: flat))
    }

    private static func setWireValue(_ value: Any?, parts: [String], in root: inout [String: Any]) {
        guard let first = parts.first else { return }
        if parts.count == 1 { root[first] = value; return }
        var nested = root[first] as? [String: Any] ?? [:]
        setWireValue(value, parts: Array(parts.dropFirst()), in: &nested)
        root[first] = nested
    }

    func changing(_ setting: ReaderSettingDefinition, value: String) throws -> Self {
        let preferences = try ReaderPreferencesJson.shared.decode(payload: canonicalJSON())
        let changed = try setting.change(preferences: preferences, value: value)
        var result = try Self(canonicalJSON: ReaderPreferencesJson.shared.encode(preferences: changed))
        if setting.id == "theme" { result.themeMode = .manual }
        return result
    }
}
