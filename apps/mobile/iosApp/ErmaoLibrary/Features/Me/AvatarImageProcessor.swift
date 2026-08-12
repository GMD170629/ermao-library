import Foundation
import ImageIO
import UniformTypeIdentifiers

enum AvatarImageProcessingError: Error, Equatable, Sendable {
    case inputTooLarge
    case invalidImage
    case unsafeDimensions
    case unableToEncode
    case outputTooLarge
}

struct AvatarImageProcessor: Sendable {
    static let defaultMaximumBytes = 5 * 1_024 * 1_024

    let maximumBytes: Int
    let maximumInputBytes: Int
    let maximumPixelDimension: Int
    let maximumPixelCount: Int

    init(
        maximumBytes: Int = AvatarImageProcessor.defaultMaximumBytes,
        maximumInputBytes: Int = 64 * 1_024 * 1_024,
        maximumPixelDimension: Int = 4_096,
        maximumPixelCount: Int = 40_000_000
    ) {
        self.maximumBytes = maximumBytes
        self.maximumInputBytes = maximumInputBytes
        self.maximumPixelDimension = maximumPixelDimension
        self.maximumPixelCount = maximumPixelCount
    }

    func process(
        data: Data,
        declaredContentTypeIdentifier: String?
    ) throws -> SettingsAvatarUpload {
        guard !data.isEmpty else { throw AvatarImageProcessingError.invalidImage }
        guard data.count <= maximumInputBytes else { throw AvatarImageProcessingError.inputTooLarge }
        guard
            let source = CGImageSourceCreateWithData(data as CFData, imageSourceOptions),
            CGImageSourceGetCount(source) > 0,
            let actualTypeIdentifier = CGImageSourceGetType(source) as String?
        else {
            throw AvatarImageProcessingError.invalidImage
        }

        _ = declaredContentTypeIdentifier // The byte signature, not picker metadata, is authoritative.
        try validateDimensions(of: source)

        let actualType = UTType(actualTypeIdentifier)
        return try transcodeToMetadataFreeImage(
            source: source,
            preservesPNG: actualType?.conforms(to: .png) == true
        )
    }

    private var imageSourceOptions: CFDictionary {
        [kCGImageSourceShouldCache: false] as CFDictionary
    }

    private func validateDimensions(of source: CGImageSource) throws {
        guard
            let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, imageSourceOptions) as? [CFString: Any],
            let width = integerValue(properties[kCGImagePropertyPixelWidth]),
            let height = integerValue(properties[kCGImagePropertyPixelHeight]),
            width > 0,
            height > 0
        else {
            throw AvatarImageProcessingError.invalidImage
        }

        let (pixelCount, overflow) = width.multipliedReportingOverflow(by: height)
        guard
            !overflow,
            pixelCount <= maximumPixelCount,
            width <= 32_768,
            height <= 32_768
        else {
            throw AvatarImageProcessingError.unsafeDimensions
        }
    }

    private func transcodeToMetadataFreeImage(
        source: CGImageSource,
        preservesPNG: Bool
    ) throws -> SettingsAvatarUpload {
        var targetDimension = maximumPixelDimension
        while targetDimension >= 256 {
            guard
                let thumbnail = thumbnail(from: source, maximumDimension: targetDimension),
                let image = normalizedSRGBImage(thumbnail)
            else {
                throw AvatarImageProcessingError.invalidImage
            }
            if preservesPNG, let encoded = pngData(for: image), encoded.count <= maximumBytes {
                return SettingsAvatarUpload(data: encoded, mimeType: .png)
            }
            if let encoded = bestJPEGData(for: image) {
                return SettingsAvatarUpload(data: encoded, mimeType: .jpeg)
            }
            targetDimension = Int(Double(targetDimension) * 0.75)
        }
        throw AvatarImageProcessingError.outputTooLarge
    }

    private func thumbnail(from source: CGImageSource, maximumDimension: Int) -> CGImage? {
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: maximumDimension,
            kCGImageSourceShouldCacheImmediately: true,
        ]
        return CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary)
    }

    private func normalizedSRGBImage(_ image: CGImage) -> CGImage? {
        guard
            let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
            let context = CGContext(
                data: nil,
                width: image.width,
                height: image.height,
                bitsPerComponent: 8,
                bytesPerRow: 0,
                space: colorSpace,
                bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
            )
        else { return nil }
        context.setFillColor(CGColor(gray: 1, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: image.width, height: image.height))
        context.interpolationQuality = .high
        context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
        return context.makeImage()
    }

    private func bestJPEGData(for image: CGImage) -> Data? {
        var lowerQuality = 0.25
        var upperQuality = 0.92
        var best: Data?

        for _ in 0..<8 {
            let quality = (lowerQuality + upperQuality) / 2
            guard let candidate = jpegData(for: image, quality: quality) else { return nil }
            if candidate.count <= maximumBytes {
                best = candidate
                lowerQuality = quality
            } else {
                upperQuality = quality
            }
        }
        return best
    }

    private func jpegData(for image: CGImage, quality: Double) -> Data? {
        let output = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(
            output,
            UTType.jpeg.identifier as CFString,
            1,
            nil
        ) else { return nil }
        let properties = [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary
        CGImageDestinationAddImage(destination, image, properties)
        guard CGImageDestinationFinalize(destination) else { return nil }
        return output as Data
    }

    private func pngData(for image: CGImage) -> Data? {
        let output = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(
            output,
            UTType.png.identifier as CFString,
            1,
            nil
        ) else { return nil }
        CGImageDestinationAddImage(destination, image, nil)
        guard CGImageDestinationFinalize(destination) else { return nil }
        return output as Data
    }

    private func integerValue(_ value: Any?) -> Int? {
        if let value = value as? NSNumber { return value.intValue }
        if let value = value as? Int { return value }
        return nil
    }
}
