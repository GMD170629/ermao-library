import XCTest

@MainActor
final class ShelfCatalogUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    func testShelfRootAndScopeRemainInShelvesTab() {
        let app = XCUIApplication()
        let isLive = ProcessInfo.processInfo.environment["ERMAO_UI_TEST_LIVE_SHELVES"] == "1"
        if !isLive {
            app.launchEnvironment["ERMAO_UI_TEST_CONTENT_FIXTURE"] = "1"
            app.launchArguments += ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        }
        app.launch()
        let shelves = app.tabBars.buttons.matching(NSPredicate(format: "label == %@ OR label == %@", "Shelves", "书架")).firstMatch
        XCTAssertTrue(shelves.waitForExistence(timeout: 15))
        shelves.tap()
        XCTAssertTrue(app.segmentedControls["shelves.scope"].waitForExistence(timeout: 15))
        let initial = XCTAttachment(screenshot: app.screenshot())
        initial.name = isLive ? "shelves-live-root" : "shelves-fixture-root"; initial.lifetime = .keepAlways; add(initial)
        let scopes = app.segmentedControls["shelves.scope"]
        scopes.buttons.element(boundBy: 2).tap()
        XCTAssertTrue(shelves.isSelected)
        let collection = XCTAttachment(screenshot: app.screenshot())
        collection.name = isLive ? "shelves-live-collections" : "shelves-fixture-collections"; collection.lifetime = .keepAlways; add(collection)
        scopes.buttons.element(boundBy: 0).tap()
    }

    func testCollectionPushSearchAndShelfBookNavigation() {
        let app = XCUIApplication()
        app.launchEnvironment["ERMAO_UI_TEST_CONTENT_FIXTURE"] = "1"
        app.launchArguments += ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let tab = app.tabBars.buttons["Shelves"]
        XCTAssertTrue(tab.waitForExistence(timeout: 10)); tab.tap()
        let plan = app.buttons["shelf.row.plan"]
        XCTAssertTrue(plan.waitForExistence(timeout: 10)); plan.tap()
        let member = app.buttons["shelf.row.to-read"]
        XCTAssertTrue(member.waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["shelf.row.favorites"].exists)
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = "shelves-fixture-collection"; attachment.lifetime = .keepAlways; add(attachment)
        member.tap()
        let book = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Pride and Prejudice")).firstMatch
        XCTAssertTrue(book.waitForExistence(timeout: 10)); book.tap()
        XCTAssertTrue(app.scrollViews["work.detail.screen"].waitForExistence(timeout: 10))
        XCTAssertTrue(tab.isSelected)
        app.navigationBars.buttons.element(boundBy: 0).tap()
        XCTAssertTrue(book.waitForExistence(timeout: 10))
        app.navigationBars.buttons.element(boundBy: 0).tap()
        XCTAssertTrue(member.waitForExistence(timeout: 10))
        app.navigationBars.buttons.element(boundBy: 0).tap()
        XCTAssertTrue(plan.waitForExistence(timeout: 10))
        let search = app.searchFields.firstMatch
        XCTAssertTrue(search.waitForExistence(timeout: 5)); search.tap(); search.typeText("not-a-shelf")
        XCTAssertTrue(app.staticTexts["No matching shelves"].waitForExistence(timeout: 5))
    }
}
