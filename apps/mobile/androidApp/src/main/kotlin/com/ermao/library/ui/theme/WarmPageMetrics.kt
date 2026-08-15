package com.ermao.library.ui.theme

import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ermao.library.design.GeneratedDesignTokens

@Immutable
data class WarmPageMetrics(
    val coverAspectRatio: Float,
    val coverProgressHeight: Dp,
    val coverProgressHorizontalInset: Dp,
    val readingProgressHeight: Dp,
    val downloadProgressHeight: Dp,
    val androidMinimumTouchTarget: Dp,
)

val WarmPageMetricTokens = WarmPageMetrics(
    coverAspectRatio = (
        GeneratedDesignTokens.Cover.AspectWidth / GeneratedDesignTokens.Cover.AspectHeight
    ).toFloat(),
    coverProgressHeight = GeneratedDesignTokens.Progress.CoverHeight.dp,
    coverProgressHorizontalInset = GeneratedDesignTokens.Progress.CoverHorizontalInset.dp,
    readingProgressHeight = GeneratedDesignTokens.Progress.ReadingHeight.dp,
    downloadProgressHeight = GeneratedDesignTokens.Progress.DownloadHeight.dp,
    androidMinimumTouchTarget = GeneratedDesignTokens.Progress.AndroidMinimumTouchTarget.dp,
)

internal val LocalWarmPageMetrics = staticCompositionLocalOf { WarmPageMetricTokens }
