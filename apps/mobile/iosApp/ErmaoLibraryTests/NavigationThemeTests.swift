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
            path.append("detail-\(String(describing: tab))")
            paths.setPath(path, for: tab)
        }

        paths.popToRoot(.library)

        XCTAssertEqual(paths.path(for: .home).count, 1)
        XCTAssertEqual(paths.path(for: .library).count, 0)
        XCTAssertEqual(paths.path(for: .shelves).count, 1)
        XCTAssertEqual(paths.path(for: .me).count, 1)
    }

    func testThemeUsesGeneratedLightDarkAndTypographyTokens() {
        let light = AppTheme.app(for: .light)
        let dark = AppTheme.app(for: .dark)

        XCTAssertNotEqual(light, dark)
        XCTAssertEqual(light.canvas, Color(hex: GeneratedDesignTokens.AppLight.canvas))
        XCTAssertEqual(dark.canvas, Color(hex: GeneratedDesignTokens.AppDark.canvas))
        XCTAssertEqual(light.actionAccent, Color(hex: GeneratedDesignTokens.AppLight.actionAccent))
        XCTAssertEqual(dark.actionAccent, Color(hex: GeneratedDesignTokens.AppDark.actionAccent))
        XCTAssertEqual(AppTextRole.display.metrics.size, CGFloat(GeneratedDesignTokens.Display.size))
        XCTAssertEqual(
            AppTextRole.display.metrics.lineHeight,
            CGFloat(GeneratedDesignTokens.Display.lineHeight)
        )
        XCTAssertEqual(AppTextRole.button.metrics.weight, GeneratedDesignTokens.Button.weight)
        XCTAssertEqual(
            CGFloat.iosMinimumTouchTarget,
            CGFloat(GeneratedDesignTokens.Progress.iosMinimumTouchTarget)
        )
    }
}
