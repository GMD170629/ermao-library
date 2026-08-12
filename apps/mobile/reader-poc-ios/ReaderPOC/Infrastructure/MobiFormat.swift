import ReadiumShared

extension FormatSpecification {
    nonisolated(unsafe) static let mobi = FormatSpecification(rawValue: "mobi")
}

extension Format {
    static func mobi(fileExtension: FileExtension = "azw3") -> Format {
        Format(
            specifications: .mobi,
            mediaType: MediaType("application/x-mobipocket-ebook"),
            fileExtension: fileExtension
        )
    }
}

struct MobiFormatSniffer: FormatSniffer {
    func sniffHints(_ hints: FormatHints) -> Format? {
        guard hints.hasFileExtension("mobi", "azw", "azw3", "prc")
            || hints.hasMediaType("application/x-mobipocket-ebook", "application/vnd.amazon.ebook")
        else {
            return nil
        }
        let fileExtension = hints.fileExtensions.first(where: { ["mobi", "azw", "azw3", "prc"].contains($0.rawValue) })
            ?? "azw3"
        return .mobi(fileExtension: fileExtension)
    }
}
