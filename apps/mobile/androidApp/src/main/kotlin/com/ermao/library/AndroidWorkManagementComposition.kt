package com.ermao.library

import android.content.Context
import com.ermao.library.features.reader.infrastructure.AndroidReaderDeviceIdentity
import com.ermao.library.platform.persistence.AndroidReaderPrivateStateStore
import com.ermao.library.shared.createAndroidWorkManagementRepository as createAndroidNetworkWorkManagementRepository
import com.ermao.library.shared.modules.reader.ReaderSyncNamespace
import com.ermao.library.shared.modules.workmanagement.BookManagementContext
import com.ermao.library.shared.modules.workmanagement.ReadingStatusResetPort
import com.ermao.library.shared.modules.workmanagement.WorkManagementRepository
import com.ermao.library.shared.modules.workmanagement.withReadingStatusReset

/**
 * Android composition for work management. The shared repository owns the
 * network mutation; this platform adapter owns the device-local Reader V5
 * purge that follows an accepted reading-status change.
 */
internal fun createAndroidWorkManagementRepository(context: Context): WorkManagementRepository {
    val appContext = context.applicationContext
    return withReadingStatusReset(
        repository = createAndroidNetworkWorkManagementRepository(appContext),
        resetPort = object : ReadingStatusResetPort {
            override suspend fun resetBook(context: BookManagementContext, bookId: String) {
                AndroidReaderPrivateStateStore.deleteBookPositions(
                    context = appContext,
                    namespace = context.readerSyncNamespace(),
                    clientId = AndroidReaderDeviceIdentity(appContext).stableDeviceId(),
                    bookId = bookId,
                )
            }

            override suspend fun resetResource(context: BookManagementContext, resourceId: String) {
                AndroidReaderPrivateStateStore.deletePosition(
                    context = appContext,
                    namespace = context.readerSyncNamespace(),
                    clientId = AndroidReaderDeviceIdentity(appContext).stableDeviceId(),
                    resourceId = resourceId,
                )
            }
        },
    )
}

private fun BookManagementContext.readerSyncNamespace(): ReaderSyncNamespace = ReaderSyncNamespace(
    serverIdentity = namespace.serverIdentity,
    userId = namespace.userId,
    authorizationVersion = namespace.authorizationVersion,
)
