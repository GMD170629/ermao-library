package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ReaderPdfFit
import com.ermao.library.shared.modules.reader.ReaderPdfPreferences
import org.readium.adapter.pdfium.navigator.PdfiumPreferences
import org.readium.r2.navigator.preferences.Axis
import org.readium.r2.navigator.preferences.Fit

/** Maps only preferences supported by the public Readium PDFium configuration API. */
internal fun ReaderPdfPreferences.toReadiumPdfium(): PdfiumPreferences = PdfiumPreferences(
    fit = when (fit) {
        ReaderPdfFit.Width -> Fit.WIDTH
        ReaderPdfFit.Page -> Fit.CONTAIN
    },
    scrollAxis = Axis.HORIZONTAL,
)
