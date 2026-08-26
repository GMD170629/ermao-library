// swift-tools-version: 5.10

import PackageDescription

let package = Package(
    name: "ErmaoArchiveCore",
    platforms: [.iOS(.v16)],
    products: [
        .library(name: "ErmaoArchiveCore", targets: ["ErmaoArchiveCore"]),
    ],
    targets: [
        .binaryTarget(
            name: "ErmaoArchiveCore",
            path: "Frameworks/ErmaoArchiveCore.xcframework"
        ),
    ]
)
