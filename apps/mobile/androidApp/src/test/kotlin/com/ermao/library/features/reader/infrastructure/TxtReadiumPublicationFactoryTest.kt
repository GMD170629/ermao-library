package com.ermao.library.features.reader.infrastructure

import java.nio.charset.Charset
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import org.junit.Test

class TxtReadiumPublicationFactoryTest {
    @Test
    fun `strict decoder accepts UTF-16 BOM without treating encoding bytes as NUL text`() {
        val bytes = byteArrayOf(0xFF.toByte(), 0xFE.toByte()) + "第一章".toByteArray(Charsets.UTF_16LE)

        assertEquals("第一章", StrictTxtDecoder.decode(bytes))
    }

    @Test
    fun `strict decoder rejects decoded NUL characters`() {
        assertFailsWith<IllegalArgumentException> {
            StrictTxtDecoder.decode(byteArrayOf('A'.code.toByte(), 0, 'B'.code.toByte()))
        }
    }

    @Test
    fun `strict decoder accepts legacy trailing NUL padding`() {
        val bytes = "有效正文".toByteArray(Charset.forName("GB18030")) + ByteArray(160)

        assertEquals("有效正文", StrictTxtDecoder.decode(bytes))
    }

    @Test
    fun decoderSupportsBomUnicodeAndGb18030ButRejectsInvalidText() {
        val utf16 = byteArrayOf(0xFF.toByte(), 0xFE.toByte()) + "章节".toByteArray(Charsets.UTF_16LE)
        assertEquals("章节", StrictTxtDecoder.decode(utf16))
        val gb18030 = "中文内容".toByteArray(Charset.forName("GB18030"))
        assertEquals("中文内容", StrictTxtDecoder.decode(gb18030))
        assertFailsWith<IllegalArgumentException> { StrictTxtDecoder.decode(byteArrayOf(0, 1)) }
    }
}
