package com.ermao.library.features.reader.infrastructure

import java.security.MessageDigest

internal fun sha256(bytes: ByteArray): String =
    MessageDigest.getInstance("SHA-256").digest(bytes).toHexString()

internal fun sha256(text: String): String = sha256(text.toByteArray(Charsets.UTF_8))

internal fun MessageDigest.digestToFingerprint(): String = "sha256:" + digest().toHexString()

private fun ByteArray.toHexString(): String = joinToString(separator = "") { byte -> "%02x".format(byte) }
