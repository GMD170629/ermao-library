// swift-tools-version: 5.10

import PackageDescription

let package = Package(
    name: "LibMobi",
    platforms: [.iOS(.v16)],
    products: [
        .library(name: "LibMobi", targets: ["CLibMobi"]),
    ],
    targets: [
        .target(
            name: "CLibMobi",
            path: "Sources/CLibMobi",
            exclude: [
                "src/encryption.c",
                "src/miniz.c",
                "src/randombytes.c",
                "src/sha1.c",
            ],
            publicHeadersPath: "include",
            cSettings: [
                .headerSearchPath("src"),
                .define("PACKAGE_VERSION", to: "\"0.12\""),
                .define("USE_XMLWRITER"),
                .define("USE_ZLIB"),
                .define("HAVE_STRDUP"),
                .define("HAVE_UNISTD_H"),
                .define("MOBI_INLINE", to: "inline"),
            ],
            linkerSettings: [
                .linkedLibrary("z"),
            ]
        ),
    ],
    cLanguageStandard: .c99
)
