package com.ermao.library

import com.ermao.library.bootstrap.LoginFormState

internal fun localLoginDefaults() = LoginFormState(
    serverAddress = "http://10.0.2.2:8000",
    email = "1821483963@qq.com",
    password = "1234567890",
)
