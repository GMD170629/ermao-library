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
        XCTAssertEqual(app.buttons.matching(identifier: "work.contents.breadcrumb.root").count, 1)
        XCTAssertTrue(app.staticTexts["The Left Hand of Darkness I"].exists)
        XCTAssertFalse(app.staticTexts["The Left Hand of Darkness I.cbz"].exists)
        XCTAssertFalse(app.staticTexts["Folder"].exists)
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

    func testLiveEpubOpensFromWorkDetailOnPhysicalDevice() throws {
        try exerciseLiveReader(
            format: "EPUB", bookID: "py_75b1eb8b3f5c4a0386a7f06ffc956563",
            resourceID: nil, screenID: "reader.reflow.screen", expectsWebContent: true
        )
    }

    func testLiveMobiOpensFromWorkDetailOnPhysicalDevice() throws {
        try exerciseLiveReader(format: "MOBI", bookID: "py_7093dd69425e4c6a900f59ff01efdad4", resourceID: nil, screenID: "reader.reflow.screen", expectsWebContent: true)
    }

    func testLiveAzwOpensFromWorkDetailOnPhysicalDevice() throws {
        try exerciseLiveReader(format: "AZW", bookID: "py_329e805731e5434baea49195c0a8d104", resourceID: nil, screenID: "reader.reflow.screen", expectsWebContent: true)
    }

    func testLiveAzw3OpensFromWorkDetailOnPhysicalDevice() throws {
        try exerciseLiveReader(format: "AZW3", bookID: "py_a0469b0ed7a74bb382372f69d8895b54", resourceID: nil, screenID: "reader.reflow.screen", expectsWebContent: true)
    }

    func testLivePrcOpensFromWorkDetailOnPhysicalDevice() throws {
        try exerciseLiveReader(format: "PRC", bookID: "py_3504d0155e13489fa779981352771025", resourceID: nil, screenID: "reader.reflow.screen", expectsWebContent: true)
    }

    func testLiveFb2OpensFromWorkDetailOnPhysicalDevice() throws {
        try exerciseLiveReader(format: "FB2", bookID: "py_63036a8ec6274fd8a26fea89816e7820", resourceID: nil, screenID: "reader.reflow.screen", expectsWebContent: true)
    }

    func testLiveTxtOpensFromWorkDetailOnPhysicalDevice() throws {
        try exerciseLiveReader(format: "TXT", bookID: "py_4ac05c773a534147aa9436c6973b6a50", resourceID: nil, screenID: "reader.reflow.screen", expectsWebContent: true)
    }

    func testLivePdfOpensFromWorkDetailOnPhysicalDevice() throws {
        try exerciseLiveReader(format: "PDF", bookID: "py_4bd840366d8140ed9bbe1ca60f274ea5", resourceID: nil, screenID: "reader.pdf.screen", expectsWebContent: false)
    }

    func testLiveCbzOpensFromWorkDetailOnPhysicalDevice() throws {
        try exerciseLiveReader(format: "CBZ", bookID: "py_7f519048d90b4a81b880db6ac411c1fa", resourceID: "py_6d0a58e2f90d41f5bcb278615f6b3b4f", screenID: "reader.comic.screen", expectsWebContent: false)
    }

    func testLiveZipOpensFromWorkDetailOnPhysicalDevice() throws {
        try exerciseLiveReader(format: "ZIP", bookID: "py_b1214478a7cc4cdc84195b2e2f9cd44b", resourceID: "py_ffc151b4bf1644d89cac6e8fb6313d03", screenID: "reader.comic.screen", expectsWebContent: false)
    }

    func testLiveCbrOpensFromWorkDetailOnPhysicalDevice() throws {
        try exerciseLiveReader(format: "CBR", bookID: "py_7f519048d90b4a81b880db6ac411c1fa", resourceID: "py_e6501e8c51844820b08919deea9254ab", screenID: "reader.comic.screen", expectsWebContent: false)
    }

    func testLiveRarOpensFromWorkDetailOnPhysicalDevice() throws {
        try exerciseLiveReader(format: "RAR", bookID: "py_b1214478a7cc4cdc84195b2e2f9cd44b", resourceID: "py_a483abf2783142ec8a3301153294580e", screenID: "reader.comic.screen", expectsWebContent: false)
    }

    func testLiveImageDirectoryOpensFromWorkDetailOnPhysicalDevice() throws {
        try exerciseLiveReader(format: "IMAGE_DIR", bookID: "py_7f519048d90b4a81b880db6ac411c1fa", resourceID: "py_c157833c02c448e58d4a884c1a9f0760", screenID: "reader.comic.screen", expectsWebContent: false)
    }

    func testLiveDownloadsEveryOriginalFormatOnPhysicalDevice() throws {
        let singles = Self.liveFormats.filter { $0.multiDownloadGroup == nil }
        for publication in singles {
            try downloadSingleOriginal(publication)
        }
        try enqueueMultiOriginals(
            bookID: "py_7f519048d90b4a81b880db6ac411c1fa",
            publications: Self.liveFormats.filter { $0.multiDownloadGroup == "volume-comics" }
        )
        try enqueueMultiOriginals(
            bookID: "py_b1214478a7cc4cdc84195b2e2f9cd44b",
            publications: Self.liveFormats.filter { $0.multiDownloadGroup == "archive-comics" }
        )

        let app = launchDownloadsCenter()
        for publication in Self.liveFormats {
            XCTAssertTrue(
                filteredDownloadRecord(publication, app: app).waitForExistence(timeout: 180),
                "\(publication.format) completed original download"
            )
        }
        attachScreenshot(named: "live-downloads-all-originals-completed", app: app)
    }

    /// Run this test only after `testLiveDownloadsEveryOriginalFormatOnPhysicalDevice`
    /// has completed and the API server has been stopped. It intentionally performs a
    /// fresh app launch for every publication so no remote response can satisfy Reader.
    func testOfflineDownloadsOpenEveryFormatAfterColdLaunchOnPhysicalDevice() throws {
        for publication in Self.liveFormats {
            try exerciseOfflineDownload(publication)
        }
    }

    func testOfflineEpubOpensAfterColdLaunchOnPhysicalDevice() throws {
        try exerciseOfflineDownload(Self.liveFormats[0])
    }

    private func exerciseOfflineDownload(
        _ publication: LivePublication,
        readerTimeout: TimeInterval = 45
    ) throws {
        let app = launchDownloadsCenter(initialResourceID: publication.resourceID)
        let offlineRecord = app.buttons["downloads.open.\(publication.resourceID)"]
        XCTAssertTrue(offlineRecord.waitForExistence(timeout: 30), "\(publication.format) local record")
        offlineRecord.tap()

        let readerScreen = app.otherElements[publication.screenID]
        let readerOpened = readerScreen.waitForExistence(timeout: readerTimeout)
        if !readerOpened {
            let failure = app.descendants(matching: .any).matching(
                NSPredicate(format: "identifier BEGINSWITH %@", "reader.bootstrap.failure.")
            ).firstMatch
            let isLoading = app.descendants(matching: .any)["reader.bootstrap.loading"].exists
            let bootstrapState = failure.exists ? failure.identifier : "reader.bootstrap.loading=\(isLoading)"
            XCTFail("\(publication.format) offline Reader did not open; \(bootstrapState)")
            app.terminate()
            return
        }
        if publication.expectsWebContent {
            XCTAssertGreaterThan(app.webViews.count, 0, "\(publication.format) offline body")
        }
        revealReaderControlsIfNeeded(app: app, readerScreen: readerScreen)
        XCTAssertFalse(app.staticTexts["Unable to Open Book"].exists)
        XCTAssertFalse(app.staticTexts["无法打开图书"].exists)
        XCTAssertTrue(app.buttons["reader.next"].waitForExistence(timeout: 10))
        app.buttons["reader.next"].tap()
        app.swipeLeft()
        attachScreenshot(named: "live-reader-\(publication.format.lowercased())-offline", app: app)
        app.terminate()

        let relaunched = launchDownloadsCenter(initialResourceID: publication.resourceID)
        let restoredRecord = relaunched.buttons["downloads.open.\(publication.resourceID)"]
        XCTAssertTrue(restoredRecord.waitForExistence(timeout: 30))
        restoredRecord.tap()
        let restoredScreen = relaunched.otherElements[publication.screenID]
        XCTAssertTrue(restoredScreen.waitForExistence(timeout: 45), "\(publication.format) cold restore")
        XCTAssertFalse(relaunched.staticTexts["Unable to Open Book"].exists)
        XCTAssertFalse(relaunched.staticTexts["无法打开图书"].exists)
        relaunched.terminate()
    }

    private func attachScreenshot(named name: String, app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func exerciseLiveReader(
        format: String,
        bookID: String,
        resourceID: String?,
        screenID: String,
        expectsWebContent: Bool
    ) throws {
        let app = XCUIApplication()
        app.launchEnvironment["ERMAO_UI_TEST_LIVE_INITIAL_WORK_ID"] = bookID
        if let resourceID { app.launchEnvironment["ERMAO_UI_TEST_LIVE_INITIAL_RESOURCE_ID"] = resourceID }
        app.launch()

        XCTAssertTrue(app.scrollViews["work.detail.screen"].waitForExistence(timeout: 30), "\(format) work detail")
        let readerAction = app.buttons["work.reader.action"]
        XCTAssertTrue(readerAction.waitForExistence(timeout: 20), "\(format) Reader action")
        readerAction.tap()

        let readerScreen = app.otherElements[screenID]
        XCTAssertTrue(readerScreen.waitForExistence(timeout: 45), "\(format) Reader screen")
        if expectsWebContent {
            XCTAssertGreaterThan(app.webViews.count, 0, "\(format) must render publication content")
        }
        revealReaderControlsIfNeeded(app: app, readerScreen: readerScreen)
        let closeReader = app.buttons["reader.close"]
        XCTAssertTrue(closeReader.waitForExistence(timeout: 20), "\(format) controls")
        XCTAssertFalse(app.staticTexts["无法打开图书"].exists, "\(format) must not show an error")
        XCTAssertTrue(app.buttons["reader.next"].waitForExistence(timeout: 10), "\(format) next action")
        attachScreenshot(named: "live-reader-\(format.lowercased())-online", app: app)
        app.buttons["reader.next"].tap()
        app.swipeLeft()
        revealReaderControlsIfNeeded(app: app, readerScreen: readerScreen)

        let progress = app.sliders["reader.progress"]
        XCTAssertTrue(progress.waitForExistence(timeout: 10), "\(format) progress jump")
        progress.adjust(toNormalizedSliderPosition: 0)
        let startValue = progress.value as? String ?? ""
        progress.adjust(toNormalizedSliderPosition: 0.72)
        let savedValue = progress.value as? String ?? ""
        XCTAssertFalse(savedValue.isEmpty, "\(format) precise location value")
        XCTAssertNotEqual(savedValue, startValue, "\(format) precise location must change")
        attachScreenshot(named: "live-reader-\(format.lowercased())-progress-jump", app: app)

        app.buttons["reader.close"].tap()
        XCTAssertTrue(app.scrollViews["work.detail.screen"].waitForExistence(timeout: 10), "\(format) return")

        readerAction.tap()
        let restoredScreen = app.otherElements[screenID]
        XCTAssertTrue(restoredScreen.waitForExistence(timeout: 45), "\(format) reopen Reader")
        revealReaderControlsIfNeeded(app: app, readerScreen: restoredScreen)
        let restoredProgress = app.sliders["reader.progress"]
        XCTAssertTrue(restoredProgress.waitForExistence(timeout: 10), "\(format) restored progress")
        XCTAssertFalse((restoredProgress.value as? String ?? "").isEmpty, "\(format) restored location value")
        XCTAssertFalse(app.staticTexts["Unable to Open Book"].exists)
        XCTAssertFalse(app.staticTexts["无法打开图书"].exists)
        attachScreenshot(named: "live-reader-\(format.lowercased())-restored", app: app)
        app.buttons["reader.close"].tap()
        XCTAssertTrue(app.scrollViews["work.detail.screen"].waitForExistence(timeout: 10), "\(format) restored return")
    }

    private func revealReaderControlsIfNeeded(app: XCUIApplication, readerScreen: XCUIElement) {
        if !app.buttons["reader.close"].exists {
            readerScreen.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        }
    }

    private func downloadSingleOriginal(_ publication: LivePublication) throws {
        let app = XCUIApplication()
        app.launchEnvironment["ERMAO_UI_TEST_LIVE_INITIAL_WORK_ID"] = publication.bookID
        app.launchEnvironment["ERMAO_UI_TEST_LIVE_INITIAL_RESOURCE_ID"] = publication.resourceID
        app.launchArguments += ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(app.scrollViews["work.detail.screen"].waitForExistence(timeout: 30))
        let action = app.buttons["work.download.action"]
        XCTAssertTrue(action.waitForExistence(timeout: 20))
        let completedLabels = ["Downloaded", "已下载"]
        if completedLabels.contains(action.label) {
            app.terminate()
            return
        }
        action.tap()
        let completed = NSPredicate(format: "label == %@ OR label == %@", completedLabels[0], completedLabels[1])
        let expectation = XCTNSPredicateExpectation(predicate: completed, object: action)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: 180), .completed, "\(publication.format) download")
        app.terminate()
    }

    private func enqueueMultiOriginals(bookID: String, publications: [LivePublication]) throws {
        let app = XCUIApplication()
        app.launchEnvironment["ERMAO_UI_TEST_LIVE_INITIAL_WORK_ID"] = bookID
        app.launchArguments += ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(app.scrollViews["work.detail.screen"].waitForExistence(timeout: 30))
        app.buttons["work.download.action"].tap()
        for publication in publications {
            let resource = revealMultiDownloadResource(publication, app: app)
            XCTAssertTrue(resource.exists, "\(publication.format) batch option")
            resource.tap()
        }
        let confirm = app.buttons["work.multiDownload.confirm"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 10))
        if confirm.isEnabled {
            confirm.tap()
        } else {
            let cancel = app.buttons.matching(
                NSPredicate(format: "label == %@ OR label == %@", "Cancel", "取消")
            ).firstMatch
            XCTAssertTrue(cancel.waitForExistence(timeout: 10), "dismiss an already active or completed batch")
            cancel.tap()
        }
        XCTAssertTrue(app.scrollViews["work.detail.screen"].waitForExistence(timeout: 30))
        app.terminate()
    }

    private func revealMultiDownloadResource(
        _ publication: LivePublication,
        app: XCUIApplication
    ) -> XCUIElement {
        let resource = app.descendants(matching: .any)[
            "work.multiDownload.resource.\(publication.resourceID)"
        ]
        let deadline = Date().addingTimeInterval(30)
        while !resource.exists, Date() < deadline {
            let collapsedFolder = app.buttons.matching(identifier: "chevron.right").firstMatch
            guard collapsedFolder.exists else {
                _ = resource.waitForExistence(timeout: 1)
                continue
            }
            collapsedFolder.tap()
            _ = resource.waitForExistence(timeout: 2)
        }
        return resource
    }

    private func launchDownloadsCenter(initialResourceID: String? = nil) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchEnvironment["ERMAO_UI_TEST_INITIAL_DOWNLOADS"] = "1"
        if let initialResourceID {
            app.launchEnvironment["ERMAO_UI_TEST_INITIAL_DOWNLOAD_RESOURCE_ID"] = initialResourceID
        }
        app.launchArguments += ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["downloads.screen"].waitForExistence(timeout: 30))
        return app
    }

    private func filteredDownloadRecord(
        _ publication: LivePublication,
        query: String? = nil,
        app: XCUIApplication
    ) -> XCUIElement {
        let record = app.buttons["downloads.open.\(publication.resourceID)"]
        let search = app.searchFields.firstMatch
        if !search.exists {
            app.swipeDown()
        }
        if search.waitForExistence(timeout: 3) {
            search.tap()
            let existingText = (search.value as? String) ?? ""
            if !existingText.isEmpty {
                search.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: existingText.count))
            }
            search.typeText(query ?? publication.format)
            let keyboardAction = app.keyboards.buttons.matching(
                NSPredicate(
                    format: "label == %@ OR label == %@ OR label == %@ OR label == %@",
                    "Search", "搜索", "Done", "完成"
                )
            ).firstMatch
            if keyboardAction.waitForExistence(timeout: 2) {
                keyboardAction.tap()
            } else {
                search.typeText(XCUIKeyboardKey.return.rawValue)
            }
            return record
        }

        for _ in 0..<20 {
            if record.waitForExistence(timeout: 1) { return record }
            app.swipeUp()
        }
        for _ in 0..<20 {
            if record.waitForExistence(timeout: 1) { return record }
            app.swipeDown()
        }
        return record
    }

    private struct LivePublication {
        let format: String
        let bookID: String
        let resourceID: String
        let screenID: String
        let expectsWebContent: Bool
        let multiDownloadGroup: String?
    }

    private static let liveFormats = [
        LivePublication(format: "EPUB", bookID: "py_75b1eb8b3f5c4a0386a7f06ffc956563", resourceID: "py_db7f936c9cda4a5a865892029c18d1ff", screenID: "reader.reflow.screen", expectsWebContent: true, multiDownloadGroup: nil),
        LivePublication(format: "MOBI", bookID: "py_7093dd69425e4c6a900f59ff01efdad4", resourceID: "py_595610912b194b62b5ed6249e8f10ff1", screenID: "reader.reflow.screen", expectsWebContent: true, multiDownloadGroup: nil),
        LivePublication(format: "AZW", bookID: "py_329e805731e5434baea49195c0a8d104", resourceID: "py_bd18d6965bea45148b5c23ed639b0aef", screenID: "reader.reflow.screen", expectsWebContent: true, multiDownloadGroup: nil),
        LivePublication(format: "AZW3", bookID: "py_a0469b0ed7a74bb382372f69d8895b54", resourceID: "py_35ecd0b1eb7b4e90ad34f38fdbff4465", screenID: "reader.reflow.screen", expectsWebContent: true, multiDownloadGroup: nil),
        LivePublication(format: "PRC", bookID: "py_3504d0155e13489fa779981352771025", resourceID: "py_ebca357a7b514141a4a1b1fb6fe02965", screenID: "reader.reflow.screen", expectsWebContent: true, multiDownloadGroup: nil),
        LivePublication(format: "FB2", bookID: "py_63036a8ec6274fd8a26fea89816e7820", resourceID: "py_8186253e6f534ff8a79ff9eac97d9697", screenID: "reader.reflow.screen", expectsWebContent: true, multiDownloadGroup: nil),
        LivePublication(format: "TXT", bookID: "py_4ac05c773a534147aa9436c6973b6a50", resourceID: "py_8614f4706d094ec3812e1480d7556b2c", screenID: "reader.reflow.screen", expectsWebContent: true, multiDownloadGroup: nil),
        LivePublication(format: "PDF", bookID: "py_4bd840366d8140ed9bbe1ca60f274ea5", resourceID: "py_33433bef4ed54276b4be9a054df68587", screenID: "reader.pdf.screen", expectsWebContent: false, multiDownloadGroup: nil),
        LivePublication(format: "CBZ", bookID: "py_7f519048d90b4a81b880db6ac411c1fa", resourceID: "py_6d0a58e2f90d41f5bcb278615f6b3b4f", screenID: "reader.comic.screen", expectsWebContent: false, multiDownloadGroup: "volume-comics"),
        LivePublication(format: "ZIP", bookID: "py_b1214478a7cc4cdc84195b2e2f9cd44b", resourceID: "py_ffc151b4bf1644d89cac6e8fb6313d03", screenID: "reader.comic.screen", expectsWebContent: false, multiDownloadGroup: "archive-comics"),
        LivePublication(format: "CBR", bookID: "py_7f519048d90b4a81b880db6ac411c1fa", resourceID: "py_e6501e8c51844820b08919deea9254ab", screenID: "reader.comic.screen", expectsWebContent: false, multiDownloadGroup: "volume-comics"),
        LivePublication(format: "RAR", bookID: "py_b1214478a7cc4cdc84195b2e2f9cd44b", resourceID: "py_a483abf2783142ec8a3301153294580e", screenID: "reader.comic.screen", expectsWebContent: false, multiDownloadGroup: "archive-comics"),
        LivePublication(format: "IMAGE_DIR", bookID: "py_7f519048d90b4a81b880db6ac411c1fa", resourceID: "py_c157833c02c448e58d4a884c1a9f0760", screenID: "reader.comic.screen", expectsWebContent: false, multiDownloadGroup: "volume-comics"),
    ]

}
