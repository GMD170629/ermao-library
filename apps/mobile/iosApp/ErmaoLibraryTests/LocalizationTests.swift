import Foundation
import XCTest
@testable import ErmaoLibrary

final class LocalizationTests: XCTestCase {
    func testRequiredStringsExistInEnglishAndSimplifiedChinese() throws {
        let keys = [
            "server.empty.title",
            "server.add.action",
            "server.tls.risk.title",
            "server.tls.ignore.action",
            "server.incompatible.title",
            "setup.required.title",
            "setup.submit.action",
            "setup.confirmPassword.mismatch",
            "setup.field.invalid",
            "auth.login.action",
            "auth.invalidCredentials",
            "auth.reauthenticate.title",
            "auth.offline.action.format",
            "common.operationFailed.title",
            "common.operationFailed",
            "common.requestFailed",
            "session.unavailable.title",
            "offline.deferred.title",
            "offline.empty.title",
            "server.saved.section",
            "server.edit.action",
            "server.delete.confirm.title",
            "server.tls.restore.action",
            "me.server.manage",
            "me.logout.confirm.title",
            "tab.home",
            "tab.library",
            "tab.shelves",
            "tab.me",
        ]

        for locale in ["en", "zh-Hans"] {
            let localizationPath = try XCTUnwrap(
                Bundle.main.path(forResource: locale, ofType: "lproj"),
                "Missing \(locale) localization bundle"
            )
            let bundle = try XCTUnwrap(Bundle(path: localizationPath))
            for key in keys {
                let localized = bundle.localizedString(forKey: key, value: nil, table: nil)
                XCTAssertNotEqual(localized, key, "Missing \(key) in \(locale)")
                XCTAssertFalse(localized.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
    }
}
