import Foundation
import XCTest
import ErmaoShared
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
        var keys = [
            "reader.error.PUBLICATION_UNAVAILABLE",
            "reader.error.UNAUTHORIZED",
            "reader.error.FORBIDDEN",
            "reader.error.PUBLICATION_RESPONSE_INVALID",
            "reader.error.SERVER_UNAVAILABLE",
            "reader.error.REQUEST_TIMEOUT",
            "reader.error.TLS_FAILURE",
            "reader.error.RATE_LIMITED",
            "reader.error.PUBLICATION_TXT_NUL_CHARACTER",
            "reader.error.PUBLICATION_TXT_ENCODING_UNSUPPORTED",
            "reader.error.PUBLICATION_TXT_EMPTY",
            "reader.download.preparing",
            "reader.download.failed",
            "reader.download.transferring",
            "reader.download.queued",
            "reader.download.paused",
            "reader.download.cancel",
            "reader.error.PUBLICATION_TOO_LARGE",
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
            "reader.font.songti",
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
            "reader.error.PUBLICATION_DRM_UNSUPPORTED",
            "reader.error.PERSISTENCE_FAILED",
            "reader.error.PDF_RANGE_UNSUPPORTED",
            "reader.error.PDF_RANGE_INVALID",
            "reader.error.PDF_RESOURCE_CHANGED",
            "reader.error.PDF_CACHE_IO",
            "reader.error.PDF_INVALID",
            "reader.error.PDF_PAGE_LOAD_FAILED",
            "reader.error.PDF_RENDER_FAILED",
            "reader.pdf.page.description",
            "nativeManagement.appliedFields",
            "nativeManagement.skippedFields",
            "nativeManagement.coverResult.applied",
            "nativeManagement.coverResult.notSelected",
            "nativeManagement.coverResult.failed",
            "nativeManagement.notice.refreshFailed",
            "nativeManagement.readingStatus",
            "nativeManagement.failure.General",
            "nativeManagement.current %@",
            "nativeManagement.candidate %@",
            "nativeManagement.sourceCount %lld",
        ]
        keys += ManagementField.entries.map { "nativeManagement.field.\($0.wireName)" }
        keys += CoverEdit.entries.map { "nativeManagement.cover.\($0.name)" }
        keys += ManagementSaveStage.entries.map { "nativeManagement.failure.\($0.name)" }
        keys += ["saved", "queued", "alreadyQueued", "deleted", "metadataPartial"].map { "nativeManagement.notice.\($0)" }
        for kind in ManagementObject.entries {
            for completed in [false, true] {
                keys += ManagementAction.entries.map { managementActionKey($0.name, kind: kind, completed: completed) }
            }
        }

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

    func testEveryReaderCatalogRuntimeKeyResolvesForTheActiveAppLocale() {
        var labels: [(key: String, chinese: String, english: String)] = []
        labels += ReaderSettingsCatalog.shared.sections
            .filter { !$0.chinese.isEmpty || !$0.english.isEmpty }
            .map { ($0.key, $0.chinese, $0.english) }
        labels += ReaderSettingsCatalog.shared.settings.map { ($0.key, $0.chinese, $0.english) }
        labels += ReaderSettingsCatalog.shared.settings.flatMap { setting in
            setting.options.map { ($0.key, $0.chinese, $0.english) }
        }
        labels += ReaderSettingsCatalog.shared.availabilityReasons.values.map {
            ($0.key, $0.chinese, $0.english)
        }

        for label in labels {
            let chinese = localizedReaderOption(
                label.key,
                locale: Locale(identifier: "zh-Hans-CN")
            )
            XCTAssertEqual(chinese, label.chinese, "Unresolved Simplified Chinese key: \(label.key)")
            XCTAssertNotEqual(chinese, label.key)

            let english = localizedReaderOption(
                label.key,
                locale: Locale(identifier: "en-US")
            )
            XCTAssertEqual(english, label.english, "Unresolved English key: \(label.key)")
            XCTAssertNotEqual(english, label.key)
        }
    }
}
