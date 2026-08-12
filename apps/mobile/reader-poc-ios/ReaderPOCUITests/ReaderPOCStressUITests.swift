import XCTest

@MainActor
final class ReaderPOCStressUITests: XCTestCase {
    private let fixtureIDs = [
        "basic-mobi6", "basic-kf8", "css", "font", "images",
        "footnotes", "complex-toc", "zh-hans", "ja-vertical", "long-chapter",
    ]

    override func setUpWithError() throws {
        continueAfterFailure = false
        #if targetEnvironment(simulator)
        throw NSError(
            domain: "ReaderPOC.PhysicalDeviceRequired",
            code: 1,
            userInfo: [NSLocalizedDescriptionKey: "Reader POC UI acceptance is physical-device-only"]
        )
        #endif
    }

    func testEveryFixtureColdOpensAndClosesTwentyTimes() throws {
        for fixtureID in fixtureIDs {
            for cycle in 0 ..< 20 {
                let app = XCUIApplication()
                app.launchArguments = ["--reader-poc-ui-test", "--cycle", "\(cycle)"]
                app.launch()
                try openNavigator(fixtureID: fixtureID, in: app)
                app.buttons["reader.close"].tap()
                app.terminate()
            }
        }
    }

    func testEveryFixtureReachesAStableNavigatorViewport() throws {
        for fixtureID in fixtureIDs {
            let app = XCUIApplication()
            app.launchArguments = ["--reader-poc-ui-test", "--navigator-smoke"]
            app.launch()
            try openNavigator(fixtureID: fixtureID, in: app)

            let stressButton = app.buttons["reader.run500Turns"]
            XCTAssertTrue(stressButton.waitForExistence(timeout: 5))
            let ready = XCTNSPredicateExpectation(
                predicate: NSPredicate(format: "enabled == true"),
                object: stressButton
            )
            XCTAssertEqual(
                XCTWaiter.wait(for: [ready], timeout: fixtureID == "long-chapter" ? 30 : 12),
                .completed,
                "Navigator did not reach a stable viewport for \(fixtureID)"
            )
            let probeButton = app.buttons["reader.runFeatureProbe"]
            XCTAssertTrue(probeButton.waitForExistence(timeout: 5))
            probeButton.tap()
            let probeResult = app.staticTexts["reader.featureProbeResult"]
            XCTAssertTrue(probeResult.waitForExistence(timeout: fixtureID == "long-chapter" ? 30 : 10))
            XCTAssertTrue(probeResult.label.hasPrefix("pass"), "Feature probe failed for \(fixtureID): \(probeResult.label)")
            app.buttons["reader.nextPage"].tap()
            app.buttons["reader.close"].tap()
            app.terminate()
        }
    }

    func testBasicKF8FiveHundredTurnsAndLifecycleTransitions() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--reader-poc-ui-test", "--stress-smoke"]
        app.launch()
        try openNavigator(fixtureID: "basic-kf8", in: app)

        let stressButton = app.buttons["reader.run500Turns"]
        let ready = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "enabled == true"),
            object: stressButton
        )
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 12), .completed)
        stressButton.tap()

        let result = app.staticTexts["reader.stressResult"]
        XCTAssertTrue(result.waitForExistence(timeout: 300))
        XCTAssertTrue(result.label.hasPrefix("pass"), "Unexpected stress result: \(result.label)")

        for index in 0 ..< 20 {
            XCUIDevice.shared.orientation = index.isMultiple(of: 2) ? .landscapeRight : .portrait
        }
        XCUIDevice.shared.orientation = .portrait
        for _ in 0 ..< 20 {
            XCUIDevice.shared.press(.home)
            app.activate()
        }
        app.buttons["reader.close"].tap()
        app.terminate()
    }

    func testEveryFixtureTurnsPagesRotatesAndTransitionsBackground() throws {
        for fixtureID in fixtureIDs {
            let app = XCUIApplication()
            app.launchArguments = ["--reader-poc-ui-test"]
            app.launch()
            try openNavigator(fixtureID: fixtureID, in: app)

            let stressButton = app.buttons["reader.run500Turns"]
            XCTAssertTrue(stressButton.waitForExistence(timeout: fixtureID == "long-chapter" ? 15 : 8))
            expectation(for: NSPredicate(format: "enabled == true"), evaluatedWith: stressButton)
            waitForExpectations(timeout: fixtureID == "long-chapter" ? 20 : 10)
            stressButton.tap()
            XCTAssertTrue(app.staticTexts["reader.stressResult"].waitForExistence(timeout: fixtureID == "long-chapter" ? 900 : 300))

            for index in 0 ..< 20 {
                XCUIDevice.shared.orientation = index.isMultiple(of: 2) ? .landscapeLeft : .portrait
            }
            XCUIDevice.shared.orientation = .portrait

            for _ in 0 ..< 20 {
                XCUIDevice.shared.press(.home)
                app.activate()
            }
            app.buttons["reader.close"].tap()
            app.terminate()
        }
    }

    private func openNavigator(fixtureID: String, in app: XCUIApplication) throws {
        let fixture = app.descendants(matching: .any)["fixture.\(fixtureID)"]
        if !fixture.waitForExistence(timeout: 2) {
            app.swipeUp()
            app.swipeUp()
        }
        XCTAssertTrue(fixture.waitForExistence(timeout: 5), "Fixture row not found: \(fixtureID)")
        fixture.tap()

        let load = app.buttons["fixture.\(fixtureID).load"]
        XCTAssertTrue(load.waitForExistence(timeout: 5))
        load.tap()
        let open = app.buttons["fixture.\(fixtureID).openNavigator"]
        XCTAssertTrue(open.waitForExistence(timeout: fixtureID == "long-chapter" ? 30 : 10))
        open.tap()
        XCTAssertTrue(app.buttons["reader.close"].waitForExistence(timeout: fixtureID == "long-chapter" ? 20 : 10))
    }
}
