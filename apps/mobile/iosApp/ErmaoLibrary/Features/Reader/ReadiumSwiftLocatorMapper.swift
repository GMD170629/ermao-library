import Foundation
@preconcurrency import ErmaoShared
import ReadiumShared

struct ReadiumSwiftLocatorMapper {
    func sharedLocation(
        from locator: Locator,
        fingerprint: IosContentFingerprint
    ) throws -> ErmaoShared.ReflowReaderLocation {
        let progression = locator.locations.progression
        guard progression.map({ $0.isFinite && (0 ... 1).contains($0) }) ?? true,
              let locatorJSON = locator.jsonString
        else {
            throw IosReaderFailure(code: .engineError)
        }
        let canonicalLocator = try canonicalizeJSONObject(locatorJSON)
        let quote = locator.text.highlight.flatMap { exact -> ErmaoShared.TextQuote? in
            guard !exact.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
            return ErmaoShared.TextQuote(
                exact: exact,
                prefix: locator.text.before?.nilIfBlank,
                suffix: locator.text.after?.nilIfBlank
            )
        }
        return ErmaoShared.ReflowReaderLocation(
            resourceKey: locator.href.string,
            progression: progression.map(KotlinDouble.init(double:)),
            totalProgression: locator.locations.totalProgression.map(KotlinDouble.init(double:)),
            position: locator.locations.position.map { KotlinInt(int: Int32($0)) },
            textQuote: quote,
            engineLocator: ErmaoShared.PublicKt.createEngineLocator(
                engine: .readium,
                platform: .ios,
                version: "3.8.0",
                payloadJson: canonicalLocator
            ),
            contentFingerprint: fingerprint.shared
        )
    }

    func exactLocator(from location: ErmaoShared.ReflowReaderLocation) throws -> Locator? {
        guard let locator = location.engineLocator,
              locator.engine == .readium,
              locator.platform == .ios,
              locator.version == "readium-swift:3.8.0" || locator.version == "3.8.0"
        else { return nil }
        return try Locator(jsonString: locator.payload.canonicalJson)
    }

    func publicEngineLocator(
        from anchor: ErmaoShared.ReaderPublicAnchor,
        publication: Publication
    ) throws -> Locator? {
        guard let locator = anchor.engineLocator,
              locator.engine == .readium
        else { return nil }
        guard let decoded = try Locator(jsonString: locator.payload.canonicalJson),
              publication.readingOrder.contains(where: {
                  $0.url().normalized == decoded.href.normalized
              })
        else { return nil }
        return decoded
    }

    func resourceProgressionLocator(
        from location: ErmaoShared.ReflowReaderLocation,
        publication: Publication
    ) async -> Locator? {
        guard let resourceKey = location.resourceKey,
              let link = publication.readingOrder.first(where: {
            $0.url().normalized.string == resourceKey
        }), let base = await publication.locate(link) else { return nil }
        return base.copy(locations: { locations in
            locations.progression = location.progression?.doubleValue
            locations.totalProgression = location.totalProgression?.doubleValue
            locations.position = location.position.map { Int($0.intValue) }
        })
    }

    func quotedTextLocator(
        from location: ErmaoShared.ReflowReaderLocation,
        publication: Publication
    ) async -> Locator? {
        guard let quote = location.textQuote else { return nil }
        var options = SearchOptions()
        options.exact = true
        guard case let .success(iterator) = await publication.search(query: quote.exact, options: options) else {
            return nil
        }
        defer { iterator.close() }
        while case let .success(page?) = await iterator.next() {
            if let match = page.locators.first(where: { locator in
                let sameResource = location.resourceKey.map {
                    locator.href.normalized.string == $0
                } ?? true
                let prefixMatches = quote.prefix.map { locator.text.before?.hasSuffix($0) == true } ?? true
                let suffixMatches = quote.suffix.map { locator.text.after?.hasPrefix($0) == true } ?? true
                return sameResource && prefixMatches && suffixMatches
            }) {
                return match
            }
        }
        return nil
    }

    func resourceProgressionLocator(
        from anchor: ErmaoShared.ReaderPublicAnchor,
        publication: Publication
    ) async -> Locator? {
        guard let resourceKey = anchor.resourceKey,
              let link = publication.readingOrder.first(where: {
                  $0.url().normalized.string == resourceKey
              }),
              let base = await publication.locate(link)
        else { return nil }
        return base.copy(locations: { locations in
            locations.progression = anchor.progression?.doubleValue
        })
    }

    func quotedTextLocator(
        from anchor: ErmaoShared.ReaderPublicAnchor,
        publication: Publication
    ) async -> Locator? {
        guard let quote = anchor.textQuote else { return nil }
        var options = SearchOptions()
        options.exact = true
        guard case let .success(iterator) = await publication.search(query: quote.exact, options: options) else {
            return nil
        }
        defer { iterator.close() }
        while case let .success(page?) = await iterator.next() {
            if let match = page.locators.first(where: { locator in
                let sameResource = anchor.resourceKey.map {
                    locator.href.normalized.string == $0
                } ?? true
                let prefixMatches = quote.prefix.map { locator.text.before?.hasSuffix($0) == true } ?? true
                let suffixMatches = quote.suffix.map { locator.text.after?.hasPrefix($0) == true } ?? true
                return sameResource && prefixMatches && suffixMatches
            }) {
                return match
            }
        }
        return nil
    }

    func positionLocator(
        from anchor: ErmaoShared.ReaderPublicAnchor,
        publication: Publication
    ) async -> Locator? {
        guard let position = anchor.position?.intValue,
              case let .success(positions) = await publication.positions()
        else { return nil }
        return positions.first(where: { $0.locations.position == Int(position) })
    }

    func totalProgressionLocator(
        from location: ErmaoShared.ReflowReaderLocation,
        publication: Publication
    ) async -> Locator? {
        guard let progression = location.totalProgression?.doubleValue else { return nil }
        return await publication.locate(progression: progression)
    }

    func positionLocator(
        from location: ErmaoShared.ReflowReaderLocation,
        publication: Publication
    ) async -> Locator? {
        guard let position = location.position?.intValue,
              case let .success(positions) = await publication.positions()
        else { return nil }
        return positions.first(where: { $0.locations.position == Int(position) })
    }

    private func canonicalizeJSONObject(_ json: String) throws -> String {
        let object = try JSONSerialization.jsonObject(with: Data(json.utf8))
        guard object is [String: Any] else { throw IosReaderFailure(code: .engineError) }
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
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
