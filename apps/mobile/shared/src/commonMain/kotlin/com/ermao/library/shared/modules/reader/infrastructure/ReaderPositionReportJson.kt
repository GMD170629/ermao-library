package com.ermao.library.shared.modules.reader.infrastructure

import com.ermao.library.shared.modules.reader.domain.ReaderPositionReport
import kotlinx.serialization.json.JsonObject

/** Versioned JSON codec shared by v5 progress and bookmark local stores. */
class ReaderPositionReportJson(
    private val mapper: ReaderV5ServerWireMapper = ReaderV5ServerWireMapper(),
) {
    fun encode(position: ReaderPositionReport): String = mapper.encodePosition(position).toString()

    @Throws(ReaderServerWireException::class)
    fun decode(payload: String): ReaderPositionReport {
        val root = runCatching {
            readerV5ServerWireJson.parseToJsonElement(payload) as? JsonObject
        }.getOrNull() ?: throw ReaderServerWireException("Reader v5 position report is malformed")
        return mapper.decodePosition(root)
    }
}
