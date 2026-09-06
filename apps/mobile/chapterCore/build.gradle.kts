import org.gradle.api.tasks.Exec
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.android.library)
}

android {
    namespace = "com.ermao.library.chapter"
    compileSdk = libs.versions.android.compile.sdk.get().toInt()

    defaultConfig {
        minSdk = libs.versions.android.min.sdk.get().toInt()
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
        externalNativeBuild {
            cmake { arguments += "-DERMAO_CHAPTERS_BUILD_TESTS=OFF" }
        }
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
        isCoreLibraryDesugaringEnabled = true
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

val hostOsName = System.getProperty("os.name")
val hostOsNameLowercase = hostOsName.lowercase()
val hostArchitecture = System.getProperty("os.arch")
val hostArchitectureLowercase = hostArchitecture.lowercase()
val hostIsWindows = hostOsNameLowercase.contains("windows")
val hostIsLinux = hostOsNameLowercase.contains("linux")
val hostIsX86_64 = hostArchitectureLowercase in setOf("amd64", "x86_64")
val hostNativePlatform = when {
    hostIsWindows && hostIsX86_64 -> "windows-x86_64"
    hostIsLinux && hostIsX86_64 -> "linux-x86_64"
    else -> "unsupported"
}
val hostNativeLibraryName = when {
    hostIsWindows -> "ermao_chapter_jni.dll"
    hostIsLinux -> "libermao_chapter_jni.so"
    else -> "ermao_chapter_jni.native"
}
val hostNativeOutputDirectory = layout.buildDirectory.dir("host-jni/$hostNativePlatform").get().asFile
val mobileRootDirectory = rootProject.projectDir
val repositoryRootDirectory = mobileRootDirectory.parentFile.parentFile
val hostJniScript = layout.projectDirectory.file("scripts/build-host-jni.py").asFile
val hostJdkHome = providers.gradleProperty("hostJniJdk")
    .orElse(providers.environmentVariable("ERMAO_HOST_JNI_JDK"))
    .orElse(System.getProperty("java.home"))
    .get()
val hostPython = providers.environmentVariable("PYTHON")
    .orElse(if (hostIsWindows) "python" else "python3")
    .get()
val hostZigConfiguration = providers.environmentVariable("ERMAO_ZIG").orElse("auto")
val hostCMakeConfiguration = providers.environmentVariable("CMAKE").orElse("auto")
val hostNinjaConfiguration = providers.environmentVariable("NINJA").orElse("auto")

tasks.register<Exec>("buildHostJni") {
    description = "Build the canonical chapter JNI bridge for the local JVM test host"
    group = "verification"

    inputs.property("hostJdkHome", hostJdkHome)
    inputs.property("pythonExecutable", hostPython)
    inputs.property("zigExecutable", hostZigConfiguration)
    inputs.property("cmakeExecutable", hostCMakeConfiguration)
    inputs.property("ninjaExecutable", hostNinjaConfiguration)

    inputs.files(
        file("src/main/cpp/CMakeLists.txt"),
        file("src/main/cpp/chapter_jni.c"),
        file("src/main/cpp/chapter_exports.map"),
        repositoryRootDirectory.resolve("packages/reader-core/native/chapters/CMakeLists.txt"),
        repositoryRootDirectory.resolve("packages/reader-core/native/chapters/chapters.c"),
        repositoryRootDirectory.resolve("packages/reader-core/native/chapters/include/ermao_chapters.h"),
        hostJniScript,
    )
    outputs.file(hostNativeOutputDirectory.resolve(hostNativeLibraryName))

    commandLine(
        hostPython,
        hostJniScript.absolutePath,
        "--repo-root", repositoryRootDirectory.absolutePath,
        "--source-dir", layout.projectDirectory.dir("src/main/cpp").asFile.absolutePath,
        "--build-dir", hostNativeOutputDirectory.resolve("cmake-host-v2").absolutePath,
        "--output-dir", hostNativeOutputDirectory.absolutePath,
        "--jdk-home", hostJdkHome,
    )
}

dependencies {
    coreLibraryDesugaring(libs.desugar.jdk.libs)
    testImplementation(libs.junit4)
    testImplementation(kotlin("test"))
}
