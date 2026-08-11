package com.ermao.library.shared.modules.library

import com.ermao.library.shared.modules.library.domain.WorkDetail
import com.ermao.library.shared.modules.library.domain.WorkDetailSummary
import com.ermao.library.shared.modules.library.domain.WorkSummary
import com.ermao.library.shared.modules.library.infrastructure.WorkDetailPayloadWire
import com.ermao.library.shared.modules.library.infrastructure.WorkDetailSummaryPayloadWire
import com.ermao.library.shared.modules.library.infrastructure.WorkSummaryWire
import com.ermao.library.shared.modules.library.infrastructure.toDomain

/** Stable capability boundary; platform code does not import library infrastructure mappers directly. */
object LibraryContract {
    fun workSummary(wire: WorkSummaryWire): WorkSummary = wire.toDomain()

    fun workDetailSummary(wire: WorkDetailSummaryPayloadWire): WorkDetailSummary = wire.toDomain()

    fun workDetail(wire: WorkDetailPayloadWire): WorkDetail = wire.toDomain()
}
