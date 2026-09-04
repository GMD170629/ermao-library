import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import org.gradle.api.tasks.testing.Test

plugins {
    alias(libs.plugins.kotlin.multiplatform)
    alias(libs.plugins.android.kotlin.multiplatform.library)
    alias(libs.plugins.kotlin.serialization)
}

kotlin {
    android {
        namespace = "com.ermao.library.shared"
        compileSdk = libs.versions.android.compile.sdk.get().toInt()
        minSdk = libs.versions.android.min.sdk.get().toInt()
        withHostTestBuilder {}
        compilerOptions {
            jvmTarget.set(JvmTarget.JVM_17)
            allWarningsAsErrors.set(true)
        }
    }

    iosArm64()

    targets.withType<org.jetbrains.kotlin.gradle.plugin.mpp.KotlinNativeTarget>().configureEach {
        binaries.framework {
            baseName = "ErmaoShared"
            isStatic = true
        }
    }

    sourceSets {
        commonMain.dependencies {
            implementation(libs.kotlinx.coroutines.core)
            implementation(libs.kotlinx.serialization.json)
            implementation(libs.ktor.client.core)
            implementation(libs.ktor.client.content.negotiation)
            implementation(libs.ktor.serialization.kotlinx.json)
        }
        commonTest.dependencies {
            implementation(kotlin("test"))
            implementation(libs.ktor.client.mock)
        }
        val androidHostTest by getting {
            kotlin.srcDir(
                rootProject.layout.projectDirectory.dir(
                    "test-support/reader-safety-conformance/kotlin",
                ),
            )
        }
        androidMain.dependencies {
            implementation(libs.ktor.client.okhttp)
        }
        iosMain.dependencies {
            implementation(libs.ktor.client.darwin)
        }
    }
}

tasks.withType<Test>().configureEach {
    systemProperty(
        "readerSafetyFixtureRoot",
        rootProject.layout.projectDirectory.dir(
            "../../packages/reader-contracts/fixtures/reader-safety-v1",
        ).asFile.absolutePath,
    )
    systemProperty(
        "readerSafetyReportPath",
        layout.buildDirectory.file("reports/reader-safety-conformance/kmp.json").get().asFile.absolutePath,
    )
    systemProperty(
        "readerComicSemanticsFixturePath",
        rootProject.layout.projectDirectory.dir(
            "../../packages/reader-contracts/fixtures/comic-reader-semantics-v1.json",
        ).asFile.absolutePath,
    )
    systemProperty(
        "readerV5FixtureRoot",
        rootProject.layout.projectDirectory.dir(
            "../../packages/reader-contracts/fixtures/reader-v5",
        ).asFile.absolutePath,
    )
}
