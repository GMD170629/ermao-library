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
    var bookmarkSyncPending: Bool { false }
    var currentBookmarkActive: Bool { false }
    var canUndoControlBookmark: Bool { false }
    func undoControlBookmark() {}
    func toggleCurrentBookmark() async {}
    func removeBookmark(id: String) {}
    func goToBookmark(id: String) async -> Bool { false }
    func zoomControl(_ direction: Int) {}

    func platformControlEnabled(_ control: ErmaoShared.ReaderControl, unavailable: Set<ErmaoShared.ReaderControl> = []) -> Bool {
        ErmaoShared.PublicKt.resolveReaderControlContext(
            control: control, morphology: controlMorphology,
            capabilities: ErmaoShared.PublicKt.readerPlatformCapabilities(morphology: controlMorphology, volumeKeys: false, pdfFit: false),
            ready: controlReady, scrolling: preferences.readingMode == .continuousScroll,
            publisherStyles: preferences.preservePublisherStyles, nativeUnavailable: unavailable
        ) == .available
    }

    func canApplyControlPreferences(_ updated: IosReaderPreferences) -> Bool {
        if updated == preferences.reset(for: controlMorphology) { return true }
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

/// One owned writer coalesces slider changes while retaining the final requested value.
@MainActor
final class IosReaderPreferenceEditor: ObservableObject {
    @Published private(set) var draft: IosReaderPreferences
    @Published private(set) var applyFailed = false
    @Published private(set) var isApplying = false
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
        isApplying = true
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
            isApplying = false
        }
    }

    func flush() async { await writer?.value }

    func reset(morphology: ErmaoShared.ReaderMorphology) {
        change { $0 = $0.reset(for: morphology) }
    }
}

extension IosReaderPreferences {
    func reset(for morphology: ErmaoShared.ReaderMorphology) -> Self {
        var result = Self()
        // Explicit morphology-owned preference groups; shared preferences always reset.
        if morphology != .reflowable {
            result.fontSize = fontSize; result.lineHeight = lineHeight; result.pageWidth = pageWidth
            result.fontFamily = fontFamily; result.fontWeight = fontWeight; result.letterSpacing = letterSpacing
            result.pageMargin = pageMargin; result.spreadMode = spreadMode; result.pageTurnAnimation = pageTurnAnimation
            result.readingMode = readingMode; result.paragraphIndent = paragraphIndent; result.paragraphSpacing = paragraphSpacing
            result.textAlignment = textAlignment; result.preservePublisherStyles = preservePublisherStyles
            result.allowPublisherColors = allowPublisherColors; result.allowPublisherFonts = allowPublisherFonts
            result.smartOptimization = smartOptimization; result.deduplicateIndent = deduplicateIndent; result.indentUnindented = indentUnindented
        }
        if morphology != .comic {
            result.comicDirection = comicDirection; result.comicSpread = comicSpread; result.comicFlow = comicFlow
            result.comicCoverSingle = comicCoverSingle; result.comicPageGap = comicPageGap; result.comicZoom = comicZoom
        }
        if morphology != .pdf {
            result.pdfZoom = pdfZoom; result.pdfFit = pdfFit; result.pdfRotation = pdfRotation; result.pdfCropMargins = pdfCropMargins
        }
        return result
    }
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
            (allowPublisherColors != previous.allowPublisherColors, .publishercolors),
            (allowPublisherFonts != previous.allowPublisherFonts, .publisherfonts),
            (smartOptimization != previous.smartOptimization, .smartoptimization),
            (deduplicateIndent != previous.deduplicateIndent, .deduplicateindent),
            (indentUnindented != previous.indentUnindented, .indentunindented),
            (comicDirection != previous.comicDirection, .comicdirection),
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
