import Foundation
@preconcurrency import ErmaoShared
import ReadiumShared

struct ReadiumSwiftLocatorMapper {
    func sharedLocation(
        from locator: Locator,
        fingerprint: IosContentFingerprint
    ) throws -> ErmaoShared.ReflowReaderLocation {
        let progression = locator.locations.progression
        guard progression.map({ $0.isFinite && (0 ... 1).contains($0) }) ?? true else {
            throw IosReaderFailure(code: .engineError)
        }
        let bounded = locator.copy(text: { text in
            text.highlight = text.highlight.map { String($0.unicodeScalars.prefix(512)) }
            text.before = text.before.map { String($0.unicodeScalars.prefix(256)) }
            text.after = text.after.map { String($0.unicodeScalars.prefix(256)) }
        })
        guard let locatorJSON = bounded.jsonString else { throw IosReaderFailure(code: .engineError) }
        let canonicalLocator = try canonicalizeJSONObject(locatorJSON)
        let quote = bounded.text.highlight.flatMap { exact -> ErmaoShared.TextQuote? in
            guard !exact.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            return ErmaoShared.TextQuote(
                exact: exact,
                prefix: bounded.text.before?.nilIfBlank,
                suffix: bounded.text.after?.nilIfBlank
            )
        }
        let location = ErmaoShared.ReflowReaderLocation(
            resourceKey: bounded.href.string,
            progression: progression.map(KotlinDouble.init(double:)),
            totalProgression: bounded.locations.totalProgression.map(KotlinDouble.init(double:)),
            position: bounded.locations.position.map { KotlinInt(int: Int32($0)) },
            textQuote: quote,
            engineLocator: ErmaoShared.PublicKt.createEngineLocator(
                engine: .readium,
                platform: .ios,
                version: "readium-swift:3.8.0",
                payloadJson: canonicalLocator
            ),
            contentFingerprint: fingerprint.shared
        )
        guard ErmaoShared.ReadiumLocatorEnvelope.companion.from(location: location) != nil else {
            throw IosReaderFailure(code: .persistenceFailed)
        }
        return location
    }

    func exactEnvelope(
        from locator: Locator,
        fingerprint: IosContentFingerprint
    ) throws -> ErmaoShared.ReadiumLocatorEnvelope {
        let location = try sharedLocation(from: locator, fingerprint: fingerprint)
        guard let envelope = ErmaoShared.ReadiumLocatorEnvelope.companion.from(location: location) else {
            throw IosReaderFailure(code: .locationRestoreFailed)
        }
        return envelope
    }

    func exactLocator(from location: ErmaoShared.ReflowReaderLocation) throws -> Locator? {
        guard let locator = location.engineLocator,
              locator.engine == .readium,
              ErmaoShared.ReadiumLocatorEnvelope.companion.from(location: location) != nil
        else { return nil }
        return try Locator(jsonString: locator.payload.canonicalJson)
    }

    func exactLocator(
        from envelope: ErmaoShared.ReadiumLocatorEnvelope,
        publication: Publication
    ) throws -> Locator? {
        guard let decoded = try Locator(jsonString: envelope.payload.canonicalJson),
              publication.readingOrder.contains(where: {
                  $0.url().normalized.isEquivalentTo(decoded.href.normalized)
              })
        else { return nil }
        return decoded
    }

    private func canonicalizeJSONObject(_ json: String) throws -> String {
        let object = try JSONSerialization.jsonObject(with: Data(json.utf8))
        guard object is [String: Any] else { throw IosReaderFailure(code: .engineError) }
        let data = try JSONSerialization.data(
            withJSONObject: object,
            options: [.sortedKeys, .withoutEscapingSlashes]
        )
        guard let result = String(data: data, encoding: .utf8) else {
            throw IosReaderFailure(code: .engineError)
        }
        return result
    }
}

private extension String {
    var nilIfBlank: String? {
        trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : self
    }
}
