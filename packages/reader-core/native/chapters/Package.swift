// swift-tools-version: 5.10

import PackageDescription

let package = Package(
    name: "ErmaoChapterCore",
    platforms: [.iOS(.v16)],
    products: [
        .library(name: "ErmaoChapterCore", targets: ["ErmaoChapterCore"]),
    ],
    targets: [
        .target(
            name: "ErmaoChapterCore",
            path: ".",
            sources: ["chapters.c"],
            publicHeadersPath: "include"
        ),
    ],
    cLanguageStandard: .c99
)
