import XCTest

@MainActor
final class ContentDiscoveryUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testWorkDetailQuickActionsOpenStableInteractionSurfaces() throws {
        let app = XCUIApplication()
        app.launchEnvironment["ERMAO_UI_TEST_CONTENT_FIXTURE"] = "1"
        app.launchArguments += ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()

        let libraryTab = app.tabBars.buttons["Library"]
        XCTAssertTrue(libraryTab.waitForExistence(timeout: 10))
        libraryTab.tap()
        let work = app.buttons["work.pride-and-prejudice"]
        XCTAssertTrue(work.waitForExistence(timeout: 10))
        work.tap()
        XCTAssertTrue(app.scrollViews["work.detail.screen"].waitForExistence(timeout: 10))

        XCTAssertTrue(app.buttons["work.download.action"].isHittable)
        XCTAssertTrue(app.buttons["work.readingStatus.action"].isHittable)

        app.buttons["work.shelf.action"].tap()
        XCTAssertTrue(app.navigationBars["Add to Shelf"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["Cancel"].isHittable)
        app.buttons["Cancel"].tap()
        XCTAssertTrue(app.scrollViews["work.detail.screen"].waitForExistence(timeout: 5))

        let moreMenu = app.buttons["work.book.moreMenu"]
        XCTAssertTrue(moreMenu.isHittable)
        moreMenu.tap()
        XCTAssertTrue(app.buttons["Edit"].waitForExistence(timeout: 2))
        app.buttons["Edit"].tap()
        XCTAssertTrue(app.navigationBars["Edit Book"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["Close"].isHittable)
    }

    func testLibraryWorkDetailAndFacetJourney() throws {
        let app = XCUIApplication()
        app.launchEnvironment["ERMAO_UI_TEST_CONTENT_FIXTURE"] = "1"
        app.launchArguments += ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()

        let libraryTab = app.tabBars.buttons["Library"]
        XCTAssertTrue(libraryTab.waitForExistence(timeout: 10))
        libraryTab.tap()

        let work = app.buttons["work.pride-and-prejudice"]
        XCTAssertTrue(work.waitForExistence(timeout: 10))
        work.tap()

        XCTAssertTrue(app.scrollViews["work.detail.screen"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Pride and Prejudice"].exists)
        let readerButton = app.buttons["Continue Reading"]
        XCTAssertTrue(readerButton.exists)
        XCTAssertTrue(readerButton.isEnabled)

        XCTAssertFalse(app.staticTexts["About This Work"].exists)
        XCTAssertTrue(app.staticTexts["Classic"].exists)
        XCTAssertTrue(app.staticTexts["Romance"].exists)
        XCTAssertTrue(app.buttons["work.download.action"].isHittable)
        XCTAssertTrue(app.buttons["work.readingStatus.action"].isHittable)
        XCTAssertTrue(app.buttons["work.shelf.action"].isHittable)
        let moreMenu = app.buttons["work.book.moreMenu"]
        XCTAssertTrue(moreMenu.isHittable)
        moreMenu.tap()
        XCTAssertTrue(app.buttons["Edit"].waitForExistence(timeout: 2))
        app.tap()
        app.scrollViews["work.detail.screen"].swipeUp()
        XCTAssertTrue(app.staticTexts["Contents"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Chapter 1"].exists)
        XCTAssertTrue(app.staticTexts["Currently Reading"].exists)
        XCTAssertTrue(app.staticTexts["Unread"].exists)
        attachScreenshot(named: "work-detail-final-single-resource", app: app)

        app.navigationBars.buttons.element(boundBy: 0).tap()
        XCTAssertTrue(app.scrollViews["library.screen"].waitForExistence(timeout: 10))

        app.segmentedControls.buttons["Series"].tap()
        let facet = app.buttons["facet.series.earthsea"]
        XCTAssertTrue(facet.waitForExistence(timeout: 10))
        facet.tap()
        XCTAssertTrue(app.scrollViews["facet.screen"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Earthsea"].waitForExistence(timeout: 10))
    }

    func testWorkWithoutDescriptionOrMediaChoiceShowsChaptersDirectly() throws {
        let app = XCUIApplication()
        app.launchEnvironment["ERMAO_UI_TEST_CONTENT_FIXTURE"] = "1"
        app.launchArguments += ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()

        XCTAssertTrue(app.tabBars.buttons["Library"].waitForExistence(timeout: 10))
        app.tabBars.buttons["Library"].tap()

        let work = app.buttons["work.a-wizard-of-earthsea"]
        XCTAssertTrue(work.waitForExistence(timeout: 10))
        work.tap()

        XCTAssertTrue(app.scrollViews["work.detail.screen"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["work.section.about"].exists)
        XCTAssertFalse(app.buttons["work.section.media"].exists)
        XCTAssertFalse(app.staticTexts["E-book"].exists)
        XCTAssertTrue(app.staticTexts["Contents"].exists)
        XCTAssertTrue(app.staticTexts["Chapter 1"].exists)
        XCTAssertTrue(app.staticTexts["Currently Reading"].exists)
        XCTAssertTrue(app.staticTexts["Unread"].exists)
        attachScreenshot(named: "work-detail-direct-chapters", app: app)
    }

    func testMultiResourceBookUsesHierarchicalContentList() throws {
        let app = XCUIApplication()
        app.launchEnvironment["ERMAO_UI_TEST_CONTENT_FIXTURE"] = "1"
        app.launchArguments += ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()

        XCTAssertTrue(app.tabBars.buttons["Library"].waitForExistence(timeout: 10))
        app.tabBars.buttons["Library"].tap()
        let work = app.buttons["work.the-left-hand-of-darkness"]
        XCTAssertTrue(work.waitForExistence(timeout: 10))
        work.tap()

        XCTAssertTrue(app.scrollViews["work.detail.screen"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Book Contents"].waitForExistence(timeout: 5))
        let resourceOne = app.otherElements["work.resource.resource-1"]
        XCTAssertTrue(resourceOne.waitForExistence(timeout: 5))
        let folder = app.buttons["work.contents.folder.winter-cycle"]
        XCTAssertTrue(folder.exists)
        folder.tap()

        let resourceTwo = app.otherElements["work.resource.resource-2"]
        XCTAssertTrue(resourceTwo.waitForExistence(timeout: 5))
        XCTAssertTrue(resourceTwo.exists)
        XCTAssertTrue(app.otherElements["work.resource.resource-3"].exists)

        attachScreenshot(named: "work-detail-hierarchical-contents", app: app)
    }

    private func attachScreenshot(named name: String, app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
