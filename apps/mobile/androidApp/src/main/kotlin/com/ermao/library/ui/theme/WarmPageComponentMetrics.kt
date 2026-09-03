package com.ermao.library.ui.theme

import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ermao.library.design.GeneratedDesignTokens

/** Android-only component geometry. Shared visual tokens remain generated from design/tokens.json. */
@Immutable
data class WarmPageComponentMetrics(
    val page: WarmPagePageMetrics,
    val topBar: WarmPageTopBarMetrics,
    val controls: WarmPageControlMetrics,
    val menu: WarmPageMenuMetrics,
    val grid: WarmPageGridMetrics,
    val covers: WarmPageComponentCoverMetrics,
    val workDetail: WarmPageWorkDetailMetrics,
    val settings: WarmPageSettingsMetrics,
    val dividerThickness: Dp,
)

@Immutable
data class WarmPagePageMetrics(
    val compactGutter: Dp,
    val sectionGap: Dp,
    val contentBottomInset: Dp,
    val expandedBreakpoint: Dp,
)

@Immutable
data class WarmPageTopBarMetrics(
    val rootHeight: Dp,
    val detailHeight: Dp,
)

@Immutable
data class WarmPageControlMetrics(
    val minimumTouchTarget: Dp,
    val searchMinimumHeight: Dp,
    val segmentedMinimumHeight: Dp,
    val actionMinimumHeight: Dp,
    val iconSize: Dp,
    val toolbarIconSize: Dp,
    val loadingIndicatorSize: Dp,
)

@Immutable
data class WarmPageMenuMetrics(
    val itemMinimumHeight: Dp,
    val titleHorizontalPadding: Dp,
    val titleVerticalPadding: Dp,
)

@Immutable
data class WarmPageGridMetrics(
    val horizontalGap: Dp,
    val verticalGap: Dp,
    val compactColumns: Int,
    val largeTextColumns: Int,
)

@Immutable
data class WarmPageComponentCoverMetrics(
    val continueWidth: Dp,
    val heroWidth: Dp,
    val heroAspectRatio: Float,
    val groupingStackWidth: Dp,
    val groupingStackHeight: Dp,
    val groupingCoverWidth: Dp,
    val groupingCoverOffset: Dp,
)

@Immutable
data class WarmPageWorkDetailMetrics(
    val heroCoverWidth: Dp,
    val horizontalVolumeWidth: Dp,
    val chapterRowMinimumHeight: Dp,
    val statusBadgeMinimumHeight: Dp,
)

@Immutable
data class WarmPageSettingsMetrics(
    val rowMinimumHeight: Dp,
    val horizontalInset: Dp,
    val verticalInset: Dp,
    val iconSlotSize: Dp,
    val iconSize: Dp,
    val iconTitleSpacing: Dp,
    val trailingSlotWidth: Dp,
    val sectionSpacing: Dp,
    val sectionHeaderBottomSpacing: Dp,
    val identityAvatarSize: Dp,
    val identityMinimumHeight: Dp,
    val bottomActionHeight: Dp,
)

val WarmPageComponentMetricTokens = WarmPageComponentMetrics(
    page = WarmPagePageMetrics(
        compactGutter = WarmPageSpacingTokens.two,
        sectionGap = WarmPageSpacingTokens.three,
        contentBottomInset = WarmPageSpacingTokens.three,
        expandedBreakpoint = 840.dp,
    ),
    topBar = WarmPageTopBarMetrics(
        rootHeight = 72.dp,
        detailHeight = 64.dp,
    ),
    controls = WarmPageControlMetrics(
        minimumTouchTarget = WarmPageMetricTokens.androidMinimumTouchTarget,
        searchMinimumHeight = WarmPageMetricTokens.androidMinimumTouchTarget,
        segmentedMinimumHeight = WarmPageMetricTokens.androidMinimumTouchTarget,
        actionMinimumHeight = WarmPageMetricTokens.androidMinimumTouchTarget,
        iconSize = WarmPageSpacingTokens.three,
        toolbarIconSize = WarmPageSpacingTokens.three,
        loadingIndicatorSize = WarmPageSpacingTokens.three,
    ),
    menu = WarmPageMenuMetrics(
        itemMinimumHeight = WarmPageMetricTokens.androidMinimumTouchTarget,
        titleHorizontalPadding = WarmPageSpacingTokens.oneAndHalf,
        titleVerticalPadding = WarmPageSpacingTokens.one,
    ),
    grid = WarmPageGridMetrics(
        horizontalGap = WarmPageSpacingTokens.two,
        verticalGap = WarmPageSpacingTokens.three,
        compactColumns = 3,
        largeTextColumns = 2,
    ),
    covers = WarmPageComponentCoverMetrics(
        continueWidth = 104.dp,
        heroWidth = 112.dp,
        heroAspectRatio = WarmPageMetricTokens.coverAspectRatio,
        groupingStackWidth = 104.dp,
        groupingStackHeight = 78.dp,
        groupingCoverWidth = 52.dp,
        groupingCoverOffset = 24.dp,
    ),
    workDetail = WarmPageWorkDetailMetrics(
        heroCoverWidth = 120.dp,
        horizontalVolumeWidth = 84.dp,
        chapterRowMinimumHeight = 56.dp,
        statusBadgeMinimumHeight = 24.dp,
    ),
    settings = WarmPageSettingsMetrics(
        rowMinimumHeight = GeneratedDesignTokens.Settings.RowMinimumHeight.dp,
        horizontalInset = GeneratedDesignTokens.Settings.HorizontalInset.dp,
        verticalInset = GeneratedDesignTokens.Settings.VerticalInset.dp,
        iconSlotSize = GeneratedDesignTokens.Settings.IconSlotSize.dp,
        iconSize = GeneratedDesignTokens.Settings.IconSize.dp,
        iconTitleSpacing = GeneratedDesignTokens.Settings.IconTitleSpacing.dp,
        trailingSlotWidth = GeneratedDesignTokens.Settings.TrailingSlotWidth.dp,
        sectionSpacing = GeneratedDesignTokens.Settings.SectionSpacing.dp,
        sectionHeaderBottomSpacing = GeneratedDesignTokens.Settings.SectionHeaderBottomSpacing.dp,
        identityAvatarSize = GeneratedDesignTokens.Settings.IdentityAvatarSize.dp,
        identityMinimumHeight = GeneratedDesignTokens.Settings.IdentityMinimumHeight.dp,
        bottomActionHeight = GeneratedDesignTokens.Settings.BottomActionHeight.dp,
    ),
    dividerThickness = Dp.Hairline,
)

internal val LocalWarmPageComponentMetrics = staticCompositionLocalOf { WarmPageComponentMetricTokens }
