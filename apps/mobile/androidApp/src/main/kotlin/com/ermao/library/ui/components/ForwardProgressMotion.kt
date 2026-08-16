package com.ermao.library.ui.components

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember

internal enum class ProgressMotion {
    AnimateForward,
    Snap,
}

internal fun progressMotion(from: Float, to: Float): ProgressMotion =
    if (to > from) ProgressMotion.AnimateForward else ProgressMotion.Snap

@Composable
fun rememberForwardProgress(
    targetProgress: Float,
    progressIdentity: String? = null,
): Float {
    val target = targetProgress.coerceIn(0f, 1f)
    val progress = remember(progressIdentity) { Animatable(target) }
    LaunchedEffect(progress, target) {
        when (progressMotion(progress.value, target)) {
            ProgressMotion.AnimateForward -> progress.animateTo(
                targetValue = target,
                animationSpec = tween(durationMillis = 150, easing = LinearEasing),
            )
            ProgressMotion.Snap -> progress.snapTo(target)
        }
    }
    return progress.value
}
