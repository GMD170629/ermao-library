package com.ermao.library.features.downloads

import com.ermao.library.features.downloads.model.AndroidDownloadRecord
import kotlin.test.assertFailsWith
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import org.junit.Test

class AndroidDownloadRecordMigrationTest {
    @Test
    fun catalogWithoutVersionFieldsIsRejected() {
        val legacy = """
            {
              "taskId":"task","namespace":{"serverIdentity":"server","userId":"user","authorizationVersion":2},
              "workId":"work","workTitle":"Book","author":"Author","coverUrl":"/api/works/work/cover",
              "volumeId":"volume","volumeTitle":"Volume","format":"EPUB","readerType":"reflowable",
              "sourceApiPath":"/api/volumes/volume/file",
              "sourceMimeType":"application/epub+zip","expectedBytes":4,"transferredBytes":4,
              "status":"Completed","localReference":"artifact.bin","verified":true,
              "createdAtEpochMillis":1,"updatedAtEpochMillis":2
            }
        """.trimIndent()

        assertFailsWith<SerializationException> {
            Json.decodeFromString<AndroidDownloadRecord>(legacy)
        }
    }
}
