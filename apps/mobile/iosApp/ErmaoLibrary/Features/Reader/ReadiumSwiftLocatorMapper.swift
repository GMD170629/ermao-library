import Foundation
@preconcurrency import ErmaoShared
import ReadiumShared

struct ReadiumSwiftLocatorMapper {
    func sharedLocation(
        from locator: Locator
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
        let canonicalLocator = try bounded.jsonString()
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
                version: "readium-swift:3.9.0",
                payloadJson: canonicalLocator
            )
        )
        guard ErmaoShared.ReadiumLocatorEnvelope.companion.from(location: location) != nil else {
            throw IosReaderFailure(code: .persistenceFailed)
        }
        return location
    }

    func exactEnvelope(
        from locator: Locator
    ) throws -> ErmaoShared.ReadiumLocatorEnvelope {
        let location = try sharedLocation(from: locator)
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
        let decoded = try Locator(jsonString: envelope.payload.canonicalJson)
        guard publication.readingOrder.contains(where: {
            $0.url().normalized.isEquivalentTo(decoded.href.normalized)
        })
        else { return nil }
        return decoded
    }
}

private extension String {
    var nilIfBlank: String? {
        trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : self
    }
}
