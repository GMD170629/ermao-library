import com.ermao.buildlogic.GenerateDesignTokens
import com.ermao.buildlogic.SyncWebDesignTokens
import com.ermao.buildlogic.VerifyGeneratedDesignTokens
import com.ermao.buildlogic.VerifyVisualTokenContract
import org.gradle.api.file.DirectoryProperty
import org.gradle.api.tasks.Internal
import org.gradle.api.tasks.TaskAction

plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.android.kotlin.multiplatform.library) apply false
    alias(libs.plugins.kotlin.multiplatform) apply false
    alias(libs.plugins.kotlin.serialization) apply false
    alias(libs.plugins.kotlin.compose) apply false
}

abstract class VerifyMobileOfflineContract : DefaultTask() {
    @get:Internal
    abstract val repositoryRoot: DirectoryProperty

    @TaskAction
    fun verify() {
        val forbidden = listOf(
            "Offline" + "Entitlement",
            "offline" + "-grace",
            "OfflineFilter" + "Availability",
            "ContentSource" + ".Cache",
            "LibrarySnapshot" + "PayloadStore",
            "library-offline-" + "cached-results",
            "library-stale-" + "refresh",
        )
        val searchableExtensions = setOf(
            "kt", "kts", "swift", "md", "json", "xml", "xcstrings", "pbxproj", "yml", "yaml",
        )
        val root = repositoryRoot.get().asFile
        val violations = root.walkTopDown()
            .onEnter { directory ->
                directory.name !in setOf(".git", ".gradle", "build", "DerivedData", "node_modules")
            }
            .filter(File::isFile)
            .flatMap { file ->
                val relative = file.relativeTo(root).invariantSeparatorsPath
                val pathHits = forbidden.filter(relative::contains).map { token -> "$relative (path: $token)" }
                val contentHits = if (file.extension in searchableExtensions) {
                    file.useLines { lines ->
                        lines.flatMapIndexed { index, line ->
                            forbidden.asSequence()
                                .filter(line::contains)
                                .map { token -> "$relative:${index + 1} ($token)" }
                        }.toList()
                    }
                } else {
                    emptyList()
                }
                (pathHits + contentHits).asSequence()
            }
            .sorted()
            .toList()
        check(violations.isEmpty()) {
            "Removed Mobile session/page-cache contract reappeared:\n${violations.joinToString("\n")}"
        }
    }
}

val generateDesignTokens by tasks.registering(GenerateDesignTokens::class) {
    group = "design"
    description = "Generates deterministic CSS, TypeScript, Kotlin, Swift, and Android visual tokens."
    tokenFile.set(layout.projectDirectory.file("../../packages/design-contracts/visual-tokens.json"))
    schemaFile.set(layout.projectDirectory.file("../../packages/design-contracts/schemas/visual-tokens.schema.json"))
    outputDirectory.set(layout.buildDirectory.dir("generated/design-tokens"))
}

tasks.register<SyncWebDesignTokens>("syncWebDesignTokens") {
    group = "design"
    description = "Updates the tracked Web visual token artifacts from the canonical contract."
    dependsOn(generateDesignTokens)
    generatedDirectory.set(layout.buildDirectory.dir("generated/design-tokens"))
    webOutputDirectory.set(layout.projectDirectory.dir("../web/generated"))
}

tasks.register<VerifyGeneratedDesignTokens>("verifyDesignTokens") {
    group = "verification"
    description = "Validates the cross-platform visual contract and rejects generated Web drift."
    dependsOn(generateDesignTokens, "verifyVisualTokenContract")
    mustRunAfter("syncWebDesignTokens")
    generatedDirectory.set(layout.buildDirectory.dir("generated/design-tokens"))
    webOutputDirectory.set(layout.projectDirectory.dir("../web/generated"))
}

tasks.register<VerifyVisualTokenContract>("verifyVisualTokenContract") {
    group = "verification"
    description = "Exercises schema, contrast, completeness, and deterministic visual token invariants."
    tokenFile.set(layout.projectDirectory.file("../../packages/design-contracts/visual-tokens.json"))
    schemaFile.set(layout.projectDirectory.file("../../packages/design-contracts/schemas/visual-tokens.schema.json"))
}

tasks.register<VerifyMobileOfflineContract>("verifyMobileOfflineContract") {
    group = "verification"
    description = "Rejects removed Mobile entitlement, GET-page cache, stale, and download-filter contracts."
    repositoryRoot.set(layout.projectDirectory.dir("../.."))
}
