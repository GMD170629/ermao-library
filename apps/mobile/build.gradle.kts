import groovy.json.JsonSlurper
import org.gradle.api.file.DirectoryProperty
import org.gradle.api.file.RegularFileProperty
import org.gradle.api.tasks.InputFile
import org.gradle.api.tasks.InputDirectory
import org.gradle.api.tasks.OutputDirectory
import org.gradle.api.tasks.TaskAction

plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.android.kotlin.multiplatform.library) apply false
    alias(libs.plugins.kotlin.multiplatform) apply false
    alias(libs.plugins.kotlin.serialization) apply false
    alias(libs.plugins.kotlin.compose) apply false
}

abstract class GenerateDesignTokens : DefaultTask() {
    @get:InputFile
    abstract val tokenFile: RegularFileProperty

    @get:OutputDirectory
    abstract val outputDirectory: DirectoryProperty

    @TaskAction
    fun generate() {
        @Suppress("UNCHECKED_CAST")
        val root = JsonSlurper().parse(tokenFile.get().asFile) as Map<String, Any?>
        val colors = root.requiredMap("colors")
        val spacing = root.requiredMap("spacing")
        val radii = root.requiredMap("radii")
        val typography = root.requiredMap("typography")
        val cover = root.requiredMap("cover")
        val progress = root.requiredMap("progress")
        validateContract(root, colors, spacing, radii, typography, cover, progress)

        val outputRoot = outputDirectory.get().asFile
        val kotlinOutput = outputRoot.resolve("kotlin/com/ermao/library/design/GeneratedDesignTokens.kt")
        val swiftOutput = outputRoot.resolve("swift/GeneratedDesignTokens.swift")
        val androidLightOutput = outputRoot.resolve("android/values/generated_design_tokens.xml")
        val androidDarkOutput = outputRoot.resolve("android/values-night/generated_design_tokens.xml")
        kotlinOutput.parentFile.mkdirs()
        swiftOutput.parentFile.mkdirs()
        androidLightOutput.parentFile.mkdirs()
        androidDarkOutput.parentFile.mkdirs()

        kotlinOutput.writeIfChanged(renderKotlinTokens(colors, spacing, radii, typography, cover, progress))
        swiftOutput.writeIfChanged(renderSwiftTokens(colors, spacing, radii, typography, cover, progress))
        androidLightOutput.writeIfChanged(renderAndroidColors(colors.requiredMap("appLight")))
        androidDarkOutput.writeIfChanged(renderAndroidColors(colors.requiredMap("appDark")))
    }

    private fun Map<String, Any?>.requiredMap(key: String): Map<String, Any?> =
        (this[key] as? Map<*, *>)
            ?.entries
            ?.associate { (entryKey, value) -> entryKey.toString() to value }
            ?: error("Missing token object: $key")

    private fun File.writeIfChanged(content: String) {
        if (!isFile || readText() != content) writeText(content)
    }

    private fun renderKotlinTokens(
        colors: Map<String, Any?>,
        spacing: Map<String, Any?>,
        radii: Map<String, Any?>,
        typography: Map<String, Any?>,
        cover: Map<String, Any?>,
        progress: Map<String, Any?>,
    ): String = buildString {
        appendLine("// Generated from design/tokens.json. Do not edit.")
        appendLine("package com.ermao.library.design")
        appendLine()
        appendLine("internal object GeneratedDesignTokens {")
        colors.forEach { (appearance, rawPalette) ->
            val palette = (rawPalette as Map<*, *>).entries.associate { it.key.toString() to it.value }
            appendLine("    object ${appearance.kotlinIdentifier()} {")
            palette.forEach { (name, value) ->
                appendLine("        const val ${name.kotlinProperty()} = \"$value\"")
            }
            appendLine("    }")
        }
        appendLine("    object Spacing {")
        spacing.forEach { (name, value) ->
            appendLine("        const val ${name.kotlinProperty()} = ${numberLiteral(value)}")
        }
        appendLine("    }")
        appendLine("    object Radii {")
        radii.forEach { (name, value) ->
            appendLine("        const val ${name.kotlinProperty()} = ${numberLiteral(value)}")
        }
        appendLine("    }")
        typography.forEach { (role, rawStyle) ->
            val style = (rawStyle as Map<*, *>).entries.associate { it.key.toString() to it.value }
            appendLine("    object ${role.kotlinIdentifier()} {")
            style.forEach { (name, value) ->
                val literal = if (value is Number) numberLiteral(value) else "\"$value\""
                appendLine("        const val ${name.kotlinProperty()} = $literal")
            }
            appendLine("    }")
        }
        appendKotlinObject("Cover", cover)
        appendKotlinObject("Progress", progress)
        appendLine("}")
    }

    private fun renderSwiftTokens(
        colors: Map<String, Any?>,
        spacing: Map<String, Any?>,
        radii: Map<String, Any?>,
        typography: Map<String, Any?>,
        cover: Map<String, Any?>,
        progress: Map<String, Any?>,
    ): String = buildString {
        appendLine("// Generated from design/tokens.json. Do not edit.")
        appendLine("import Foundation")
        appendLine()
        appendLine("enum GeneratedDesignTokens {")
        colors.forEach { (appearance, rawPalette) ->
            val palette = (rawPalette as Map<*, *>).entries.associate { it.key.toString() to it.value }
            appendLine("    enum ${appearance.swiftIdentifier()} {")
            palette.forEach { (name, value) ->
                appendLine("        static let ${name.swiftProperty()} = \"$value\"")
            }
            appendLine("    }")
        }
        appendLine("    enum Spacing {")
        spacing.forEach { (name, value) ->
            appendLine("        static let ${name.swiftProperty()}: Double = ${numberLiteral(value)}")
        }
        appendLine("    }")
        appendLine("    enum Radii {")
        radii.forEach { (name, value) ->
            appendLine("        static let ${name.swiftProperty()}: Double = ${numberLiteral(value)}")
        }
        appendLine("    }")
        typography.forEach { (role, rawStyle) ->
            val style = (rawStyle as Map<*, *>).entries.associate { it.key.toString() to it.value }
            appendLine("    enum ${role.swiftIdentifier()} {")
            style.forEach { (name, value) ->
                val type = if (value is Number) ": Double" else ""
                val literal = if (value is Number) numberLiteral(value) else "\"$value\""
                appendLine("        static let ${name.swiftProperty()}$type = $literal")
            }
            appendLine("    }")
        }
        appendSwiftEnum("Cover", cover)
        appendSwiftEnum("Progress", progress)
        appendLine("}")
    }

    private fun StringBuilder.appendKotlinObject(name: String, tokens: Map<String, Any?>) {
        appendLine("    object $name {")
        tokens.forEach { (tokenName, value) ->
            val literal = if (value is Number) numberLiteral(value) else "\"$value\""
            appendLine("        const val ${tokenName.kotlinProperty()} = $literal")
        }
        appendLine("    }")
    }

    private fun StringBuilder.appendSwiftEnum(name: String, tokens: Map<String, Any?>) {
        appendLine("    enum $name {")
        tokens.forEach { (tokenName, value) ->
            val type = if (value is Number) ": Double" else ""
            val literal = if (value is Number) numberLiteral(value) else "\"$value\""
            appendLine("        static let ${tokenName.swiftProperty()}$type = $literal")
        }
        appendLine("    }")
    }

    private fun renderAndroidColors(palette: Map<String, Any?>): String = """
        <?xml version="1.0" encoding="utf-8"?>
        <!-- Generated from design/tokens.json. Do not edit. -->
        <resources>
            <color name="launcher_background">${palette.getValue("canvas")}</color>
            <color name="window_background">${palette.getValue("canvas")}</color>
        </resources>
    """.trimIndent() + "\n"

    private fun validateContract(
        root: Map<String, Any?>,
        colors: Map<String, Any?>,
        spacing: Map<String, Any?>,
        radii: Map<String, Any?>,
        typography: Map<String, Any?>,
        cover: Map<String, Any?>,
        progress: Map<String, Any?>,
    ) {
        check((root["schemaVersion"] as? Number)?.toInt() == 1) { "Unsupported token schema" }
        check(colors.keys == setOf("appLight", "appDark", "readerPaper", "readerNight")) {
            "Color appearances do not match Phase 4"
        }
        val expectedColors = mapOf(
            "appLight" to mapOf(
                "canvas" to "#FBFAF8", "surface" to "#FFFDF9", "surfaceRaised" to "#FFFFFF",
                "textPrimary" to "#17191D", "textSecondary" to "#6F6A65", "textTertiary" to "#8A837D",
                "divider" to "#E6E1DB", "brandAccent" to "#FF4F2A", "actionAccent" to "#C83B23",
                "accentSoft" to "#FFF0EA", "onAction" to "#FFFFFF",
            ),
            "appDark" to mapOf(
                "canvas" to "#151311", "surface" to "#1D1A18", "surfaceRaised" to "#26221E",
                "textPrimary" to "#F3ECE4", "textSecondary" to "#B7ADA2", "textTertiary" to "#90867C",
                "divider" to "#37312C", "brandAccent" to "#FF6B48", "actionAccent" to "#FF7A58",
                "accentSoft" to "#3A211A", "onAction" to "#26110B",
            ),
            "readerPaper" to mapOf(
                "canvas" to "#FDF6EA", "surface" to "#FFF9F1", "surfaceRaised" to "#FFFDF9",
                "textPrimary" to "#2B2118", "textSecondary" to "#6F5E50", "textTertiary" to "#8A796A",
                "divider" to "#E6D9C8", "brandAccent" to "#FF4F2A", "actionAccent" to "#B44125",
                "accentSoft" to "#F5DDCC", "onAction" to "#FFFFFF",
            ),
            "readerNight" to mapOf(
                "canvas" to "#151311", "surface" to "#211E1B", "surfaceRaised" to "#29241F",
                "textPrimary" to "#EFE7DD", "textSecondary" to "#B9AEA2", "textTertiary" to "#91867B",
                "divider" to "#3B352F", "brandAccent" to "#FF6B48", "actionAccent" to "#FF7A58",
                "accentSoft" to "#3A211A", "onAction" to "#26110B",
            ),
        )
        val normalizedColors = colors.mapValues { (_, raw) ->
            (raw as Map<*, *>).entries.associate { it.key.toString() to it.value.toString() }
        }
        check(normalizedColors == expectedColors) { "Color values do not match Phase 4" }
        val paletteKeys = setOf(
            "canvas", "surface", "surfaceRaised", "textPrimary", "textSecondary", "textTertiary",
            "divider", "brandAccent", "actionAccent", "accentSoft", "onAction",
        )
        colors.values.forEach { raw ->
            val palette = (raw as? Map<*, *>) ?: error("Invalid color palette")
            check(palette.keys.map(Any?::toString).toSet() == paletteKeys) { "Incomplete color palette" }
            palette.values.forEach { check(it is String && COLOR_PATTERN.matches(it)) { "Invalid color: $it" } }
        }
        check(spacing == mapOf(
            "space0" to 0, "space0_5" to 4, "space1" to 8, "space1_5" to 12,
            "space2" to 16, "space3" to 24, "space4" to 32, "space5" to 40,
            "space6" to 48, "space8" to 64,
        )) { "Spacing tokens do not match Phase 4" }
        check(radii == mapOf("control" to 12, "task" to 16, "coverCompact" to 8, "coverHero" to 12)) {
            "Radius tokens do not match Phase 4"
        }
        check(typography.keys == setOf(
            "display", "title", "sectionTitle", "headline", "body", "callout", "label", "caption",
            "button", "readerChapter", "readerBody", "readerAuxiliary",
        )) { "Typography roles do not match Phase 4" }
        typography.values.forEach { raw ->
            check((raw as? Map<*, *>)?.keys?.map(Any?::toString)?.toSet() ==
                setOf("size", "lineHeight", "weight", "familyRole")) { "Invalid typography role" }
        }
        val expectedTypography = mapOf(
            "display" to listOf(32, 40, 700, "systemSans"),
            "title" to listOf(24, 32, 700, "systemSans"),
            "sectionTitle" to listOf(20, 28, 600, "systemSans"),
            "headline" to listOf(17, 24, 600, "systemSans"),
            "body" to listOf(16, 24, 400, "systemSans"),
            "callout" to listOf(15, 22, 400, "systemSans"),
            "label" to listOf(14, 20, 500, "systemSans"),
            "caption" to listOf(12, 16, 400, "systemSans"),
            "button" to listOf(16, 22, 600, "systemSans"),
            "readerChapter" to listOf(20, 30, 600, "readerSerif"),
            "readerBody" to listOf(18, 32, 400, "readerSerif"),
            "readerAuxiliary" to listOf(13, 18, 400, "systemSans"),
        )
        val normalizedTypography = typography.mapValues { (_, raw) ->
            val style = raw as Map<*, *>
            listOf(style["size"], style["lineHeight"], style["weight"], style["familyRole"])
        }
        check(normalizedTypography == expectedTypography) { "Typography values do not match Phase 4" }
        check(cover == mapOf(
            "aspectWidth" to 2, "aspectHeight" to 3, "contentMode" to "contain",
            "compactRadiusToken" to "coverCompact", "heroRadiusToken" to "coverHero",
        )) { "Cover contract does not match Phase 4" }
        check(progress == mapOf(
            "coverHeight" to 2, "coverHorizontalInset" to 8, "readingHeight" to 3,
            "downloadHeight" to 4, "scrubberTrackMinimumHeight" to 2,
            "scrubberTrackMaximumHeight" to 3, "iosMinimumTouchTarget" to 44,
            "androidMinimumTouchTarget" to 48,
        )) { "Progress contract does not match Phase 4" }
    }

    private fun String.kotlinIdentifier(): String =
        split('-', '_', '.').joinToString("") { it.replaceFirstChar(Char::uppercaseChar) }

    private fun String.kotlinProperty(): String =
        replace('-', '_').replace('.', '_').replaceFirstChar(Char::uppercaseChar)

    private fun String.swiftIdentifier(): String = kotlinIdentifier()

    private fun String.swiftProperty(): String =
        replace('-', '_').replace('.', '_')

    private fun numberLiteral(value: Any?): String = when (value) {
        is Int, is Long -> "$value.0"
        is Number -> value.toString()
        else -> error("Expected numeric token, got $value")
    }

    private companion object {
        val COLOR_PATTERN = Regex("^#[0-9A-F]{6}$")
    }
}

abstract class VerifyGeneratedDesignTokens : DefaultTask() {
    @get:InputDirectory
    abstract val generatedDirectory: DirectoryProperty

    @TaskAction
    fun verify() {
        val output = generatedDirectory.get().asFile
        val required = listOf(
            "kotlin/com/ermao/library/design/GeneratedDesignTokens.kt",
            "swift/GeneratedDesignTokens.swift",
            "android/values/generated_design_tokens.xml",
            "android/values-night/generated_design_tokens.xml",
        )
        required.forEach { relative ->
            val generated = output.resolve(relative)
            check(generated.isFile && generated.readText().endsWith("\n")) {
                "Invalid generated token file: $relative"
            }
        }
    }
}

val generateDesignTokens by tasks.registering(GenerateDesignTokens::class) {
    group = "design"
    description = "Generates platform-neutral Kotlin and Swift token constants."
    tokenFile.set(layout.projectDirectory.file("design/tokens.json"))
    outputDirectory.set(layout.buildDirectory.dir("generated/design-tokens"))
}

tasks.register<VerifyGeneratedDesignTokens>("verifyDesignTokens") {
    group = "verification"
    description = "Validates the exact Phase 4 token contract and deterministic generated outputs."
    dependsOn(generateDesignTokens)
    generatedDirectory.set(layout.buildDirectory.dir("generated/design-tokens"))
}
