import Darwin
import Foundation
import ReadiumNavigator
import ReadiumShared
import UIKit

struct LocatorPublicationFingerprint: Equatable, Sendable {
    let originalFileHash: String
    let parser: String
    let normalization: String

    var jsonObject: [String: String] {
        [
            "originalFileHash": originalFileHash,
            "parser": parser,
            "normalization": normalization,
        ]
    }
}

@MainActor
final class NavigatorSession: ObservableObject {
    @Published private(set) var isReady = false
    @Published private(set) var resourceFailures: [String] = []
    @Published private(set) var navigatorWarnings: [String] = []
    @Published private(set) var pageTurnProgress = 0
    @Published private(set) var lastStressResult: PageTurnStressResult?
    @Published private(set) var javascriptResult = ""
    @Published private(set) var lastFeatureProbe: FeatureProbeResult?
    @Published private(set) var firstPageMilliseconds: Double?
    @Published private(set) var locatorExchangeResult = ""

    weak var navigator: EPUBNavigatorViewController?
    private var fingerprint: LocatorPublicationFingerprint?
    private var attachedAt: ContinuousClock.Instant?
    func attach(_ navigator: EPUBNavigatorViewController, fingerprint: LocatorPublicationFingerprint) {
        self.navigator = navigator
        self.fingerprint = fingerprint
        isReady = false
        firstPageMilliseconds = nil
        attachedAt = ContinuousClock().now
    }

    func markReady() {
        guard !isReady else { return }
        isReady = true
        if let attachedAt {
            firstPageMilliseconds = attachedAt.duration(to: ContinuousClock().now).milliseconds
        }
    }

    func recordResourceFailure(href: String, error: Error) {
        resourceFailures.append("\(href): \(error.localizedDescription)")
    }

    func recordNavigatorWarning(_ message: String) {
        navigatorWarnings.append(message)
    }

    func waitUntilReady(timeout: Duration = .seconds(10)) async -> Bool {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: timeout)
        while clock.now < deadline {
            if isReady { return true }
            try? await Task.sleep(for: .milliseconds(100))
        }
        return isReady
    }

    func copyExactLocatorToPasteboard() async {
        guard let navigator,
              let fingerprint,
              let visibleLocator = await navigator.firstVisibleElementLocator()
        else {
            locatorExchangeResult = String(localized: "locator.captureFailed")
            return
        }
        do {
            let boundedLocator = visibleLocator.copy(text: { text in
                text.highlight = text.highlight.map { String($0.unicodeScalars.prefix(512)) }
                text.before = text.before.map { String($0.unicodeScalars.prefix(256)) }
                text.after = text.after.map { String($0.unicodeScalars.prefix(256)) }
            })
            let payload = try JSONSerialization.jsonObject(with: boundedLocator.jsonData())
            let envelope: [String: Any] = [
                "engine": "readium",
                "platform": "ios",
                "version": "readium-swift:3.11.0",
                "publication": fingerprint.jsonObject,
                "payload": payload,
            ]
            let data = try JSONSerialization.data(
                withJSONObject: envelope,
                options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
            )
            guard data.count <= 65_536, let json = String(data: data, encoding: .utf8) else {
                locatorExchangeResult = String(localized: "locator.payloadTooLarge")
                return
            }
            UIPasteboard.general.string = json
            locatorExchangeResult = String(localized: "locator.copied")
        } catch {
            locatorExchangeResult = error.localizedDescription
        }
    }

    func goToLocatorFromPasteboard() async {
        guard let navigator,
              let json = UIPasteboard.general.string,
              let data = json.data(using: .utf8),
              data.count <= 65_536
        else {
            locatorExchangeResult = String(localized: "locator.pasteFailed")
            return
        }
        do {
            let decoded = try JSONSerialization.jsonObject(with: data)
            let payload: Any
            if let envelope = decoded as? [String: Any] {
                if let engine = envelope["engine"] as? String, engine != "readium" {
                    locatorExchangeResult = String(localized: "locator.wrongEngine")
                    return
                }
                if let remote = envelope["publication"] as? [String: String],
                   let local = fingerprint,
                   remote != local.jsonObject
                {
                    locatorExchangeResult = String(localized: "locator.fingerprintMismatch")
                    return
                }
                payload = envelope["payload"] ?? envelope
            } else {
                payload = decoded
            }
            guard let locatorJSON = JSONValue(payload),
                  let locator = try Locator(json: locatorJSON, warnings: nil)
            else {
                locatorExchangeResult = String(localized: "locator.invalid")
                return
            }
            let moved = await navigator.go(to: locator, options: .animated)
            guard moved,
                  let recaptured = await navigator.firstVisibleElementLocator(),
                  Self.matchesExactBlock(expected: locator, actual: recaptured)
            else {
                locatorExchangeResult = String(localized: "locator.restoreFailed")
                return
            }
            locatorExchangeResult = String(localized: "locator.restored")
        } catch {
            locatorExchangeResult = error.localizedDescription
        }
    }

    /// A successful `go` is only an attempted navigation. The proof is the
    /// first-visible Locator recaptured afterwards matching the same block.
    private static func matchesExactBlock(expected: Locator, actual: Locator) -> Bool {
        guard normalizedHref(expected.href.string) == normalizedHref(actual.href.string) else { return false }

        let expectedLocations = expected.jsonObject["locations"]?.object
        let actualLocations = actual.jsonObject["locations"]?.object

        if let selector = expectedLocations?["cssSelector"]?.string,
           !selector.isEmpty,
           selector == actualLocations?["cssSelector"]?.string {
            return true
        }

        let expectedFragments = Set(expected.locations.fragments)
        let actualFragments = Set(actual.locations.fragments)
        if !expectedFragments.isEmpty, !expectedFragments.isDisjoint(with: actualFragments) {
            return true
        }

        guard let expectedHighlight = expected.text.highlight,
              let actualHighlight = actual.text.highlight,
              normalizedText(expectedHighlight) == normalizedText(actualHighlight)
        else { return false }
        let beforeMatches = expected.text.before == nil || actual.text.before == nil
            || normalizedText(expected.text.before!) == normalizedText(actual.text.before!)
        let afterMatches = expected.text.after == nil || actual.text.after == nil
            || normalizedText(expected.text.after!) == normalizedText(actual.text.after!)
        return beforeMatches && afterMatches
    }

    private static func normalizedHref(_ value: String) -> String {
        value.replacingOccurrences(of: "^\\./", with: "", options: .regularExpression)
            .split(separator: "#", maxSplits: 1).first.map(String.init) ?? value
    }

    private static func normalizedText(_ value: String) -> String {
        value.precomposedStringWithCanonicalMapping
            .components(separatedBy: .whitespacesAndNewlines)
            .filter { !$0.isEmpty }
            .joined(separator: " ")
    }

    func runPageTurnStress(count: Int = 500) async {
        guard let navigator, await waitUntilReady() else {
            lastStressResult = PageTurnStressResult(
                requestedTurns: count,
                completedTurns: 0,
                p50Milliseconds: 0,
                p95Milliseconds: 0,
                maximumMilliseconds: 0,
                residentMemoryBeforeBytes: 0,
                peakResidentMemoryBytes: 0,
                residentMemoryAfterBytes: 0,
                grade: .fail,
                failure: String(localized: "stress.navigatorNotReady")
            )
            return
        }

        pageTurnProgress = 0
        var movingForward = true
        var latencies: [Double] = []
        let clock = ContinuousClock()
        let memoryBefore = Self.residentMemoryBytes()
        var peakMemory = memoryBefore
        for index in 0 ..< count {
            let started = clock.now
            var moved = movingForward
                ? await navigator.goForward(options: .none)
                : await navigator.goBackward(options: .none)
            if !moved {
                movingForward.toggle()
                moved = movingForward
                    ? await navigator.goForward(options: .none)
                    : await navigator.goBackward(options: .none)
            }
            guard moved else { break }
            latencies.append(started.duration(to: clock.now).milliseconds)
            pageTurnProgress = index + 1
            if index.isMultiple(of: 10) {
                peakMemory = max(peakMemory, Self.residentMemoryBytes())
            }
        }

        let sorted = latencies.sorted()
        let p50 = percentile(0.50, in: sorted)
        let p95 = percentile(0.95, in: sorted)
        let grade: TechnicalGrade
        if latencies.count < count {
            grade = .fail
        } else if p95 <= 350, (sorted.last ?? 0) <= 1_000, resourceFailures.isEmpty {
            grade = .pass
        } else {
            grade = .degraded
        }
        lastStressResult = PageTurnStressResult(
            requestedTurns: count,
            completedTurns: latencies.count,
            p50Milliseconds: p50,
            p95Milliseconds: p95,
            maximumMilliseconds: sorted.last ?? 0,
            residentMemoryBeforeBytes: memoryBefore,
            peakResidentMemoryBytes: peakMemory,
            residentMemoryAfterBytes: Self.residentMemoryBytes(),
            grade: grade,
            failure: resourceFailures.first
        )
    }

    func evaluateFeatureProbe(fixtureID: String) async {
        guard let navigator else {
            recordFeatureProbeFailure(fixtureID: fixtureID, message: "Navigator is unavailable")
            return
        }
        let assertion = Self.featureAssertion(for: fixtureID)
        let script = #"""
        (() => {
          try {
          const images = [...document.images];
          const body = document.body;
          if (!body) {
            return JSON.stringify({ fixtureID: "__FIXTURE_ID__", pass: false, diagnostics: { scriptError: "document.body is unavailable" } });
          }
          const bodyStyle = getComputedStyle(body);
          const htmlStyle = getComputedStyle(document.documentElement);
          const text = body.innerText ?? "";
          const cssProof = document.getElementById("css-proof");
          const fontProof = document.getElementById("font-proof");
          const links = [...document.querySelectorAll("a[href]")].map(link => link.getAttribute("href") ?? "");
          const diagnostics = {
            title: document.title ?? "",
            textLength: text.length,
            writingMode: bodyStyle.writingMode,
            htmlWritingMode: htmlStyle.writingMode,
            direction: bodyStyle.direction,
            imageCount: images.length,
            brokenImages: images.filter(image => !image.complete || image.naturalWidth === 0).length,
            fontsStatus: document.fonts?.status ?? "unsupported",
            embeddedFontReady: document.fonts?.check('16px "Shuku Test Font"') ?? false,
            fontFamily: fontProof ? getComputedStyle(fontProof).fontFamily : "",
            cssMarginLeft: cssProof ? getComputedStyle(cssProof).marginLeft : "",
            cssTextIndent: cssProof ? getComputedStyle(cssProof).textIndent : "",
            cssColor: cssProof ? getComputedStyle(cssProof).color : "",
            rubyCount: document.querySelectorAll("ruby").length,
            footnoteLinkCount: links.filter(href => href.includes("note-")).length,
            hasLocalFootnoteTarget: document.getElementById("note-local") !== null,
            href: location.pathname + location.hash
          };
          const pass = __FIXTURE_ASSERTION__;
          return JSON.stringify({ fixtureID: "__FIXTURE_ID__", pass, diagnostics });
          } catch (error) {
            return JSON.stringify({
              fixtureID: "__FIXTURE_ID__",
              pass: false,
              diagnostics: {
                scriptError: String(error),
                stack: String(error?.stack ?? "")
              }
            });
          }
        })();
        """#
            .replacingOccurrences(of: "__FIXTURE_ASSERTION__", with: assertion)
            .replacingOccurrences(of: "__FIXTURE_ID__", with: fixtureID)
        switch await navigator.evaluateJavaScript(script) {
        case .success(let value):
            guard let json = value as? String,
                  let data = json.data(using: .utf8),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let passed = object["pass"] as? Bool,
                  let diagnostics = object["diagnostics"] as? [String: Any],
                  JSONSerialization.isValidJSONObject(diagnostics),
                  let diagnosticsData = try? JSONSerialization.data(withJSONObject: diagnostics, options: [.sortedKeys]),
                  let diagnosticsText = String(data: diagnosticsData, encoding: .utf8)
            else {
                recordFeatureProbeFailure(fixtureID: fixtureID, message: "JavaScript returned an invalid result")
                return
            }
            let result = FeatureProbeResult(
                fixtureID: fixtureID,
                grade: passed ? .pass : .fail,
                diagnostics: diagnosticsText,
                failure: passed ? nil : "Fixture-specific DOM assertion failed"
            )
            lastFeatureProbe = result
            javascriptResult = "\(result.grade.rawValue): \(diagnosticsText)"
        case .failure(let error):
            let cocoaError = error as NSError
            let details = cocoaError.userInfo
                .map { "\($0.key)=\($0.value)" }
                .sorted()
                .joined(separator: ", ")
            recordFeatureProbeFailure(
                fixtureID: fixtureID,
                message: "\(cocoaError.domain)[\(cocoaError.code)] \(cocoaError.localizedDescription) \(details)"
            )
        }
    }

    private static func featureAssertion(for fixtureID: String) -> String {
        switch fixtureID {
        case "basic-mobi6":
            "text.includes('原生解析从这里开始') && text.includes('章节跳转、返回和连续翻页都必须稳定')"
        case "basic-kf8":
            "text.includes('AZW3_SMOKE_MARKER_ONE')"
        case "css":
            "text.includes('CSS_COMPUTED_STYLE_MARKER') && diagnostics.cssMarginLeft === '37px' && diagnostics.cssTextIndent !== '0px' && diagnostics.cssColor === 'rgb(32, 78, 121)'"
        case "font":
            "text.includes('FONT_EMBED_MARKER') && diagnostics.embeddedFontReady && diagnostics.fontFamily.includes('Shuku Test Font')"
        case "images":
            "text.includes('IMAGE_RESOURCE_MARKER') && diagnostics.imageCount >= 2 && diagnostics.brokenImages === 0"
        case "footnotes":
            "diagnostics.footnoteLinkCount >= 4 && diagnostics.hasLocalFootnoteTarget"
        case "complex-toc":
            "text.includes('TOC_LEVEL_3_A')"
        case "zh-hans":
            "text.includes('ZH_TEXT_MARKER') && text.includes('𠮷') && text.includes('𪚥')"
        case "ja-vertical":
            "text.includes('JA_VERTICAL_MARKER') && diagnostics.rubyCount >= 1 && (diagnostics.writingMode === 'vertical-rl' || diagnostics.htmlWritingMode === 'vertical-rl')"
        case "long-chapter":
            "text.length >= 1000000 && text.includes('LONG_CHAPTER_START') && text.includes('LONG_CHAPTER_END')"
        default:
            "false"
        }
    }

    private func recordFeatureProbeFailure(fixtureID: String, message: String) {
        let result = FeatureProbeResult(
            fixtureID: fixtureID,
            grade: .fail,
            diagnostics: "{}",
            failure: message
        )
        lastFeatureProbe = result
        javascriptResult = "\(result.grade.rawValue): \(message)"
    }

    private func percentile(_ percentile: Double, in values: [Double]) -> Double {
        guard !values.isEmpty else { return 0 }
        let index = min(values.count - 1, Int((Double(values.count - 1) * percentile).rounded()))
        return values[index]
    }

    private static func residentMemoryBytes() -> UInt64 {
        var information = task_vm_info_data_t()
        var count = mach_msg_type_number_t(MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<natural_t>.size)
        let result = withUnsafeMutablePointer(to: &information) { pointer in
            pointer.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count)
            }
        }
        return result == KERN_SUCCESS ? information.phys_footprint : 0
    }
}

struct PageTurnStressResult: Codable, Equatable, Sendable {
    let requestedTurns: Int
    let completedTurns: Int
    let p50Milliseconds: Double
    let p95Milliseconds: Double
    let maximumMilliseconds: Double
    let residentMemoryBeforeBytes: UInt64
    let peakResidentMemoryBytes: UInt64
    let residentMemoryAfterBytes: UInt64
    let grade: TechnicalGrade
    let failure: String?
}

struct FeatureProbeResult: Codable, Equatable, Sendable {
    let fixtureID: String
    let grade: TechnicalGrade
    let diagnostics: String
    let failure: String?
}

private extension Duration {
    var milliseconds: Double {
        let components = self.components
        return Double(components.seconds) * 1_000 + Double(components.attoseconds) / 1e15
    }
}
