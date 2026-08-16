package com.ermao.library.features.reader.presentation

import android.animation.ValueAnimator
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.animation.core.FastOutLinearInEasing
import androidx.compose.animation.core.LinearOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp

internal data class ReaderControlMotionSpec(
    val enterDurationMillis: Int,
    val exitDurationMillis: Int,
    val translationDp: Int,
)

internal fun readerControlMotionSpec(systemAnimationsEnabled: Boolean): ReaderControlMotionSpec =
    if (systemAnimationsEnabled) {
        ReaderControlMotionSpec(
            enterDurationMillis = 180,
            exitDurationMillis = 150,
            translationDp = 8,
        )
    } else {
        ReaderControlMotionSpec(
            enterDurationMillis = 0,
            exitDurationMillis = 0,
            translationDp = 0,
        )
    }

@Composable
internal fun ReaderControlsVisibility(
    visible: Boolean,
    content: @Composable () -> Unit,
) {
    val motion = readerControlMotionSpec(ValueAnimator.areAnimatorsEnabled())
    val translationPixels = with(LocalDensity.current) { motion.translationDp.dp.roundToPx() }
    val enter = if (motion.enterDurationMillis == 0) {
        EnterTransition.None
    } else {
        fadeIn(
            animationSpec = tween(motion.enterDurationMillis, easing = LinearOutSlowInEasing),
        ) + slideInVertically(
            animationSpec = tween(motion.enterDurationMillis, easing = LinearOutSlowInEasing),
            initialOffsetY = { translationPixels },
        )
    }
    val exit = if (motion.exitDurationMillis == 0) {
        ExitTransition.None
    } else {
        fadeOut(
            animationSpec = tween(motion.exitDurationMillis, easing = FastOutLinearInEasing),
        ) + slideOutVertically(
            animationSpec = tween(motion.exitDurationMillis, easing = FastOutLinearInEasing),
            targetOffsetY = { translationPixels },
        )
    }

    AnimatedVisibility(
        visible = visible,
        enter = enter,
        exit = exit,
        content = { content() },
    )
}
