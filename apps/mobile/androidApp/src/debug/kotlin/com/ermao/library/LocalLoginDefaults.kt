package com.ermao.library

import com.ermao.library.bootstrap.LoginFormState

internal fun localLoginDefaults() = LoginFormState(
    serverAddress = "http://192.168.50.179:3000",
    email = "1821483963@qq.com",
    password = "1234567890",
)
