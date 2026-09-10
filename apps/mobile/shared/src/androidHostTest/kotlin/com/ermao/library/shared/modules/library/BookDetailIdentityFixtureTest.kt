package com.ermao.library.shared.modules.library

import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals

class BookDetailIdentityFixtureTest {
    @Test
    fun sharedPageIdentityMatchesCrossPlatformExamples() {
        val cases = Json.parseToJsonElement(File(requireNotNull(System.getProperty("bookDetailIdentityFixturePath"))).readText()).jsonArray
        for (entry in cases) {
            val case = entry.jsonObject
            assertEquals(case.getValue("source").jsonPrimitive.content,
                resolveBookDetailIdentitySource(
                    case.getValue("isBookRoot").jsonPrimitive.boolean,
                    case.getValue("hasSelectedResource").jsonPrimitive.boolean,
                ).name, case.getValue("name").jsonPrimitive.content)
        }
    }
}
