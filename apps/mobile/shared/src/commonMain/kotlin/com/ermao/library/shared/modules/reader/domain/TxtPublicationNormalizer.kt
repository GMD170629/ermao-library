package com.ermao.library.shared.modules.reader.domain

data class NormalizedTxtResource(
    val href: String,
    val title: String,
    val xhtml: String,
)

data class NormalizedTxtPublication(
    val title: String,
    val resources: List<NormalizedTxtResource>,
    val stylesheetHref: String = "text/reader.css",
    val stylesheet: String = TXT_STYLESHEET,
)

const val TXT_PARSER_IDENTIFIER = "shuku-txt-parser-v1"
const val TXT_PUBLICATION_NORMALIZATION_IDENTIFIER = "shuku-txt-publication-v2"

/** Deterministic TXT -> EPUB-profile resources shared by every native platform. */
class TxtPublicationNormalizer {
    fun normalize(decodedText: String, publicationTitle: String): NormalizedTxtPublication {
        require(publicationTitle.isNotBlank()) { "TXT publication title is blank" }
        require('\u0000' !in decodedText) { "TXT publication contains NUL" }
        val normalized = decodedText
            .replace("\r\n", "\n")
            .replace('\r', '\n')
            .replace('\u2028', '\n')
            .replace('\u2029', '\n')
        require(normalized.isNotBlank()) { "TXT publication is empty" }
        val lines = normalized.split('\n').map(String::trimEnd)
        val starts = lines.indices.filter { isChapterHeading(lines[it]) }
        val ranges = chapterRanges(lines, starts)
        val resources = ranges.mapIndexed { chapterIndex, range ->
            val chapterLines = lines.subList(range.first, range.second)
            val heading = chapterLines.firstOrNull()?.takeIf(::isChapterHeading)
                ?: if (ranges.size == 1) publicationTitle else "${publicationTitle} ${chapterIndex + 1}"
            NormalizedTxtResource(
                href = "text/chapter-${(chapterIndex + 1).padded(4)}.xhtml",
                title = heading,
                xhtml = xhtml(
                    title = heading,
                    lines = if (chapterLines.firstOrNull()?.let(::isChapterHeading) == true) {
                        chapterLines.drop(1)
                    } else {
                        chapterLines
                    },
                ),
            )
        }
        require(resources.isNotEmpty()) { "TXT publication has no readable resources" }
        return NormalizedTxtPublication(publicationTitle, resources)
    }

    private fun chapterRanges(lines: List<String>, starts: List<Int>): List<Pair<Int, Int>> {
        if (starts.isEmpty()) return listOf(0 to lines.size)
        val effectiveStarts = if (lines.subList(0, starts.first()).any(String::isNotBlank)) {
            listOf(0) + starts
        } else {
            starts
        }
        return effectiveStarts.mapIndexed { index, start ->
            start to (effectiveStarts.getOrNull(index + 1) ?: lines.size)
        }
    }

    private fun xhtml(title: String, lines: List<String>): String {
        val blocks = mutableListOf<List<String>>()
        var current = mutableListOf<String>()
        fun finishBlock() {
            if (current.isNotEmpty()) blocks += current.toList()
            current = mutableListOf()
        }
        lines.forEach { line ->
            if (line.isBlank()) finishBlock() else current += line
        }
        finishBlock()
        val body = blocks.mapIndexed { index, block ->
            val content = block.joinToString("<br/>") { escapeXml(it) }
            "<p id=\"block-${(index + 1).padded(6)}\">$content</p>"
        }.joinToString("\n")
        return """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="und">
<head><meta charset="utf-8"/><title>${escapeXml(title)}</title><link rel="stylesheet" type="text/css" href="reader.css"/></head>
<body><h1 id="heading-000001">${escapeXml(title)}</h1>
$body
</body></html>"""
    }

    private fun isChapterHeading(line: String): Boolean {
        val value = line.trim()
        return value.length in 2..96 && (CHINESE_CHAPTER.matches(value) || LATIN_CHAPTER.matches(value))
    }

    private fun escapeXml(value: String): String = buildString(value.length) {
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

    private fun Int.padded(width: Int): String = toString().padStart(width, '0')

    private companion object {
        val CHINESE_CHAPTER = Regex("^第[0-9〇零一二三四五六七八九十百千万两]+[章节回卷篇部](?:[ 　:：].*)?$")
        val LATIN_CHAPTER = Regex("^(?i:chapter|part|book)[ \\t]+[0-9ivxlcdm]+(?:[ .:：-].*)?$")
    }
}

private const val TXT_STYLESHEET = """html { color-scheme: light dark; }
body { margin: 0; padding: 1rem; line-height: 1.6; overflow-wrap: anywhere; }
h1 { font-size: 1.35em; margin: 1.5em 0 1em; }
p { margin: 0 0 1em; white-space: normal; }
"""
