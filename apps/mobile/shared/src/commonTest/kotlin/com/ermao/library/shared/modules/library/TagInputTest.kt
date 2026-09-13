package com.ermao.library.shared.modules.library

import kotlin.test.Test
import kotlin.test.assertEquals

class TagInputTest {
    @Test fun inputMatchesWebSeparatorsAndNormalization() {
        assertEquals(listOf("科幻", "待读", "年度精选", "中文", "短篇"), TagInput.parse("科幻, 待读；年度精选\n中文，短篇"))
        assertEquals(TagInput.key("sci fi"), TagInput.key(" ＳＣＩ－ＦＩ "))
        assertEquals(TagInput.key("龙族 完结"), TagInput.key("龙族【完结】"))
        assertEquals(listOf("Sci-Fi", "待 阅读"), TagInput.parse(" Sci-Fi ,sci fi,,待  阅读;待 阅读"))
    }

    @Test fun editingPreservesStoredNamesAndOnlyDeduplicatesNewInput() {
        val stored = TagInput.stored("History, Politics\nSci-Fi")
        assertEquals(listOf("History, Politics", "Sci-Fi"), stored)
        assertEquals(stored + "Fantasy", TagInput.append(stored, "sci fi；Fantasy;fantasy"))
        assertEquals(stored, TagInput.append(stored, " , ; \n"))
    }
}
