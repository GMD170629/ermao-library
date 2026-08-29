import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "com.ermao.library"
    compileSdk = libs.versions.android.compile.sdk.get().toInt()

    defaultConfig {
        applicationId = "com.ermao.library"
        minSdk = libs.versions.android.min.sdk.get().toInt()
        targetSdk = libs.versions.android.target.sdk.get().toInt()
        versionCode = 1
        versionName = "1.0.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    androidResources {
        localeFilters += setOf("en", "zh-rCN")
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
        isCoreLibraryDesugaringEnabled = true
    }

    sourceSets.named("main") {
        kotlin.directories.add(
            rootProject.layout.buildDirectory.dir("generated/design-tokens/kotlin").get().asFile.absolutePath,
        )
        res.directories.add(
            rootProject.layout.buildDirectory.dir("generated/design-tokens/android").get().asFile.absolutePath,
        )
        res.directories.add(layout.buildDirectory.dir("generated/brand-res").get().asFile.absolutePath)
        assets.directories.add(layout.buildDirectory.dir("generated/reader-assets").get().asFile.absolutePath)
    }

    sourceSets.named("test") {
        resources.directories.add(
            rootProject.layout.projectDirectory.dir("../../packages/reader-contracts/fixtures").asFile.absolutePath,
        )
    }

    sourceSets.named("androidTest") {
        assets.directories.add(layout.buildDirectory.dir("generated/reader-test-assets").get().asFile.absolutePath)
    }

    packaging {
        resources.excludes += setOf(
            "/META-INF/{AL2.0,LGPL2.1}",
            "META-INF/versions/9/OSGI-INF/MANIFEST.MF",
        )
    }

    testOptions {
        animationsDisabled = true
    }

    lint {
        abortOnError = true
        warningsAsErrors = true
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
        allWarningsAsErrors.set(true)
    }
}

val syncBrandAsset by tasks.registering(Sync::class) {
    val brandSource = rootProject.layout.projectDirectory.file("../web/public/brand/ermao-library-app-icon-v1.png")
    into(layout.buildDirectory.dir("generated/brand-res"))
    from(brandSource) {
        into("drawable-nodpi")
        rename { "ermao_library_brand.png" }
    }
}

val syncReaderAssets by tasks.registering(Sync::class) {
    from(rootProject.layout.projectDirectory.dir("../web/public/fonts/reader"))
    into(layout.buildDirectory.dir("generated/reader-assets/fonts/reader"))
}

val syncReaderTestAssets by tasks.registering(Sync::class) {
    for (format in listOf("epub", "mobi", "comics", "pdf")) {
        from(rootProject.layout.projectDirectory.dir("../../test-data/library/$format")) {
            // Corpus documentation is not a runtime asset and has duplicate names.
            exclude("CORPUS.md")
        }
    }
    from(rootProject.layout.projectDirectory.dir("../../test-data/library/fb2")) {
        into("fb2")
    }
    into(layout.buildDirectory.dir("generated/reader-test-assets"))
}

tasks.named("preBuild") {
    dependsOn(rootProject.tasks.named("generateDesignTokens"))
    dependsOn(syncBrandAsset)
    dependsOn(syncReaderAssets)
    dependsOn(syncReaderTestAssets)
}

dependencies {
    implementation(libs.androidx.exifinterface)
    implementation(project(":shared"))
    implementation(project(":mobiCore"))
    implementation(project(":archiveCore"))
    implementation(project(":pdfiumNative"))

    coreLibraryDesugaring(libs.desugar.jdk.libs)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.compose.foundation)
    implementation(libs.androidx.compose.material.icons.extended)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material3.adaptive.navigation.suite)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.fragment.ktx)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.viewmodel.navigation3)
    implementation(libs.androidx.navigation3.runtime)
    implementation(libs.androidx.navigation3.ui)
    implementation(libs.kotlinx.coroutines.core)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.readium.shared)
    implementation(libs.readium.streamer)
    implementation(libs.readium.navigator)
    implementation(libs.readium.adapter.pdfium)

    debugImplementation(libs.androidx.compose.ui.test.manifest)
    debugImplementation(libs.androidx.compose.ui.tooling)

    testImplementation(platform(libs.androidx.compose.bom))
    testImplementation(libs.androidx.compose.ui.test.junit4)
    testImplementation(libs.junit4)
    testImplementation(kotlin("test"))
    testImplementation(libs.kotlinx.coroutines.test)

    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.test.core.ktx)
    androidTestImplementation(libs.androidx.test.junit.ktx)
    androidTestImplementation(libs.androidx.test.runner)
}
