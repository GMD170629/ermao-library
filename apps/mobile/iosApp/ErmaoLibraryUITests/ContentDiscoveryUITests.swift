import XCTest

@MainActor
final class ContentDiscoveryUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
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
        XCTAssertFalse(readerButton.isEnabled)

        XCTAssertTrue(app.staticTexts["About This Work"].exists)
        XCTAssertTrue(app.staticTexts["Contents"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Chapter 1"].exists)
        XCTAssertTrue(app.buttons["Add to Shelf"].exists)
        attachScreenshot(named: "work-detail-final-single-volume", app: app)

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
        XCTAssertFalse(app.staticTexts["Unread"].exists)
        attachScreenshot(named: "work-detail-direct-chapters", app: app)
    }

    func testMultiVolumeWorkUsesSelectableCoverGrid() throws {
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
        XCTAssertTrue(app.staticTexts["All Volumes"].exists)
        XCTAssertTrue(app.buttons["work.volume.volume-1"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["work.volume.volume-2"].exists)
        XCTAssertTrue(app.buttons["work.volume.volume-3"].exists)
        XCTAssertEqual(app.buttons["work.volume.volume-1"].value as? String, "Reading progress 34%")

        app.buttons["work.volume.volume-2"].tap()
        XCTAssertTrue(app.buttons["work.volume.volume-2"].isSelected)
        attachScreenshot(named: "work-detail-final-volume-rail", app: app)
    }

    private func attachScreenshot(named name: String, app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
