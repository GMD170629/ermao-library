package com.ermao.library.features.reader.infrastructure

import kotlin.test.assertFalse
import kotlin.test.assertTrue
import org.junit.Test

class EpubContentSecurityPolicyTest {
    @Test
    fun removesExecutableAndRemotePublicationContentButKeepsSafeExternalLinks() {
        val input = """
            <html><head>
              <meta http-equiv="refresh" content="0;https://attacker.invalid" />
              <link rel="stylesheet" href="https://attacker.invalid/style.css" />
              <script>fetch('https://attacker.invalid/data')</script>
              <style>.hero { background: url(https://attacker.invalid/image.png); }</style>
            </head><body onload="steal()">
              <iframe src="https://attacker.invalid/frame"></iframe>
              <img src="https://attacker.invalid/pixel.png" />
              <a id="safe" href="https://example.com">Safe link</a>
              <a id="danger" href="javascript:steal()">Dangerous link</a>
            </body></html>
        """.trimIndent()

        val output = EpubContentSecurityPolicy.sanitizeHtml(input.toByteArray()).toString(Charsets.UTF_8)

        assertFalse(output.contains("<script"))
        assertFalse(output.contains("<iframe"))
        assertFalse(output.contains("onload="))
        assertFalse(output.contains("javascript:"))
        assertFalse(output.contains("attacker.invalid"))
        assertTrue(output.contains("href=\"https://example.com\""))
    }
}
