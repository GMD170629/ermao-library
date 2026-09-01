package com.ermao.library.shared.modules.audio.domain

import com.ermao.library.shared.modules.reader.ReaderSyncNamespace

data class AudioLocalArtifactIdentity(
    val namespace: ReaderSyncNamespace,
    val bookId: String,
    val resourceId: String,
    val assetId: String,
) {
    init {
        require(bookId.isNotBlank() && resourceId.isNotBlank() && assetId.isNotBlank())
    }
}

/** Opaque completed-download reference. Native storage validates the reference before opening it. */
data class AudioLocalArtifact(
    val identity: AudioLocalArtifactIdentity,
    val artifactToken: String,
    val verifiedSizeBytes: Long,
    val completed: Boolean,
) {
    init {
        require(artifactToken.isNotBlank())
        require(verifiedSizeBytes >= 0)
        require(completed || verifiedSizeBytes == 0L)
    }
}

object AudioLocalFallbackPolicy {
    fun exactCompletedArtifact(
        publication: AudioPublication,
        asset: AudioAsset,
        artifacts: List<AudioLocalArtifact>,
    ): AudioLocalArtifact? = artifacts.singleOrNull { artifact ->
        artifact.completed &&
            artifact.verifiedSizeBytes == asset.sizeBytes &&
            artifact.identity.namespace == publication.namespace &&
            artifact.identity.bookId == publication.bookId &&
            artifact.identity.resourceId == publication.resource.resourceId &&
            artifact.identity.assetId == asset.assetId
    }
}
