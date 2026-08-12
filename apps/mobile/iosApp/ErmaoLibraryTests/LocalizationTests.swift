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
            "auth.login.entry.subtitle",
            "auth.credentials.storageFailed.title",
            "auth.credentials.storageFailed.message",
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
            "server.delete.current.action",
            "server.delete.current.confirm.title",
            "server.switch.sheet.title",
            "server.tls.accept.action",
            "server.tls.restore.action",
            "me.server.manage",
            "me.logout.confirm.title",
            "settings.profile.title",
            "settings.profile.subtitle",
            "settings.avatar.choose.action",
            "settings.avatar.error.tooLarge",
            "settings.security.title",
            "settings.security.subtitle",
            "settings.security.email.section",
            "settings.security.changePassword.action",
            "settings.security.purgeFailed",
            "settings.language.title",
            "settings.language.zhCN",
            "settings.language.enUS",
            "settings.server.current",
            "settings.about.title",
            "settings.about.serverVersion",
            "settings.about.serverVersion.retry.hint",
            "tab.home",
            "tab.library",
            "tab.shelves",
            "tab.me",
            "home.continue.title",
            "home.recentReading.title",
            "home.recentAdded.title",
            "library.search.works",
            "library.scope.series",
            "library.filter.title",
            "library.pagination.error",
            "facet.series.title",
            "content.inaccessible.title",
            "work.detail.title",
            "work.reader.unavailable.message",
            "work.reader.accessibility.hint",
            "reader.close",
            "reader.download.preparing",
            "reader.opening",
            "reader.toc",
            "reader.settings",
            "reader.progress",
            "reader.restore.warning.message",
            "reader.save.failure.message",
            "reader.error.CORRUPT_FILE",
            "reader.error.DRM_PROTECTED",
            "reader.error.PERSISTENCE_FAILED",
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
