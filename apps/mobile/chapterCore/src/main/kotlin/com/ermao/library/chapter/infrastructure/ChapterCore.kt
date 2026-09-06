package com.ermao.library.chapter.infrastructure

data class ChapterCoreEntry(
    val index: Int,
    val parentIndex: Int?,
    val navigable: Boolean,
    val key: String,
    val title: String,
    val href: String?,
    val sourceStart: Long,
    val sourceEnd: Long,
    val contentStart: Long,
)

data class ChapterCoreResult(
    val entries: List<ChapterCoreEntry>,
    val text: String,
)

data class ChapterCoreMobiNode(
    val parentIndex: Int?,
    val title: String,
    val href: String?,
)

data class ChapterCoreXmlAttribute(
    val name: String,
    val value: String,
)

/** XML facts emitted by the platform parser; chapter selection remains in the C core. */
data class ChapterCoreXmlEvent(
    val kind: Int,
    val name: String? = null,
    val text: String? = null,
    val attributes: Array<ChapterCoreXmlAttribute> = emptyArray(),
    val href: String? = null,
)

object ChapterCore {
    val abiVersion: Int get() = ChapterCoreNative.abiVersion()

    fun parseTxt(value: String): ChapterCoreResult =
        withResult(ChapterCoreNative.parseTxt(value.encodeToByteArray()))

    fun fromMobi(nodes: List<ChapterCoreMobiNode>): ChapterCoreResult {
        require(nodes.size <= Int.MAX_VALUE)
        return withResult(
            ChapterCoreNative.parseMobi(
                nodes.map { it.parentIndex ?: -1 }.toIntArray(),
                nodes.map { it.title }.toTypedArray(),
                nodes.map { it.href }.toTypedArray(),
            ),
        )
    }

    fun parseXml(format: Int, events: List<ChapterCoreXmlEvent>): ChapterCoreResult {
        require(format in 1..3)
        return withResult(ChapterCoreNative.parseXml(format, events.toTypedArray()))
    }

    private fun withResult(handle: Long): ChapterCoreResult {
        require(handle != 0L) { "Chapter core returned an empty result" }
        try {
            val entries = List(ChapterCoreNative.count(handle)) { index ->
                val values = requireNotNull(ChapterCoreNative.entryValues(handle, index))
                val strings = requireNotNull(ChapterCoreNative.entryStrings(handle, index))
                ChapterCoreEntry(
                    index = values[0].toInt(),
                    parentIndex = values[1].toInt().takeUnless { it < 0 },
                    navigable = values[2] != 0L,
                    sourceStart = values[3],
                    sourceEnd = values[4],
                    contentStart = values[5],
                    key = requireNotNull(strings[0]),
                    title = requireNotNull(strings[1]),
                    href = strings[2],
                )
            }
            val text = ChapterCoreNative.text(handle)?.toString(Charsets.UTF_8).orEmpty()
            return ChapterCoreResult(entries, text)
        } finally {
            ChapterCoreNative.freeResult(handle)
        }
    }
}

private object ChapterCoreNative {
    init { System.loadLibrary("ermao_chapter_jni") }

    external fun abiVersion(): Int
    external fun parseTxt(input: ByteArray): Long
    external fun parseMobi(parents: IntArray, titles: Array<String?>, hrefs: Array<String?>): Long
    external fun parseXml(format: Int, events: Array<ChapterCoreXmlEvent>): Long
    external fun freeResult(handle: Long)
    external fun count(handle: Long): Int
    external fun text(handle: Long): ByteArray?
    external fun entryValues(handle: Long, index: Int): LongArray?
    external fun entryStrings(handle: Long, index: Int): Array<String?>?
}
