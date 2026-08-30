package com.ermao.library.features.reader.infrastructure

import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class EpubContentSecurityPolicyInstrumentedTest {
    @Test
    fun serverRenderedXhtmlCanBeDecoratedByAndroidPlatformParser() {
        val markup = """
            <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
              "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">
            <html xmlns="http://www.w3.org/1999/xhtml">
              <head>
                <meta http-equiv="Content-Security-Policy"
                  content="default-src 'none'; script-src blob:; style-src 'self' 'unsafe-inline'"
                  data-shuku-security-profile="web-v2" />
                <title>Server publication</title>
              </head>
              <body><p>Readable chapter</p></body>
            </html>
        """.trimIndent()

        val decorated = EpubContentSecurityPolicy.decorateHtml(markup.encodeToByteArray()).decodeToString()

        assertTrue(decorated.contains("data-shuku-safety-policy-version=\"1\""))
        assertTrue(decorated.contains("<p>Readable chapter</p>"))
    }
}
