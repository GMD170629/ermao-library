package com.ermao.poc.mobireadium

import org.json.JSONObject
import org.junit.Assert.assertTrue
import org.junit.Test
import org.readium.r2.navigator.epub.EpubNavigatorFactory
import org.readium.r2.shared.publication.Manifest
import org.readium.r2.shared.publication.Publication

class ReadiumRuntimePublicationTest {
    @Test
    fun runtimePublicationCanBeHandedToEpubNavigator() {
        val manifest = Manifest.fromJSON(JSONObject("""
            {
              "metadata": {
                "title": "Runtime MOBI publication",
                "conformsTo": ["https://readium.org/webpub-manifest/profiles/epub"]
              },
              "links": [],
              "readingOrder": [
                {"href": "chapter-1.xhtml", "type": "application/xhtml+xml"}
              ]
            }
        """.trimIndent())) ?: error("Manifest parse failed")

        val publication = Publication(manifest)
        assertTrue(publication.conformsTo(Publication.Profile.EPUB))

        // This is the architectural seam we need for libmobi: the EPUB navigator
        // accepts a runtime Publication; it does not require an .epub package or OPF parser output.
        EpubNavigatorFactory(publication)
    }
}
