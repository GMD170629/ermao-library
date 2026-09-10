package com.ermao.library.shared.modules.administrativesettings

fun createOpdsEditState(enabled: Boolean, publicBaseUrl: String): OpdsEditState =
    OpdsEditState(OpdsEditValues(enabled, publicBaseUrl))

/** Defer focus-loss submission briefly so the same tap's toggle event can replace it. */
fun opdsFocusCommitDelayMilliseconds(): Long = 150L
