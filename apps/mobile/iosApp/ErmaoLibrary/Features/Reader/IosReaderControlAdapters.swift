import Foundation
import UIKit
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumNavigator
@preconcurrency import ReadiumShared

@MainActor
func makeIosReflowableNavigator(publication: Publication, preferences: EPUBPreferences, location: Locator?) throws -> EPUBNavigatorViewController {
    var configuration = EPUBNavigatorViewController.Configuration(
        preferences: preferences, editingActions: [], preloadPreviousPositionCount: 1, preloadNextPositionCount: 1,
        fontFamilyDeclarations: try iosReaderFontDeclarations()
    )
    configuration.disablePageTurnsWhileScrolling = true
    return try EPUBNavigatorViewController(publication: publication, initialLocation: location, config: configuration)
}

extension IosReflowableReaderSession: IosReaderControlSession {
    var controlMorphology: ErmaoShared.ReaderMorphology { .reflowable }
    var controlReady: Bool { navigator != nil && (phase == .reading || phase == .background) }
    var controlContents: [IosReaderTocEntry] { tableOfContents }
    var controlPosition: String {
        navigator?.currentLocation?.locations.position.map { $0.formatted() }
            ?? progress.formatted(.percent.precision(.fractionLength(0)))
    }

    func isEnabled(_ control: ErmaoShared.ReaderControl) -> Bool {
        guard let navigator else { return false }
        var native = preferences.readium(for: navigator.traitCollection.userInterfaceStyle)
        // Null is the publisher-default value, not a reason to prevent choosing an alignment.
        if native.textAlign == nil { native.textAlign = .start }
        let editor = navigator.editor(of: native)
        let effective: [ErmaoShared.ReaderControl: Bool] = [
            .fontsize: editor.fontSize.isEffective, .fontfamily: editor.fontFamily.isEffective,
            .fontweight: editor.fontWeight.isEffective, .lineheight: editor.lineHeight.isEffective,
            .letterspacing: editor.letterSpacing.isEffective, .pagemargins: editor.pageMargins.isEffective,
            .paragraphindent: editor.paragraphIndent.isEffective, .paragraphspacing: editor.paragraphSpacing.isEffective,
            .textalignment: editor.textAlign.isEffective, .readingmode: editor.scroll.isEffective,
            .spread: editor.columnCount.isEffective, .publisherstyles: editor.publisherStyles.isEffective,
        ]
        return platformControlEnabled(control, unavailable: Set(effective.filter { !$0.value }.map(\.key)))
    }

    func seekControlProgress(_ progress: Double) async -> Bool {
        await goToProgression(progress)
    }
}

extension IosComicReaderSession: IosReaderControlSession {
    var controlMorphology: ErmaoShared.ReaderMorphology { .comic }
    var controlReady: Bool { navigator != nil && (phase == .reading || phase == .background) }
    var controlPosition: String { pageLabel }
    var controlContents: [IosReaderTocEntry] {
        pages.map { page in
            IosReaderTocEntry(id: String(page.pageIndex), title: page.title ?? String(format: String(localized: "reader.comic.page.format"), locale: .current, page.pageIndex + 1), href: nil, depth: 0)
        }
    }
    func isEnabled(_ control: ErmaoShared.ReaderControl) -> Bool { platformControlEnabled(control) }
    func applyControlPreferences(_ updated: IosReaderPreferences) async -> Bool { await applyPreferences(updated) }
    func seekControlProgress(_ progress: Double) async -> Bool { await goToPage(Int((progress * Double(max(0, pageCount - 1))).rounded())) }
    func goToTOCEntry(_ entry: IosReaderTocEntry) async -> Bool {
        guard let index = Int(entry.id) else { return false }
        return await goToPage(index)
    }
}

extension IosPdfReaderSession: IosReaderControlSession {
    var controlMorphology: ErmaoShared.ReaderMorphology { .pdf }
    var controlReady: Bool { navigator != nil && (phase == .reading || phase == .background) }
    var controlPosition: String { pageLabel }
    var controlContents: [IosReaderTocEntry] { tableOfContents }
    func isEnabled(_ control: ErmaoShared.ReaderControl) -> Bool {
        if control == .pdfzoom { return controlReady }
        return platformControlEnabled(control)
    }
    func applyControlPreferences(_ updated: IosReaderPreferences) async -> Bool { await applyPreferences(updated) }
    func seekControlProgress(_ progress: Double) async -> Bool { await goToPage(Int((progress * Double(max(0, canonicalPageCount - 1))).rounded())) }
    func zoomControl(_ direction: Int) {
        if direction < 0 { zoomOut() } else if direction > 0 { zoomIn() } else { zoomToFit() }
    }
}

func iosReaderFontDeclarations() throws -> [AnyHTMLFontFamilyDeclaration] {
        guard let resourcesURL = Bundle.main.resourceURL,
              let resources = FileURL(url: resourcesURL)
        else { throw IosReaderFailure(code: .resourceMissing) }
        let sans = resources.appendingPath("reader/sans.woff2", isDirectory: false)
        let songti = resources.appendingPath("reader/songti.woff2", isDirectory: false)
        let kaiti = resources.appendingPath("reader/kaiti.woff2", isDirectory: false)
        for path in ["reader/sans.woff2", "reader/songti.woff2", "reader/kaiti.woff2"] {
            guard FileManager.default.fileExists(atPath: resourcesURL.appendingPathComponent(path).path) else {
                throw IosReaderFailure(code: .resourceMissing)
            }
        }
        return [
            CSSFontFamilyDeclaration(
                fontFamily: FontFamily(rawValue: "Shuku Sans"),
                fontFaces: [CSSFontFace(file: sans, style: .normal, weight: .variable(100 ... 900))]
            ).eraseToAnyHTMLFontFamilyDeclaration(),
            CSSFontFamilyDeclaration(
                fontFamily: FontFamily(rawValue: "Shuku Songti"),
                fontFaces: [CSSFontFace(file: songti, style: .normal, weight: .variable(100 ... 900))]
            ).eraseToAnyHTMLFontFamilyDeclaration(),
            CSSFontFamilyDeclaration(
                fontFamily: FontFamily(rawValue: "Shuku Kaiti"),
                fontFaces: [CSSFontFace(file: kaiti, style: .normal, weight: .standard(.normal))]
            ).eraseToAnyHTMLFontFamilyDeclaration(),
        ]
    }
