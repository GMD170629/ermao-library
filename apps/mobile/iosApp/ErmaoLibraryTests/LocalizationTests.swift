import Foundation
import XCTest
@testable import ErmaoLibrary

final class LocalizationTests: XCTestCase {
    func testCompatibilityCopyReflectsTheActualFailure() {
        XCTAssertEqual(
            ServerCompatibilityCopy.resolve(reasonCode: "CLIENT_UPDATE_REQUIRED"),
            ServerCompatibilityCopy(
                titleKey: "server.compatibility.appUpdate.title",
                messageKey: "server.compatibility.appUpdate.message"
            )
        )
        XCTAssertEqual(
            ServerCompatibilityCopy.resolve(reasonCode: "UNSUPPORTED_READER_SCHEMA"),
            ServerCompatibilityCopy(
                titleKey: "server.compatibility.serverUpdate.title",
                messageKey: "server.compatibility.serverUpdate.message"
            )
        )
        XCTAssertEqual(
            ServerCompatibilityCopy.resolve(reasonCode: "UNEXPECTED_SERVICE"),
            ServerCompatibilityCopy(
                titleKey: "server.compatibility.invalidResponse.title",
                messageKey: "server.compatibility.invalidResponse.message"
            )
        )
    }

    func testRequiredStringsExistInEnglishAndSimplifiedChinese() throws {
        let keys = [
            "server.empty.title",
            "server.add.action",
            "server.tls.risk.title",
            "server.tls.ignore.action",
            "server.incompatible.title",
            "server.compatibility.appUpdate.title",
            "server.compatibility.appUpdate.message",
            "server.compatibility.serverUpdate.title",
            "server.compatibility.serverUpdate.message",
            "server.compatibility.invalidResponse.title",
            "server.compatibility.invalidResponse.message",
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
            "common.operationFailed.title",
            "common.operationFailed",
            "common.requestFailed",
            "session.unavailable.title",
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
            "library.scope.works",
            "library.scope.series",
            "library.results.works.format",
            "library.empty.works.title",
            "library.book.accessibility.progress",
            "library.filter.title",
            "library.pagination.error",
            "facet.series.title",
            "facet.series.book.accessibility.format",
            "content.inaccessible.title",
            "work.detail.title",
            "work.reader.unavailable.message",
            "work.reader.accessibility.hint",
            "reader.close",
            "reader.loading.publication",
            "reader.opening",
            "reader.toc",
            "reader.settings",
            "reader.progress",
            "reader.appearance",
            "reader.notes",
            "reader.bookmarks",
            "reader.bookmarks.pending",
            "reader.theme.day",
            "reader.theme.warm",
            "reader.theme.green",
            "reader.theme.night",
            "reader.theme.black",
            "reader.font.pingfang",
            "reader.font.heiti",
            "reader.font.songti",
            "reader.font.yahei",
            "reader.font.kaiti",
            "reader.margin.narrow",
            "reader.margin.standard",
            "reader.margin.wide",
            "reader.progressStyle.auto",
            "reader.progressStyle.percent",
            "reader.progressStyle.position",
            "reader.progressStyle.remaining",
            "reader.progressStyle.hidden",
            "reader.tapZones.standard",
            "reader.tapZones.reversed",
            "reader.tapZones.disabled",
            "reader.spread.auto",
            "reader.spread.single",
            "reader.spread.double",
            "reader.alignment.publisher",
            "reader.alignment.left",
            "reader.alignment.justify",
            "reader.settings.reset",
            "reader.restore.warning.message",
            "reader.resume.prompt.format",
            "reader.resume.return",
            "reader.resume.returnFailed",
            "work.chapter.current",
            "work.chapter.read",
            "reader.save.failure.message",
            "reader.error.CORRUPT_FILE",
            "reader.error.DRM_PROTECTED",
            "reader.error.PERSISTENCE_FAILED",
            "reader.error.PDF_RANGE_UNSUPPORTED",
            "reader.error.PDF_RANGE_INVALID",
            "reader.error.PDF_RESOURCE_CHANGED",
            "reader.error.PDF_CACHE_IO",
            "reader.error.PDF_ENCRYPTED",
            "reader.error.PDF_INVALID",
            "reader.error.PDF_PAGE_LOAD_FAILED",
            "reader.error.PDF_RENDER_FAILED",
            "reader.pdf.page.description",
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

    func testDynamicReaderOptionLabelsUseLocalizedRuntimeKeys() throws {
        let expectations = [
            (locale: "en", key: "reader.theme.warm", value: "Warm"),
            (locale: "en", key: "reader.font.pingfang", value: "PingFang"),
            (locale: "en", key: "reader.margin.standard", value: "Standard"),
            (locale: "zh-Hans", key: "reader.theme.warm", value: "暖色"),
            (locale: "zh-Hans", key: "reader.font.pingfang", value: "苹方"),
            (locale: "zh-Hans", key: "reader.margin.standard", value: "标准"),
        ]

        for expectation in expectations {
            let localizationPath = try XCTUnwrap(
                Bundle.main.path(forResource: expectation.locale, ofType: "lproj")
            )
            let bundle = try XCTUnwrap(Bundle(path: localizationPath))
            XCTAssertEqual(
                localizedReaderOption(expectation.key, bundle: bundle),
                expectation.value
            )
        }
    }
}
