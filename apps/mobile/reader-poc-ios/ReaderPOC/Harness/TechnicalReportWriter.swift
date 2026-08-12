import Foundation
import UIKit

struct TechnicalRunReport: Codable, Sendable {
    let schemaVersion: Int
    let recordedAt: Date
    let fixture: String
    let sourceFormat: MobiFormat
    let operatingSystem: String
    let deviceModel: String
    let libmobiVersion: String
    let readiumVersion: String
    let publicationBuildMilliseconds: Double
    let firstPageMilliseconds: Double?
    let resourceCount: Int
    let totalExtractedBytes: Int
    let verifiedReferenceCount: Int
    let warningCodes: [MobiWarningCode]
    let resourceFailures: [String]
    let navigatorWarnings: [String]
    let featureProbe: FeatureProbeResult?
    let pageTurnStress: PageTurnStressResult?
    let grade: TechnicalGrade
}

enum TechnicalReportWriter {
    static func write(_ report: TechnicalRunReport) throws -> URL {
        let fileManager = FileManager.default
        let directory = try fileManager.url(
            for: .documentDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        ).appendingPathComponent("ReaderPOCReports", isDirectory: true)
        try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        let date = ISO8601DateFormatter().string(from: report.recordedAt).replacingOccurrences(of: ":", with: "-")
        let url = directory.appendingPathComponent("\(report.fixture)-\(date).json")
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        encoder.dateEncodingStrategy = .iso8601
        try encoder.encode(report).write(to: url, options: .atomic)
        return url
    }

    @MainActor
    static func makeReport(
        loaded: ReaderPOCStore.LoadedFixture,
        session: NavigatorSession
    ) -> TechnicalRunReport {
        let stressGrade = session.lastStressResult?.grade ?? .awaitingEvidence
        let grade: TechnicalGrade
        let featureGrade = session.lastFeatureProbe?.grade ?? .awaitingEvidence
        if loaded.performanceGrade == .fail || stressGrade == .fail || featureGrade == .fail || !session.resourceFailures.isEmpty {
            grade = .fail
        } else if loaded.performanceGrade == .degraded || stressGrade == .degraded || featureGrade == .degraded {
            grade = .degraded
        } else if stressGrade == .awaitingEvidence || featureGrade == .awaitingEvidence {
            grade = .awaitingEvidence
        } else {
            grade = .pass
        }
        return TechnicalRunReport(
            schemaVersion: 2,
            recordedAt: .now,
            fixture: loaded.descriptor.filename,
            sourceFormat: loaded.result.book.format,
            operatingSystem: UIDevice.current.systemName + " " + UIDevice.current.systemVersion,
            deviceModel: UIDevice.current.model,
            libmobiVersion: NativeMobiExtractor.libmobiVersion,
            readiumVersion: "3.11.0",
            publicationBuildMilliseconds: loaded.publicationBuildMilliseconds,
            firstPageMilliseconds: session.firstPageMilliseconds,
            resourceCount: loaded.result.preflight.resourceCount,
            totalExtractedBytes: loaded.result.preflight.totalBytes,
            verifiedReferenceCount: loaded.result.preflight.verifiedReferenceCount,
            warningCodes: loaded.result.book.warnings.map(\.code),
            resourceFailures: session.resourceFailures,
            navigatorWarnings: session.navigatorWarnings,
            featureProbe: session.lastFeatureProbe,
            pageTurnStress: session.lastStressResult,
            grade: grade
        )
    }
}
