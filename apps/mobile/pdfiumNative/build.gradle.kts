plugins {
    alias(libs.plugins.android.library)
}

android {
    namespace = "com.ermao.library.pdfium"
    compileSdk = libs.versions.android.compile.sdk.get().toInt()

    defaultConfig {
        minSdk = libs.versions.android.min.sdk.get().toInt()
        consumerProguardFiles("consumer-rules.pro")
    }

    sourceSets.named("main") {
        jniLibs.directories.add(
            rootProject.layout.projectDirectory.dir("native/pdfium/artifacts/android/jni").asFile.absolutePath,
        )
    }

    lint {
        abortOnError = true
        warningsAsErrors = true
    }
}
