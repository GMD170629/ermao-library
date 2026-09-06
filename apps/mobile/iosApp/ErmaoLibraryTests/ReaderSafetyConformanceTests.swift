import CryptoKit
import Foundation
import XCTest
@preconcurrency import ErmaoShared
@testable import ErmaoLibrary

/// Executes the iOS side of the reader-safety-v2 suite. Markup and CSS cases pass through the
/// production iOS adapter and the existing KMP facade. The facade exposes the sanitized content
/// and typed rejection, but it does not expose an event trace; this test intentionally reports
/// that trace as empty instead of reconstructing one from fixture expectations.
final class ReaderSafetyConformanceTests: XCTestCase {
    func testIosReaderSafetyConformanceReport() async throws {
        let bundle = Bundle(for: Self.self)
        let suite = try load(ConformanceSuite.self, bundle: bundle, resource: "reader-safety-v2-conformance-suite")
        let manifest = try load(ConformanceManifest.self, bundle: bundle, resource: "reader-safety-v2-manifest")
        XCTAssertEqual(suite.policyId, "shuku.reader-safety")
        XCTAssertEqual(suite.policyVersion, ErmaoShared.PublicKt.readerSafetyPolicyVersion())
        XCTAssertEqual(suite.policyDigest, ErmaoShared.PublicKt.readerSafetyPolicyDigest())
        XCTAssertEqual(manifest.policyDigest, suite.policyDigest)

        let fixtures = Dictionary(uniqueKeysWithValues: manifest.cases.map { ($0.id, $0) })
        var reportResults: [ReportResult] = []
        var omissions: [String] = []
        for suiteCase in suite.cases where suiteCase.consumers.contains("IOS") {
            let fixture = try XCTUnwrap(fixtures[suiteCase.id])
            XCTAssertEqual(sha256(fixture.input), fixture.inputSha256, suiteCase.id)
            do {
                let actual = try await evaluate(suiteCase, fixture: fixture)
                let expected = fixture.expected
                if actual.terminalRuleId != nil || actual.errorCode != nil {
                    XCTAssertEqual(actual.terminalRuleId, Optional(expected.terminalRuleId), suiteCase.id)
                    XCTAssertEqual(actual.action, Optional(expected.action), suiteCase.id)
                    XCTAssertEqual(actual.errorCode, expected.errorCode, suiteCase.id)
                } else {
                    XCTAssertNil(expected.errorCode, suiteCase.id)
                }
                XCTAssertEqual(actual.semanticProjectionSha256, expected.semanticProjectionSha256, suiteCase.id)
                reportResults.append(actual)
            } catch let omission as ConformanceOmission {
                omissions.append(omission.reason)
            }
        }

        XCTAssertEqual(
            reportResults.count + omissions.count,
            suite.cases.filter { $0.consumers.contains("IOS") }.count
        )
        let report = ConformanceReport(
            schemaVersion: 1,
            policyId: suite.policyId,
            policyVersion: suite.policyVersion,
            policyDigest: suite.policyDigest,
            consumer: "IOS",
            engine: "ios-readium-native-adapters",
            results: reportResults,
            omissions: omissions
        )
        if let output = ProcessInfo.processInfo.environment["READER_SAFETY_CONFORMANCE_OUTPUT"] {
            try JSONEncoder().encode(report).write(to: URL(fileURLWithPath: output), options: .atomic)
        }
    }

    private func evaluate(
        _ suiteCase: SuiteCase,
        fixture: FixtureCase
    ) async throws -> ReportResult {
        let actual: ActualDecision
        switch suiteCase.evaluator {
        case "REFLOWABLE_MARKUP", "REFLOWABLE_NAMED_ENTITIES",
             "REFLOWABLE_MARKUP_SANITIZE", "REFLOWABLE_URI",
             "REFLOWABLE_CSS", "REFLOWABLE_SVG":
            actual = try evaluateMarkup(
                suiteCase,
                source: fixture.input,
                expectedProjectionSha256: fixture.expected.semanticProjectionSha256
            )
        case "ARCHIVE_STRUCTURE":
            actual = try evaluateArchiveStructure(suiteCase, format: fixture.format, source: fixture.input)
        case "EPUB_ARCHIVE_CRC":
            actual = try await evaluateArchiveCRC(suiteCase, format: fixture.format, source: fixture.input)
        case "POLICY_DECISION":
            actual = try evaluatePolicyDecision(suiteCase, source: fixture.input)
        default:
            actual = try evaluateFactCase(suiteCase, format: fixture.format, source: fixture.input)
        }
        return ReportResult(
            caseId: suiteCase.id,
            inputSha256: sha256(fixture.input),
            terminalRuleId: actual.ruleId,
            action: actual.action,
            errorCode: actual.errorCode,
            orderedRuleEvents: actual.events,
            semanticProjectionSha256: actual.semanticProjection.map(sha256)
        )
    }

    private func evaluateMarkup(
        _ suiteCase: SuiteCase,
        source: String,
        expectedProjectionSha256: String?
    ) throws -> ActualDecision {
        let data = Data(source.utf8)
        // The fixtures intentionally include fragments.  Exercise the production
        // resource adapter with the original XML/CSS/SVG when it can parse that
        // resource, and use a valid XHTML envelope only for fragment probes that
        // represent a rendered reading-order document.
        let adapterData: Data
        let mediaType: String?
        switch suiteCase.evaluator {
        case "REFLOWABLE_CSS":
            adapterData = data
            mediaType = "text/css"
        case "REFLOWABLE_SVG":
            adapterData = data
            mediaType = "image/svg+xml"
        default:
            let facade = ErmaoShared.ReaderSafetyFacade()
            let root = facade.rootElementName(markup: source)?.lowercased()
            let completeHtml = root == "html" &&
                source.range(of: "<head", options: .caseInsensitive) != nil &&
                source.range(of: "<body", options: .caseInsensitive) != nil
            let renderedFragment = suiteCase.evaluator != "REFLOWABLE_MARKUP" &&
                suiteCase.evaluator != "REFLOWABLE_NAMED_ENTITIES"
            if renderedFragment || (root == "html" && !completeHtml) {
                // The fixture may be a deliberately minimal HTML/XML probe. Keep the
                // production adapter call real while supplying the smallest valid
                // Readium reading-order envelope; semantic projection still uses source.
                let fragment = root == "html" ? "" : source
                adapterData = Data("<html><head></head><body>\(fragment)</body></html>".utf8)
                mediaType = "application/xhtml+xml"
            } else {
                adapterData = data
                mediaType = nil
            }
        }
        let adapterOutput: Data
        do {
            adapterOutput = try IosPublicationSecurityPolicy.prepareResource(
                data: adapterData,
                mediaType: mediaType
            )
            XCTAssertFalse(adapterOutput.isEmpty, suiteCase.id)
        } catch let error as IosPublicationSecurityError {
            if case let .rejected(ruleId, errorCode) = error {
                return actualDecision(
                    ruleId: ruleId,
                    errorCode: errorCode,
                    format: "EPUB",
                    resourceRole: "READING_ORDER"
                )
            }
            throw error
        }

        let facade = ErmaoShared.ReaderSafetyFacade()
        let result: ErmaoShared.ReaderSafetyMarkupResult = suiteCase.evaluator == "REFLOWABLE_CSS"
            ? facade.sanitizeCss(css: source, sourceByteCount: Int64(data.count))
            : facade.sanitizeMarkup(markup: source, sourceByteCount: Int64(data.count))
        guard let accepted = result as? ErmaoShared.ReaderSafetyMarkupResultAccepted else {
            if let rejected = result as? ErmaoShared.ReaderSafetyMarkupResultRejected {
                return actualDecision(
                    ruleId: rejected.failure.ruleId,
                    errorCode: rejected.failure.errorCode,
                    format: "EPUB",
                    resourceRole: "READING_ORDER"
                )
            }
            throw factFailure("\(suiteCase.id): sanitizer returned an unknown result")
        }
        if suiteCase.evaluator == "REFLOWABLE_CSS" {
            // CSS has no XHTML envelope in the production adapter, so its output is directly
            // comparable with the facade's actual sanitized stylesheet.
            let actualCss = try XCTUnwrap(String(data: adapterOutput, encoding: .utf8))
            XCTAssertEqual(actualCss, accepted.value.markup, suiteCase.id)
        }
        let markup = accepted.value.markup
        let semantic: String
        if suiteCase.semanticProjection == "ROOT_LOCAL_NAME" {
            semantic = try XCTUnwrap(facade.rootElementName(markup: markup))
        } else {
            semantic = markup
        }
        if let expectedProjectionSha256 {
            XCTAssertEqual(sha256(semantic), expectedProjectionSha256, suiteCase.id)
        }
        return ActualDecision(
            ruleId: nil,
            action: nil,
            errorCode: nil,
            events: [],
            semanticProjection: semantic
        )
    }

    private func evaluateArchiveStructure(
        _ suiteCase: SuiteCase,
        format: String,
        source: String
    ) throws -> ActualDecision {
        let entries = source.split(separator: "|", omittingEmptySubsequences: false).enumerated().map { index, path in
            IosEpubArchiveSafetyPreflight.EntryFacts(
                path: String(path),
                isDirectory: false,
                isSymbolicLink: false,
                isEncrypted: false,
                uncompressedSize: 16,
                compressedSize: 16,
                crc32: 0,
                localHeaderOffset: UInt64(index * 64),
                dataOffset: UInt64(index * 64 + 30),
                physicalEndOffset: UInt64(index * 64 + 46)
            )
        }
        let result: IosEpubArchiveSafetyPreflight.IosEpubArchiveSafetyResult
        do {
            result = try IosEpubArchiveSafetyPreflight.verifyMetadata(entries, archiveLength: 1_024)
        } catch let failure as IosReaderFailure {
            throw ConformanceOmission(
                reason: "\(suiteCase.id): iOS archive preflight reported \(failure.safeContext["ruleId"] ?? "unknown") before a resource role was available"
            )
        }
        let firstPath = source.split(separator: "|", maxSplits: 1).first.map(String.init) ?? ""
        guard let failure = result.quarantineFor(path: firstPath) else {
            throw factFailure("\(suiteCase.id): archive adapter did not quarantine the unsafe entry")
        }
        return actualDecision(
            ruleId: failure.ruleId,
            errorCode: failure.errorCode,
            format: format,
            resourceRole: "PUBLICATION"
        )
    }

    private func evaluateArchiveCRC(
        _ suiteCase: SuiteCase,
        format: String,
        source: String
    ) async throws -> ActualDecision {
        let encoded = String(source.dropFirst("base64:".count))
        let fileURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("reader-safety-\(UUID().uuidString).epub")
        defer { try? FileManager.default.removeItem(at: fileURL) }
        try XCTUnwrap(Data(base64Encoded: encoded)).write(to: fileURL, options: .atomic)
        let archive = try await IosEpubArchiveSafetyPreflight.verify(fileURL: fileURL)
        let expected = try XCTUnwrap(archive.expectedFor(path: "unused.bin"))
        var actualRuleId: String?
        var actualErrorCode: String?
        XCTAssertThrowsError(
            try IosEpubArchiveSafetyPreflight.verifyResourceBytes(
                expected: expected,
                data: Data("unused-entry-crc-payload".utf8)
            )
        ) { error in
            guard case let IosPublicationSecurityError.rejected(ruleId, errorCode) = error else {
                return XCTFail("unexpected iOS resource verification error: \(error)")
            }
            actualRuleId = ruleId
            actualErrorCode = errorCode
        }
        let ruleId = try XCTUnwrap(actualRuleId)
        let errorCode = try XCTUnwrap(actualErrorCode)
        return actualDecision(
            ruleId: ruleId,
            errorCode: errorCode,
            format: format,
            resourceRole: "OPTIONAL_RESOURCE"
        )
    }

    private func evaluatePolicyDecision(
        _ suiteCase: SuiteCase,
        source: String
    ) throws -> ActualDecision {
        let context = try JSONDecoder().decode(PolicyContext.self, from: Data(source.utf8))
        let decision: ErmaoShared.ReaderSafetyDecisionProjection
        do {
            decision = ErmaoShared.PublicKt.readerSafetyEvaluateDecision(
                format: context.format,
                resourceRole: context.resourceRole,
                facts: context.facts,
                enforcementAvailable: context.enforcementAvailable,
                canIsolate: context.canIsolate
            )
        } catch {
            throw factFailure("\(suiteCase.id): generated policy rejected the fixture format or resource role")
        }
        let ruleId = try XCTUnwrap(decision.ruleId, suiteCase.id)
        XCTAssertEqual(ruleId, suiteCase.ruleId)
        return ActualDecision(
            ruleId: ruleId,
            action: decision.action,
            errorCode: decision.errorCode,
            events: [],
            semanticProjection: nil
        )
    }

    private func evaluateFactCase(
        _ suiteCase: SuiteCase,
        format _: String,
        source _: String
    ) throws -> ActualDecision {
        throw ConformanceOmission(
            reason: "\(suiteCase.id): iOS has no production adapter for the \(suiteCase.evaluator) fact evaluator"
        )
    }

    private func actualDecision(
        ruleId: String,
        errorCode: String?,
        format: String,
        resourceRole: String = "PUBLICATION",
        semanticProjection: String? = nil
    ) -> ActualDecision {
        let decision = ErmaoShared.PublicKt.readerSafetyEvaluateRuleDecision(
            format: format,
            resourceRole: resourceRole,
            ruleId: ruleId,
            enforcementAvailable: true,
            canIsolate: resourceRole == "OPTIONAL_RESOURCE"
        )
        XCTAssertEqual(decision.ruleId, ruleId)
        XCTAssertEqual(decision.errorCode, errorCode)
        let action = decision.action
        return ActualDecision(
            ruleId: ruleId,
            action: action,
            errorCode: errorCode,
            events: [],
            semanticProjection: semanticProjection
        )
    }


    private func factFailure(_ message: String) -> NSError {
        NSError(domain: "ReaderSafetyConformance", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }


    private func sha256(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func load<T: Decodable>(
        _: T.Type,
        bundle: Bundle,
        resource: String
    ) throws -> T {
        let url = try XCTUnwrap(bundle.url(forResource: resource, withExtension: "json"))
        return try JSONDecoder().decode(T.self, from: Data(contentsOf: url))
    }
}

private struct ConformanceSuite: Decodable {
    let policyId: String
    let policyVersion: Int
    let policyDigest: String
    let cases: [SuiteCase]
}

private struct SuiteCase: Decodable {
    let id: String
    let ruleId: String
    let evaluator: String
    let semanticProjection: String
    let consumers: [String]
}

private struct ConformanceManifest: Decodable {
    let policyDigest: String
    let cases: [FixtureCase]
}

private struct FixtureCase: Decodable {
    let id: String
    let format: String
    let input: String
    let inputSha256: String
    let expected: ExpectedCase
}

private struct ExpectedCase: Decodable {
    let terminalRuleId: String
    let action: String
    let errorCode: String?
    let orderedRuleEvents: [String]
    let semanticProjectionSha256: String?
}

private struct PolicyContext: Decodable {
    let format: String
    let resourceRole: String
    let facts: [String]
    let enforcementAvailable: Bool
    let canIsolate: Bool
}

private struct ActualDecision {
    let ruleId: String?
    let action: String?
    let errorCode: String?
    let events: [String]
    let semanticProjection: String?
}

private struct ConformanceOmission: Error {
    let reason: String
}

private struct ReportResult: Encodable {
    let caseId: String
    let inputSha256: String
    let terminalRuleId: String?
    let action: String?
    let errorCode: String?
    let orderedRuleEvents: [String]
    let semanticProjectionSha256: String?
}

private struct ConformanceReport: Encodable {
    let schemaVersion: Int
    let policyId: String
    let policyVersion: Int
    let policyDigest: String
    let consumer: String
    let engine: String
    let results: [ReportResult]
    let omissions: [String]
}
