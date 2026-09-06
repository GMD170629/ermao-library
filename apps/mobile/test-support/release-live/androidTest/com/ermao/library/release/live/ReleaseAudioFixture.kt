package com.ermao.library.release.live

import android.content.Context
import android.content.ContextWrapper
import android.content.SharedPreferences
import android.database.DatabaseErrorHandler
import android.database.sqlite.SQLiteDatabase
import java.io.File
import java.io.IOException
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import org.junit.Assert.assertTrue

// Deliberately not a data class: assertion diagnostics must never render credentials.
@Serializable
internal class ReleaseAudioFixture(
    val baseUrl: String,
    val email: String,
    val password: String,
    val bookId: String,
    val resourceId: String,
    val assetId: String,
    val mimeType: String,
    val sourceApiPath: String,
    val expectedDurationMillis: Long,
)

internal class PrivateAudioFixture(
    val directory: File,
    val value: ReleaseAudioFixture,
) {
    companion object {
        fun consume(context: Context, argument: String?): PrivateAudioFixture {
            assertTrue("RG04_RELEASE_FIXTURE_REQUIRED", !argument.isNullOrBlank())
            val root = context.filesDir.canonicalFile
            val supplied = File(requireNotNull(argument))
            val file = (if (supplied.isAbsolute) supplied else File(root, argument)).canonicalFile
            val directory = requireNotNull(file.parentFile)
            assertTrue("RG04_FIXTURE_CONTAINMENT",
                file.name == "fixture.json" && directory.parentFile == root &&
                    directory.name.matches(Regex("rg04-live-[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}")))
            assertTrue("RG04_FRESH_FIXTURE_DIRECTORY_REQUIRED",
                directory.listFiles()?.let { it.size == 1 && it.single().canonicalFile == file } == true)
            assertTrue("RG04_FIXTURE_FILE_REQUIRED", file.isFile)
            val bytes = try {
                assertTrue("RG04_FIXTURE_SIZE", file.length() in 1..65_536L)
                file.readBytes()
            } catch (_: IOException) {
                throw AssertionError("RG04_FIXTURE_READ_FAILED")
            } finally {
                // Consume only the canonically contained input, even when reading fails.
                assertTrue("RG04_FIXTURE_DELETE_FAILED", file.delete())
            }
            val value = try {
                Json.decodeFromString<ReleaseAudioFixture>(bytes.decodeToString())
            } catch (_: SerializationException) {
                // Serialization diagnostics can contain the entire private input.
                throw AssertionError("RG04_FIXTURE_JSON_INVALID")
            } finally {
                bytes.fill(0)
            }
            assertTrue("RG04_FIXTURE_FIELDS_REQUIRED",
                listOf(value.baseUrl, value.email, value.password, value.bookId, value.resourceId,
                    value.assetId, value.mimeType, value.sourceApiPath).all(String::isNotBlank))
            assertTrue("RG04_FIXTURE_DURATION_TOO_SHORT", value.expectedDurationMillis > 12_000)
            assertTrue("RG04_FIXTURE_SOURCE_PATH", value.sourceApiPath.startsWith("/api/"))
            assertTrue("RG04_FIXTURE_ALREADY_USED", File(directory, "probe-started").createNewFile())
            return PrivateAudioFixture(directory, value)
        }
    }
}

/** Only Android storage routing; schema, cookies, device identity and progress keep their owners. */
internal class ReleaseAudioContext(base: Context, private val directory: File) : ContextWrapper(base) {
    override fun getApplicationContext(): Context = this

    override fun getFilesDir(): File = directory

    override fun getSharedPreferences(name: String, mode: Int): SharedPreferences {
        assertTrue("RG04_PREFS_NAME", name.isNotBlank() && '/' !in name && '\\' !in name)
        return baseContext.getSharedPreferences("${directory.name}-$name", mode)
    }

    override fun getDatabasePath(name: String): File = File(directory, name).canonicalFile.also {
        assertTrue("RG04_DATABASE_CONTAINMENT", it.parentFile == directory.canonicalFile)
    }

    override fun openOrCreateDatabase(
        name: String,
        mode: Int,
        factory: SQLiteDatabase.CursorFactory?,
    ): SQLiteDatabase = baseContext.openOrCreateDatabase(getDatabasePath(name).absolutePath, mode, factory)

    override fun openOrCreateDatabase(
        name: String,
        mode: Int,
        factory: SQLiteDatabase.CursorFactory?,
        errorHandler: DatabaseErrorHandler?,
    ): SQLiteDatabase = baseContext.openOrCreateDatabase(
        getDatabasePath(name).absolutePath, mode, factory, errorHandler,
    )
}
