package com.ermao.library.features.reader

import com.ermao.library.features.reader.infrastructure.AndroidReaderCapabilities
import com.ermao.library.shared.modules.reader.ReaderSourceFormat
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AndroidReaderCapabilitiesTest {
    @Test
    fun declaresOnlyFormatsWithParserNavigatorLocationAndLocalRestore() {
        val expected = setOf(
            ReaderSourceFormat.Epub,
            ReaderSourceFormat.Mobi,
            ReaderSourceFormat.Azw,
            ReaderSourceFormat.Azw3,
            ReaderSourceFormat.Prc,
            ReaderSourceFormat.Txt,
            ReaderSourceFormat.Fb2,
            ReaderSourceFormat.Cbz,
            ReaderSourceFormat.Zip,
            ReaderSourceFormat.Cbr,
            ReaderSourceFormat.Rar,
            ReaderSourceFormat.ImageDir,
            ReaderSourceFormat.Pdf,
        )

        ReaderSourceFormat.entries.forEach { format ->
            val capability = requireNotNull(AndroidReaderCapabilities.registry.capability(format))
            if (format in expected) {
                assertTrue("$format must be reader-ready", capability.canOpen)
            } else {
                assertFalse("$format must not be advertised", capability.canOpen)
            }
        }
    }
}
