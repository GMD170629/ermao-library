package com.ermao.library.shared.modules.reader.domain

data class NormalizedTxtResource(
    val href: String,
    val title: String,
    val xhtml: String,
)

class TxtPublicationEmptyException : IllegalArgumentException("TXT publication is empty")

/** Renders an already segmented TXT body; chapter boundaries come from chapter-core. */
fun renderTxtXhtml(title: String, bodyText: String): String {
        val blocks = mutableListOf<List<String>>()
        var current = mutableListOf<String>()
        fun finishBlock() {
            if (current.isNotEmpty()) blocks += current.toList()
            current = mutableListOf()
        }
        bodyText.replace("\r\n", "\n").replace('\r', '\n').split('\n').forEach { line ->
            if (line.isBlank()) finishBlock() else current += line
        }
        finishBlock()
        val body = blocks.mapIndexed { index, block ->
            val content = block.joinToString("<br/>") { escapeTxtXml(it) }
            "<p id=\"block-${(index + 1).toString().padStart(6, '0')}\">$content</p>"
        }.joinToString("\n")
        return """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="und">
<head><meta charset="utf-8"/><title>${escapeTxtXml(title)}</title><link rel="stylesheet" type="text/css" href="reader.css"/></head>
<body><h1 id="heading-000001">${escapeTxtXml(title)}</h1>
$body
</body></html>"""
}

private fun escapeTxtXml(value: String): String = buildString(value.length) {
        value.forEach { character ->
            append(
                when (character) {
                    '&' -> "&amp;"
                    '<' -> "&lt;"
                    '>' -> "&gt;"
                    '"' -> "&quot;"
                    '\'' -> "&apos;"
                    else -> character
                },
            )
        }
    }
