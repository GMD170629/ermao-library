package com.ermao.library.shared.modules.servers

import kotlin.random.Random

/** Generates a client-owned profile identifier independently of server identity. */
fun interface ProfileIdGenerator {
    fun generate(): String
}

/** Common default for callers that do not inject a deterministic generator. */
class RandomProfileIdGenerator private constructor(
    private val random: Random,
) : ProfileIdGenerator {
    constructor() : this(Random.Default)

    override fun generate(): String {
        val bytes = ByteArray(UUID_BYTE_COUNT).also { random.nextBytes(it) }
        bytes[6] = ((bytes[6].toInt() and VERSION_CLEAR_MASK) or VERSION_FOUR).toByte()
        bytes[8] = ((bytes[8].toInt() and VARIANT_CLEAR_MASK) or RFC_4122_VARIANT).toByte()
        return buildString(UUID_TEXT_LENGTH) {
            bytes.forEachIndexed { index, byte ->
                if (index in UUID_DASH_POSITIONS) append('-')
                append(HEX_DIGITS[(byte.toInt() ushr 4) and HEX_MASK])
                append(HEX_DIGITS[byte.toInt() and HEX_MASK])
            }
        }
    }

    private companion object {
        const val UUID_BYTE_COUNT = 16
        const val UUID_TEXT_LENGTH = 36
        const val VERSION_CLEAR_MASK = 0x0f
        const val VERSION_FOUR = 0x40
        const val VARIANT_CLEAR_MASK = 0x3f
        const val RFC_4122_VARIANT = 0x80
        const val HEX_MASK = 0x0f
        const val HEX_DIGITS = "0123456789abcdef"
        val UUID_DASH_POSITIONS = setOf(4, 6, 8, 10)
    }
}
