import SwiftUI
import XCTest
@testable import ErmaoLibrary

final class NavigationThemeTests: XCTestCase {
    func testRootTabContractUsesSharedStableOrderAndFailsSafe() {
        XCTAssertEqual(RootTabContract.orderedIDs, ["home", "library", "shelves", "me"])
        XCTAssertEqual(RootTabContract.normalizedID("shelves"), "shelves")
        XCTAssertEqual(RootTabContract.normalizedID("future-tab"), "home")
    }

    func testEachRootTabKeepsAnIndependentNavigationStack() {
        var paths = RootTabPaths()
        for tab in [TabPresentation.home, .library, .shelves, .me] {
            var path = paths.path(for: tab)
            path.append(.work(bookID: "detail-\(String(describing: tab))"))
            paths.setPath(path, for: tab)
        }

        paths.popToRoot(.library)

        XCTAssertEqual(paths.path(for: .home).count, 1)
        XCTAssertEqual(paths.path(for: .library).count, 0)
        XCTAssertEqual(paths.path(for: .shelves).count, 1)
        XCTAssertEqual(paths.path(for: .me).count, 1)
    }

    func testThemeUsesGeneratedLightOnlyAndTypographyTokens() {
        let theme = AppTheme.app

        XCTAssertEqual(theme.canvas, Color(hex: GeneratedDesignTokens.App.canvas))
        XCTAssertEqual(theme.actionAccent, Color(hex: GeneratedDesignTokens.App.actionAccent))
        XCTAssertEqual(AppTextRole.display.metrics.size, CGFloat(GeneratedDesignTokens.Display.size))
        XCTAssertEqual(
            AppTextRole.display.metrics.lineHeight,
            CGFloat(GeneratedDesignTokens.Display.lineHeight)
        )
        XCTAssertEqual(AppTextRole.button.metrics.weight, GeneratedDesignTokens.Button.weight)
        XCTAssertEqual(
            CGFloat.iosMinimumTouchTarget,
            CGFloat(GeneratedDesignTokens.Accessibility.MinimumTouchTarget.ios)
        )
    }

    func testReaderSystemThemeUsesTheIndependentSystemAppearanceSignal() {
        var preferences = IosReaderPreferences()
        preferences.theme = .green
        preferences.themeMode = .system

        XCTAssertEqual(preferences.resolvedTheme(for: .light), .day)
        XCTAssertEqual(preferences.resolvedTheme(for: .dark), .night)
        XCTAssertEqual(preferences.theme, .green)
        XCTAssertEqual(IosReaderTheme.day.colors.canvas, GeneratedDesignTokens.Reader.Day.canvas)
        XCTAssertEqual(IosReaderTheme.warm.colors.canvas, GeneratedDesignTokens.Reader.Warm.canvas)
        XCTAssertEqual(IosReaderTheme.green.colors.canvas, GeneratedDesignTokens.Reader.Green.canvas)
        XCTAssertEqual(IosReaderTheme.night.colors.canvas, GeneratedDesignTokens.Reader.Night.canvas)
        XCTAssertEqual(IosReaderTheme.black.colors.canvas, GeneratedDesignTokens.Reader.Black.canvas)
    }

    func testPublicationThemeAdapterClearsAuthoredBackgroundsAndMapsGeneratedLinks() throws {
        let decorated = String(
            decoding: try IosPublicationSecurityPolicy.decorate(
                data: Data("<html><head></head><body><p>Text</p></body></html>".utf8)
            ),
            as: UTF8.self
        )

        XCTAssertTrue(decorated.contains("data-shuku-reader-theme-adapter=\"v1\""))
        XCTAssertTrue(decorated.contains("background-image: none !important"))
        XCTAssertTrue(decorated.contains(":root.readium-sepia-on"))
        XCTAssertTrue(decorated.contains(":root.readium-night-on"))
        XCTAssertTrue(decorated.contains(GeneratedDesignTokens.Reader.Day.link))
        XCTAssertTrue(decorated.contains(GeneratedDesignTokens.Reader.Warm.link))
        XCTAssertTrue(decorated.contains(GeneratedDesignTokens.Reader.Green.link))
        XCTAssertTrue(decorated.contains(GeneratedDesignTokens.Reader.Night.link))
    }
}
