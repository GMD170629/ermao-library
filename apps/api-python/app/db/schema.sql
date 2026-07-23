-- SQLite is the only supported database. This schema is idempotent for new installs.

CREATE TABLE IF NOT EXISTS `User` (
    `id` TEXT NOT NULL,
    `email` TEXT NOT NULL,
    `name` TEXT NOT NULL,
    `passwordHash` TEXT NOT NULL,
    `avatarPath` TEXT NULL,
    `role` TEXT NOT NULL DEFAULT 'member',
    `status` TEXT NOT NULL DEFAULT 'active',
    `canManageSystem` INTEGER NOT NULL DEFAULT 0,
    `canViewManualImports` INTEGER NOT NULL DEFAULT 0,
    `authzVersion` INTEGER NOT NULL DEFAULT 1,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`)
);

CREATE TABLE IF NOT EXISTS `Session` (
    `id` TEXT NOT NULL,
    `tokenHash` TEXT NOT NULL,
    `userId` TEXT NOT NULL,
    `expiresAt` TEXT NOT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `PasswordResetToken` (
    `id` TEXT NOT NULL,
    `tokenHash` TEXT NOT NULL,
    `userId` TEXT NOT NULL,
    `expiresAt` TEXT NOT NULL,
    `usedAt` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `MonitorFolder` (
    `id` TEXT NOT NULL,
    `name` TEXT NOT NULL,
    `rootPath` TEXT NOT NULL,
    `shelfId` TEXT NULL,
    `enabled` INTEGER NOT NULL DEFAULT 1,
    `ignorePatterns` TEXT NULL,
    `ignoreHidden` INTEGER NOT NULL DEFAULT 1,
    `minFileSizeBytes` INTEGER NOT NULL DEFAULT 10240,
    `description` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`shelfId`) REFERENCES `Shelf`(`id`) ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `UserMonitorFolderAccess` (
    `userId` TEXT NOT NULL,
    `monitorFolderId` TEXT NOT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`userId`, `monitorFolderId`),
    FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`monitorFolderId`) REFERENCES `MonitorFolder`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `UserPreference` (
    `userId` TEXT NOT NULL,
    `key` TEXT NOT NULL,
    `value` TEXT NOT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`userId`, `key`),
    FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `Source` (
    `id` TEXT NOT NULL,
    `name` TEXT NOT NULL,
    `kind` TEXT NOT NULL,
    `providerType` TEXT NOT NULL,
    `enabled` INTEGER NOT NULL DEFAULT 1,
    `priority` INTEGER NOT NULL DEFAULT 100,
    `config` TEXT NULL,
    `credentialsKey` TEXT NULL,
    `capabilities` TEXT NULL,
    `rateLimit` TEXT NULL,
    `lastTestAt` TEXT NULL,
    `lastTestStatus` TEXT NULL,
    `lastError` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`)
);

CREATE TABLE IF NOT EXISTS `SourceSearchRecord` (
    `id` TEXT NOT NULL,
    `sourceId` TEXT NOT NULL,
    `providerType` TEXT NOT NULL,
    `externalId` TEXT NOT NULL,
    `title` TEXT NOT NULL,
    `subtitle` TEXT NULL,
    `author` TEXT NULL,
    `description` TEXT NULL,
    `coverUrl` TEXT NULL,
    `externalUrl` TEXT NULL,
    `format` TEXT NULL,
    `size` TEXT NULL,
    `language` TEXT NULL,
    `publishedAt` TEXT NULL,
    `downloadAvailable` INTEGER NOT NULL DEFAULT 0,
    `downloadMeta` TEXT NULL,
    `raw` TEXT NULL,
    `status` TEXT NOT NULL DEFAULT 'new',
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`sourceId`) REFERENCES `Source`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `DownloadTask` (
    `id` TEXT NOT NULL,
    `sourceId` TEXT NULL,
    `searchRecordId` TEXT NULL,
    `bookId` TEXT NULL,
    `type` TEXT NOT NULL,
    `status` TEXT NOT NULL,
    `displayName` TEXT NOT NULL,
    `remoteRef` TEXT NULL,
    `savePath` TEXT NULL,
    `filePath` TEXT NULL,
    `errorMessage` TEXT NULL,
    `progress` REAL NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`)
);

CREATE TABLE IF NOT EXISTS `LibraryWork` (
    `id` TEXT NOT NULL,
    `monitorFolderId` TEXT NULL,
    `origin` TEXT NOT NULL DEFAULT 'MANUAL',
    `title` TEXT NOT NULL,
    `normalizedTitle` TEXT NOT NULL,
    `author` TEXT NULL,
    `normalizedAuthor` TEXT NULL,
    `description` TEXT NULL,
    `workType` TEXT NOT NULL,
    `status` TEXT NOT NULL DEFAULT 'UNREAD',
    `publicationStatus` TEXT NOT NULL DEFAULT 'UNKNOWN',
    `trackingStatus` TEXT NOT NULL DEFAULT 'NOT_TRACKING',
    `localLatestVolume` REAL NULL,
    `localLatestChapter` REAL NULL,
    `localLatestTitle` TEXT NULL,
    `localLatestAt` TEXT NULL,
    `tags` TEXT NOT NULL,
    `seriesName` TEXT NULL,
    `seriesIndex` REAL NULL,
    `publishedYear` INTEGER NULL,
    `metadataQuality` INTEGER NOT NULL DEFAULT 0,
    `organizeStatus` TEXT NOT NULL DEFAULT 'REVIEWING',
    `coverPath` TEXT NULL,
    `coverStatus` TEXT NOT NULL DEFAULT 'PENDING',
    `hidden` INTEGER NOT NULL DEFAULT 0,
    `organized` INTEGER NOT NULL DEFAULT 0,
    `primaryEditionId` TEXT NULL,
    `mergeKey` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`monitorFolderId`) REFERENCES `MonitorFolder`(`id`) ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `LibraryEdition` (
    `id` TEXT NOT NULL,
    `workId` TEXT NOT NULL,
    `monitorFolderId` TEXT NULL,
    `origin` TEXT NOT NULL DEFAULT 'MANUAL',
    `mediaKind` TEXT NOT NULL DEFAULT 'EBOOK',
    `format` TEXT NOT NULL,
    `versionName` TEXT NOT NULL,
    `versionKey` TEXT NOT NULL,
    `sourceGroupKey` TEXT NULL,
    `description` TEXT NULL,
    `language` TEXT NULL,
    `publisher` TEXT NULL,
    `publishedAt` TEXT NULL,
    `identifier` TEXT NULL,
    `isbn` TEXT NULL,
    `importStatus` TEXT NOT NULL DEFAULT 'PENDING',
    `importError` TEXT NULL,
    `sizeBytes` INTEGER NOT NULL DEFAULT 0,
    `pageCount` INTEGER NULL,
    `chapterCount` INTEGER NULL,
    `durationMs` INTEGER NULL,
    `trackCount` INTEGER NULL,
    `narrator` TEXT NULL,
    `abridged` INTEGER NULL,
    `coverPath` TEXT NULL,
    `coverStatus` TEXT NOT NULL DEFAULT 'PENDING',
    `primary` INTEGER NOT NULL DEFAULT 0,
    `hidden` INTEGER NOT NULL DEFAULT 0,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`workId`) REFERENCES `LibraryWork`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`monitorFolderId`) REFERENCES `MonitorFolder`(`id`) ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `LibraryVolume` (
    `id` TEXT NOT NULL,
    `editionId` TEXT NOT NULL,
    `title` TEXT NOT NULL,
    `volumeIndex` REAL NULL,
    `sortOrder` INTEGER NOT NULL DEFAULT 0,
    `pageCount` INTEGER NULL,
    `chapterCount` INTEGER NULL,
    `durationMs` INTEGER NULL,
    `coverPath` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`editionId`) REFERENCES `LibraryEdition`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `LibraryFile` (
    `id` TEXT NOT NULL,
    `editionId` TEXT NOT NULL,
    `volumeId` TEXT NULL,
    `path` TEXT NOT NULL,
    `filePathHash` TEXT NULL,
    `fingerprint` TEXT NULL,
    `fullHash` TEXT NULL,
    `hashStatus` TEXT NOT NULL DEFAULT 'FAILED',
    `mtimeMs` INTEGER NOT NULL DEFAULT 0,
    `kind` TEXT NOT NULL,
    `mimeType` TEXT NOT NULL,
    `sizeBytes` INTEGER NOT NULL DEFAULT 0,
    `durationMs` INTEGER NULL,
    `codec` TEXT NULL,
    `bitrate` INTEGER NULL,
    `sampleRate` INTEGER NULL,
    `channels` INTEGER NULL,
    `discNumber` INTEGER NULL,
    `trackNumber` INTEGER NULL,
    `sortOrder` INTEGER NOT NULL DEFAULT 0,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`editionId`) REFERENCES `LibraryEdition`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`volumeId`) REFERENCES `LibraryVolume`(`id`) ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `KindleSendTask` (
    `id` TEXT NOT NULL,
    `userId` TEXT NULL,
    `workId` TEXT NULL,
    `editionId` TEXT NULL,
    `volumeId` TEXT NULL,
    `fileId` TEXT NULL,
    `bookTitle` TEXT NOT NULL,
    `editionName` TEXT NULL,
    `volumeTitle` TEXT NULL,
    `fileName` TEXT NOT NULL,
    `format` TEXT NOT NULL,
    `mimeType` TEXT NOT NULL,
    `sizeBytes` INTEGER NOT NULL DEFAULT 0,
    `senderEmail` TEXT NULL,
    `recipientEmail` TEXT NOT NULL,
    `subject` TEXT NOT NULL,
    `smtpHost` TEXT NULL,
    `smtpPort` INTEGER NULL,
    `smtpSecurity` TEXT NULL,
    `smtpUsername` TEXT NULL,
    `messageId` TEXT NULL,
    `status` TEXT NOT NULL DEFAULT 'queued',
    `attemptCount` INTEGER NOT NULL DEFAULT 0,
    `nextAttemptAt` TEXT NULL,
    `errorMessage` TEXT NULL,
    `startedAt` TEXT NULL,
    `sentAt` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`workId`) REFERENCES `LibraryWork`(`id`) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (`editionId`) REFERENCES `LibraryEdition`(`id`) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (`volumeId`) REFERENCES `LibraryVolume`(`id`) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (`fileId`) REFERENCES `LibraryFile`(`id`) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `ImportTask` (
    `id` TEXT NOT NULL,
    `monitorFolderId` TEXT NULL,
    `workId` TEXT NULL,
    `editionId` TEXT NULL,
    `volumeId` TEXT NULL,
    `origin` TEXT NOT NULL,
    `status` TEXT NOT NULL DEFAULT 'PENDING',
    `originalName` TEXT NULL,
    `requestedTitle` TEXT NULL,
    `requestedAuthor` TEXT NULL,
    `sourcePath` TEXT NOT NULL,
    `contentHash` TEXT NULL,
    `taskKind` TEXT NOT NULL DEFAULT 'FILE',
    `bundleKey` TEXT NULL,
    `assetCount` INTEGER NOT NULL DEFAULT 1,
    `processedAssetCount` INTEGER NOT NULL DEFAULT 0,
    `progress` INTEGER NOT NULL DEFAULT 0,
    `duplicate` INTEGER NOT NULL DEFAULT 0,
    `duration` INTEGER NOT NULL DEFAULT 0,
    `errorSummary` TEXT NULL,
    `errorCode` TEXT NULL,
    `retryable` INTEGER NOT NULL DEFAULT 0,
    `attempts` INTEGER NOT NULL DEFAULT 0,
    `leaseOwner` TEXT NULL,
    `leaseExpiresAt` TEXT NULL,
    `message` TEXT NULL,
    `startedAt` TEXT NULL,
    `finishedAt` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`monitorFolderId`) REFERENCES `MonitorFolder`(`id`) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (`workId`) REFERENCES `LibraryWork`(`id`) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (`editionId`) REFERENCES `LibraryEdition`(`id`) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (`volumeId`) REFERENCES `LibraryVolume`(`id`) ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `ImportAsset` (
    `id` TEXT NOT NULL,
    `importTaskId` TEXT NOT NULL,
    `sourcePath` TEXT NOT NULL,
    `status` TEXT NOT NULL DEFAULT 'PENDING',
    `sortOrder` INTEGER NOT NULL DEFAULT 0,
    `fileId` TEXT NULL,
    `errorCode` TEXT NULL,
    `errorSummary` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`importTaskId`) REFERENCES `ImportTask`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`fileId`) REFERENCES `LibraryFile`(`id`) ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `BookConversionTask` (
    `id` TEXT NOT NULL,
    `importTaskId` TEXT NOT NULL,
    `mode` TEXT NOT NULL DEFAULT 'AUTO',
    `sourceFormat` TEXT NOT NULL,
    `targetFormat` TEXT NOT NULL DEFAULT 'EPUB',
    `sourcePath` TEXT NOT NULL,
    `outputPath` TEXT NULL,
    `sourceHash` TEXT NULL,
    `converter` TEXT NOT NULL DEFAULT 'shuku-internal',
    `converterVersion` TEXT NULL,
    `optionsJson` TEXT NOT NULL DEFAULT '{}',
    `status` TEXT NOT NULL DEFAULT 'QUEUED',
    `progress` INTEGER NOT NULL DEFAULT 0,
    `attempts` INTEGER NOT NULL DEFAULT 0,
    `retryable` INTEGER NOT NULL DEFAULT 0,
    `errorCode` TEXT NULL,
    `errorSummary` TEXT NULL,
    `startedAt` TEXT NULL,
    `finishedAt` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE (`importTaskId`),
    FOREIGN KEY (`importTaskId`) REFERENCES `ImportTask`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `OrganizeJob` (
    `id` TEXT NOT NULL,
    `runId` TEXT NULL,
    `workId` TEXT NOT NULL,
    `editionId` TEXT NULL,
    `importTaskId` TEXT NULL,
    `trigger` TEXT NOT NULL DEFAULT 'LEGACY',
    `status` TEXT NOT NULL DEFAULT 'REVIEWING',
    `issueCodes` TEXT NOT NULL,
    `reasonCodes` TEXT NOT NULL DEFAULT '[]',
    `summary` TEXT NULL,
    `errorSummary` TEXT NULL,
    `startedAt` TEXT NULL,
    `finishedAt` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`runId`) REFERENCES `OrganizeRun`(`id`) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (`workId`) REFERENCES `LibraryWork`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`editionId`) REFERENCES `LibraryEdition`(`id`) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (`importTaskId`) REFERENCES `ImportTask`(`id`) ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `OrganizePolicy` (
    `id` TEXT NOT NULL,
    `enabled` INTEGER NOT NULL DEFAULT 0,
    `scheduleMode` TEXT NOT NULL DEFAULT 'MANUAL',
    `intervalMinutes` INTEGER NOT NULL DEFAULT 60,
    `autoRunOnNew` INTEGER NOT NULL DEFAULT 0,
    `autoRunOnNewSince` TEXT NULL,
    `rulesJson` TEXT NOT NULL DEFAULT '{}',
    `overwriteTitleAuthor` INTEGER NOT NULL DEFAULT 1,
    `lastScheduledAt` TEXT NULL,
    `nextRunAt` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`)
);

CREATE TABLE IF NOT EXISTS `OrganizeRun` (
    `id` TEXT NOT NULL,
    `trigger` TEXT NOT NULL,
    `scopeJson` TEXT NOT NULL DEFAULT '{}',
    `dedupeKey` TEXT NULL,
    `status` TEXT NOT NULL DEFAULT 'QUEUED',
    `queuedCount` INTEGER NOT NULL DEFAULT 0,
    `completedCount` INTEGER NOT NULL DEFAULT 0,
    `reviewCount` INTEGER NOT NULL DEFAULT 0,
    `failedCount` INTEGER NOT NULL DEFAULT 0,
    `startedAt` TEXT NULL,
    `finishedAt` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE (`dedupeKey`)
);

CREATE TABLE IF NOT EXISTS `MetadataLookupTask` (
    `id` TEXT NOT NULL,
    `workId` TEXT NOT NULL,
    `editionId` TEXT NULL,
    `importTaskId` TEXT NULL,
    `organizeJobId` TEXT NULL,
    `status` TEXT NOT NULL DEFAULT 'PENDING',
    `providerOrder` TEXT NOT NULL,
    `attempts` INTEGER NOT NULL DEFAULT 0,
    `nextAttemptAt` TEXT NULL,
    `resultSource` TEXT NULL,
    `candidateRawJson` TEXT NULL,
    `appliedFields` TEXT NULL,
    `errorSummary` TEXT NULL,
    `startedAt` TEXT NULL,
    `finishedAt` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`workId`) REFERENCES `LibraryWork`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`editionId`) REFERENCES `LibraryEdition`(`id`) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (`importTaskId`) REFERENCES `ImportTask`(`id`) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (`organizeJobId`) REFERENCES `OrganizeJob`(`id`) ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `MetadataProviderExecution` (
    `id` TEXT NOT NULL,
    `jobId` TEXT NULL,
    `lookupTaskId` TEXT NULL,
    `providerId` TEXT NOT NULL,
    `status` TEXT NOT NULL DEFAULT 'PENDING',
    `attempts` INTEGER NOT NULL DEFAULT 0,
    `rawResultJson` TEXT NULL,
    `errorSummary` TEXT NULL,
    `startedAt` TEXT NULL,
    `finishedAt` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`jobId`) REFERENCES `OrganizeJob`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`lookupTaskId`) REFERENCES `MetadataLookupTask`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `MetadataProviderPipeline` (
    `workType` TEXT NOT NULL,
    `providerId` TEXT NOT NULL,
    `included` INTEGER NOT NULL DEFAULT 1,
    `enabled` INTEGER NOT NULL DEFAULT 0,
    `position` INTEGER NOT NULL DEFAULT 100,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`workType`, `providerId`)
);

CREATE TABLE IF NOT EXISTS `MetadataSuggestion` (
    `id` TEXT NOT NULL,
    `jobId` TEXT NOT NULL,
    `field` TEXT NOT NULL,
    `currentValue` TEXT NULL,
    `suggestedValue` TEXT NOT NULL,
    `source` TEXT NOT NULL,
    `confidence` REAL NOT NULL DEFAULT 0,
    `reason` TEXT NOT NULL,
    `status` TEXT NOT NULL DEFAULT 'PENDING',
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`jobId`) REFERENCES `OrganizeJob`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `DuplicateCandidate` (
    `id` TEXT NOT NULL,
    `jobId` TEXT NOT NULL,
    `targetWorkId` TEXT NOT NULL,
    `reasons` TEXT NOT NULL,
    `confidence` REAL NOT NULL DEFAULT 0,
    `suggestedAction` TEXT NOT NULL,
    `status` TEXT NOT NULL DEFAULT 'PENDING',
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`jobId`) REFERENCES `OrganizeJob`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`targetWorkId`) REFERENCES `LibraryWork`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `ImportLog` (
    `id` TEXT NOT NULL,
    `importTaskId` TEXT NOT NULL,
    `level` TEXT NOT NULL DEFAULT 'info',
    `message` TEXT NOT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`importTaskId`) REFERENCES `ImportTask`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `SystemEvent` (
    `id` TEXT NOT NULL,
    `level` TEXT NOT NULL DEFAULT 'info',
    `source` TEXT NOT NULL,
    `actorType` TEXT NOT NULL DEFAULT 'system',
    `actorId` TEXT NULL,
    `action` TEXT NOT NULL,
    `targetType` TEXT NULL,
    `targetId` TEXT NULL,
    `message` TEXT NOT NULL,
    `metadata` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`)
);

CREATE TABLE IF NOT EXISTS `SystemHealthRun` (
    `id` TEXT NOT NULL,
    `actorUserId` TEXT NOT NULL,
    `status` TEXT NOT NULL DEFAULT 'running',
    `version` INTEGER NOT NULL DEFAULT 1,
    `snapshot` TEXT NOT NULL,
    `startedAt` TEXT NOT NULL,
    `finishedAt` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`)
);

CREATE TABLE IF NOT EXISTS `QueueRuntimeState` (
    `queueName` TEXT NOT NULL,
    `instanceId` TEXT NOT NULL,
    `status` TEXT NOT NULL,
    `pollIntervalSeconds` REAL NOT NULL,
    `startedAt` TEXT NOT NULL,
    `heartbeatAt` TEXT NOT NULL,
    `lastProcessedAt` TEXT NULL,
    `lastError` TEXT NULL,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`queueName`)
);

CREATE TABLE IF NOT EXISTS `QueueControlOperation` (
    `id` TEXT NOT NULL,
    `queueName` TEXT NOT NULL,
    `action` TEXT NOT NULL,
    `status` TEXT NOT NULL,
    `actorUserId` TEXT NOT NULL,
    `messageCode` TEXT NULL,
    `requestedAt` TEXT NOT NULL,
    `startedAt` TEXT NULL,
    `finishedAt` TEXT NULL,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`)
);
CREATE INDEX IF NOT EXISTS `QueueControlOperation_queue_status_idx`
    ON `QueueControlOperation`(`queueName`, `status`, `requestedAt`);

CREATE TABLE IF NOT EXISTS `ReaderPreference` (
    `id` TEXT NOT NULL,
    `userId` TEXT NOT NULL,
    `readerType` TEXT NOT NULL,
    `settings` TEXT NOT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `ReaderBookPreference` (
    `id` TEXT NOT NULL,
    `userId` TEXT NOT NULL,
    `workId` TEXT NOT NULL,
    `schemaVersion` INTEGER NOT NULL DEFAULT 3,
    `preferences` TEXT NOT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`workId`) REFERENCES `LibraryWork`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `ReaderProgressCursor` (
    `id` TEXT NOT NULL,
    `userId` TEXT NOT NULL,
    `workId` TEXT NOT NULL,
    `clientId` TEXT NOT NULL,
    `highWater` INTEGER NOT NULL DEFAULT -1,
    `lastMutationId` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`workId`) REFERENCES `LibraryWork`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `SystemSetting` (
    `key` TEXT NOT NULL,
    `value` TEXT NOT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`key`)
);

CREATE TABLE IF NOT EXISTS `ExternalMetadataCache` (
    `id` TEXT NOT NULL,
    `provider` TEXT NOT NULL,
    `queryKey` TEXT NOT NULL,
    `rawJson` TEXT NOT NULL,
    `expiresAt` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`)
);

CREATE TABLE IF NOT EXISTS `BookIdentityCache` (
    `logicalPath` TEXT NOT NULL,
    `title` TEXT NOT NULL,
    `author` TEXT NOT NULL,
    `volumeIndex` REAL NULL,
    `source` TEXT NOT NULL,
    `confidence` REAL NOT NULL,
    `parserVersion` INTEGER NOT NULL,
    `rawJson` TEXT NOT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`logicalPath`)
);

CREATE TABLE IF NOT EXISTS `Shelf` (
    `id` TEXT NOT NULL,
    `ownerUserId` TEXT NULL,
    `name` TEXT NOT NULL,
    `description` TEXT NULL,
    `kind` TEXT NOT NULL DEFAULT 'STATIC',
    `rulesJson` TEXT NOT NULL DEFAULT '{}',
    `pinned` INTEGER NOT NULL DEFAULT 0,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`ownerUserId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `ShelfWork` (
    `shelfId` TEXT NOT NULL,
    `workId` TEXT NOT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`shelfId`, `workId`),
    FOREIGN KEY (`shelfId`) REFERENCES `Shelf`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`workId`) REFERENCES `LibraryWork`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `LibraryFacet` (
    `id` TEXT NOT NULL,
    `kind` TEXT NOT NULL,
    `name` TEXT NOT NULL,
    `normalizedName` TEXT NOT NULL,
    `aliases` TEXT NOT NULL DEFAULT '[]',
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE (`kind`, `normalizedName`)
);

CREATE TABLE IF NOT EXISTS `LibraryWorkFacet` (
    `facetId` TEXT NOT NULL,
    `workId` TEXT NOT NULL,
    `sortOrder` INTEGER NOT NULL DEFAULT 0,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`facetId`, `workId`),
    FOREIGN KEY (`facetId`) REFERENCES `LibraryFacet`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`workId`) REFERENCES `LibraryWork`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `LibraryEditionFacet` (
    `facetId` TEXT NOT NULL,
    `editionId` TEXT NOT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`facetId`, `editionId`),
    FOREIGN KEY (`facetId`) REFERENCES `LibraryFacet`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`editionId`) REFERENCES `LibraryEdition`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `LibraryOperation` (
    `id` TEXT NOT NULL,
    `userId` TEXT NULL,
    `action` TEXT NOT NULL,
    `status` TEXT NOT NULL DEFAULT 'COMPLETED',
    `targetType` TEXT NULL,
    `targetId` TEXT NULL,
    `summary` TEXT NOT NULL,
    `payloadJson` TEXT NOT NULL DEFAULT '{}',
    `inverseJson` TEXT NOT NULL DEFAULT '{}',
    `expiresAt` TEXT NULL,
    `undoneAt` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `LibraryReadingUnit` (
    `id` TEXT NOT NULL,
    `editionId` TEXT NOT NULL,
    `volumeId` TEXT NULL,
    `fileId` TEXT NULL,
    `unitType` TEXT NOT NULL,
    `title` TEXT NOT NULL,
    `href` TEXT NOT NULL,
    `mediaType` TEXT NULL,
    `sortOrder` INTEGER NOT NULL,
    `width` INTEGER NULL,
    `height` INTEGER NULL,
    `size` INTEGER NULL,
    `startMs` INTEGER NULL,
    `endMs` INTEGER NULL,
    `durationMs` INTEGER NULL,
    `metadataJson` TEXT NOT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`editionId`) REFERENCES `LibraryEdition`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`volumeId`) REFERENCES `LibraryVolume`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`fileId`) REFERENCES `LibraryFile`(`id`) ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `LibraryMetadata` (
    `id` TEXT NOT NULL,
    `editionId` TEXT NOT NULL,
    `source` TEXT NOT NULL,
    `rawJson` TEXT NOT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`editionId`) REFERENCES `LibraryEdition`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `LibraryReadingProgress` (
    `id` TEXT NOT NULL,
    `userId` TEXT NOT NULL,
    `workId` TEXT NOT NULL,
    `editionId` TEXT NOT NULL,
    `volumeId` TEXT NULL,
    `readerType` TEXT NOT NULL,
    `position` TEXT NOT NULL DEFAULT '0',
    `page` INTEGER NULL,
    `percent` REAL NOT NULL DEFAULT 0,
    `extra` TEXT NOT NULL,
    `schemaVersion` INTEGER NOT NULL DEFAULT 1,
    `locationType` TEXT NULL,
    `locationJson` TEXT NULL,
    `contentFingerprint` TEXT NULL,
    `mutationId` TEXT NULL,
    `clientId` TEXT NULL,
    `clientSequence` INTEGER NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`workId`) REFERENCES `LibraryWork`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`editionId`) REFERENCES `LibraryEdition`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`volumeId`) REFERENCES `LibraryVolume`(`id`) ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `LibraryConsumptionState` (
    `id` TEXT NOT NULL,
    `userId` TEXT NOT NULL,
    `workId` TEXT NOT NULL,
    `mediaKind` TEXT NOT NULL,
    `status` TEXT NOT NULL DEFAULT 'UNREAD',
    `lastEditionId` TEXT NULL,
    `lastVolumeId` TEXT NULL,
    `lastUnitId` TEXT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`workId`) REFERENCES `LibraryWork`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`lastEditionId`) REFERENCES `LibraryEdition`(`id`) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (`lastVolumeId`) REFERENCES `LibraryVolume`(`id`) ON DELETE SET NULL ON UPDATE CASCADE,
    FOREIGN KEY (`lastUnitId`) REFERENCES `LibraryReadingUnit`(`id`) ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `WorkDetailPreference` (
    `id` TEXT NOT NULL,
    `userId` TEXT NOT NULL,
    `workId` TEXT NOT NULL,
    `selectedTab` TEXT NOT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`workId`) REFERENCES `LibraryWork`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS `ReaderBookmark` (
    `id` TEXT NOT NULL,
    `userId` TEXT NOT NULL,
    `workId` TEXT NOT NULL,
    `editionId` TEXT NOT NULL,
    `contentFingerprint` TEXT NOT NULL,
    `bookmarkId` TEXT NOT NULL,
    `locationJson` TEXT NOT NULL,
    `label` TEXT NOT NULL,
    `percent` REAL NOT NULL DEFAULT 0,
    `bookmarkCreatedAt` TEXT NOT NULL,
    `createdAt` TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updatedAt` TEXT NOT NULL,
    PRIMARY KEY (`id`),
    FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`workId`) REFERENCES `LibraryWork`(`id`) ON DELETE CASCADE ON UPDATE CASCADE,
    FOREIGN KEY (`editionId`) REFERENCES `LibraryEdition`(`id`) ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS `User_email_key` ON `User`(`email`);
CREATE UNIQUE INDEX IF NOT EXISTS `Session_tokenHash_key` ON `Session`(`tokenHash`);
CREATE UNIQUE INDEX IF NOT EXISTS `PasswordResetToken_tokenHash_key` ON `PasswordResetToken`(`tokenHash`);
CREATE INDEX IF NOT EXISTS `PasswordResetToken_userId_createdAt_idx` ON `PasswordResetToken`(`userId`, `createdAt`);
CREATE INDEX IF NOT EXISTS `PasswordResetToken_expiresAt_idx` ON `PasswordResetToken`(`expiresAt`);
CREATE UNIQUE INDEX IF NOT EXISTS `MonitorFolder_rootPath_key` ON `MonitorFolder`(`rootPath`);
CREATE INDEX IF NOT EXISTS `UserMonitorFolderAccess_folder_idx` ON `UserMonitorFolderAccess`(`monitorFolderId`);
CREATE INDEX IF NOT EXISTS `UserPreference_userId_idx` ON `UserPreference`(`userId`);
CREATE INDEX IF NOT EXISTS `Source_enabled_idx` ON `Source`(`enabled`);
CREATE INDEX IF NOT EXISTS `Source_kind_idx` ON `Source`(`kind`);
CREATE INDEX IF NOT EXISTS `Source_providerType_idx` ON `Source`(`providerType`);
CREATE INDEX IF NOT EXISTS `Source_priority_idx` ON `Source`(`priority`);
CREATE INDEX IF NOT EXISTS `SourceSearchRecord_sourceId_idx` ON `SourceSearchRecord`(`sourceId`);
CREATE INDEX IF NOT EXISTS `SourceSearchRecord_providerType_idx` ON `SourceSearchRecord`(`providerType`);
CREATE INDEX IF NOT EXISTS `SourceSearchRecord_status_idx` ON `SourceSearchRecord`(`status`);
CREATE INDEX IF NOT EXISTS `SourceSearchRecord_title_idx` ON `SourceSearchRecord`(`title`);
CREATE INDEX IF NOT EXISTS `SourceSearchRecord_createdAt_idx` ON `SourceSearchRecord`(`createdAt`);
CREATE UNIQUE INDEX IF NOT EXISTS `SourceSearchRecord_sourceId_externalId_key` ON `SourceSearchRecord`(`sourceId`, `externalId`);
CREATE INDEX IF NOT EXISTS `DownloadTask_sourceId_idx` ON `DownloadTask`(`sourceId`);
CREATE INDEX IF NOT EXISTS `DownloadTask_searchRecordId_idx` ON `DownloadTask`(`searchRecordId`);
CREATE INDEX IF NOT EXISTS `DownloadTask_bookId_idx` ON `DownloadTask`(`bookId`);
CREATE INDEX IF NOT EXISTS `DownloadTask_type_idx` ON `DownloadTask`(`type`);
CREATE INDEX IF NOT EXISTS `DownloadTask_status_createdAt_idx` ON `DownloadTask`(`status`, `createdAt`);
CREATE INDEX IF NOT EXISTS `LibraryWork_workType_idx` ON `LibraryWork`(`workType`);
CREATE INDEX IF NOT EXISTS `LibraryEdition_workId_mediaKind_idx` ON `LibraryEdition`(`workId`, `mediaKind`);
CREATE UNIQUE INDEX IF NOT EXISTS `LibraryEdition_workId_mediaKind_primary_key` ON `LibraryEdition`(`workId`, `mediaKind`) WHERE `primary` = 1 AND `hidden` = 0;
CREATE INDEX IF NOT EXISTS `LibraryWork_publicationStatus_idx` ON `LibraryWork`(`publicationStatus`);
CREATE INDEX IF NOT EXISTS `LibraryWork_trackingStatus_idx` ON `LibraryWork`(`trackingStatus`);
CREATE INDEX IF NOT EXISTS `LibraryWork_title_idx` ON `LibraryWork`(`title`);
CREATE INDEX IF NOT EXISTS `LibraryWork_normalizedTitle_idx` ON `LibraryWork`(`normalizedTitle`);
CREATE INDEX IF NOT EXISTS `LibraryWork_normalizedAuthor_idx` ON `LibraryWork`(`normalizedAuthor`);
CREATE INDEX IF NOT EXISTS `LibraryWork_seriesName_idx` ON `LibraryWork`(`seriesName`);
CREATE INDEX IF NOT EXISTS `LibraryWork_publishedYear_idx` ON `LibraryWork`(`publishedYear`);
CREATE INDEX IF NOT EXISTS `LibraryWork_organizeStatus_idx` ON `LibraryWork`(`organizeStatus`);
CREATE INDEX IF NOT EXISTS `LibraryWork_hidden_idx` ON `LibraryWork`(`hidden`);
CREATE INDEX IF NOT EXISTS `LibraryWork_organized_idx` ON `LibraryWork`(`organized`);
CREATE INDEX IF NOT EXISTS `LibraryWork_monitorFolderId_idx` ON `LibraryWork`(`monitorFolderId`);
CREATE INDEX IF NOT EXISTS `LibraryWork_mergeKey_idx` ON `LibraryWork`(`mergeKey`);
CREATE INDEX IF NOT EXISTS `LibraryEdition_workId_primary_idx` ON `LibraryEdition`(`workId`, `primary`);
CREATE INDEX IF NOT EXISTS `LibraryEdition_format_idx` ON `LibraryEdition`(`format`);
CREATE INDEX IF NOT EXISTS `LibraryEdition_identifier_idx` ON `LibraryEdition`(`identifier`);
CREATE INDEX IF NOT EXISTS `LibraryEdition_isbn_idx` ON `LibraryEdition`(`isbn`);
CREATE INDEX IF NOT EXISTS `LibraryEdition_sourceGroupKey_idx` ON `LibraryEdition`(`sourceGroupKey`);
CREATE INDEX IF NOT EXISTS `LibraryEdition_monitorFolderId_idx` ON `LibraryEdition`(`monitorFolderId`);
CREATE UNIQUE INDEX IF NOT EXISTS `LibraryEdition_workId_versionKey_key` ON `LibraryEdition`(`workId`, `versionKey`);
CREATE INDEX IF NOT EXISTS `LibraryVolume_editionId_sortOrder_idx` ON `LibraryVolume`(`editionId`, `sortOrder`);
CREATE INDEX IF NOT EXISTS `LibraryVolume_editionId_volumeIndex_idx` ON `LibraryVolume`(`editionId`, `volumeIndex`);
CREATE UNIQUE INDEX IF NOT EXISTS `LibraryFile_path_key` ON `LibraryFile`(`path`);
CREATE UNIQUE INDEX IF NOT EXISTS `LibraryFile_filePathHash_key` ON `LibraryFile`(`filePathHash`);
CREATE UNIQUE INDEX IF NOT EXISTS `LibraryFile_fullHash_key` ON `LibraryFile`(`fullHash`);
CREATE INDEX IF NOT EXISTS `LibraryFile_editionId_sortOrder_idx` ON `LibraryFile`(`editionId`, `sortOrder`);
CREATE INDEX IF NOT EXISTS `LibraryFile_volumeId_sortOrder_idx` ON `LibraryFile`(`volumeId`, `sortOrder`);
CREATE INDEX IF NOT EXISTS `LibraryFile_fingerprint_idx` ON `LibraryFile`(`fingerprint`);
CREATE INDEX IF NOT EXISTS `LibraryFile_fullHash_idx` ON `LibraryFile`(`fullHash`);
CREATE INDEX IF NOT EXISTS `LibraryFile_sizeBytes_mtimeMs_idx` ON `LibraryFile`(`sizeBytes`, `mtimeMs`);
CREATE INDEX IF NOT EXISTS `KindleSendTask_status_nextAttemptAt_createdAt_idx` ON `KindleSendTask`(`status`, `nextAttemptAt`, `createdAt`);
CREATE INDEX IF NOT EXISTS `KindleSendTask_workId_createdAt_idx` ON `KindleSendTask`(`workId`, `createdAt`);
CREATE INDEX IF NOT EXISTS `KindleSendTask_userId_createdAt_idx` ON `KindleSendTask`(`userId`, `createdAt`);
CREATE UNIQUE INDEX IF NOT EXISTS `KindleSendTask_active_file_recipient_key` ON `KindleSendTask`(`fileId`, `recipientEmail`) WHERE `status` IN ('queued', 'sending');
CREATE INDEX IF NOT EXISTS `ImportTask_monitorFolderId_status_idx` ON `ImportTask`(`monitorFolderId`, `status`);
CREATE INDEX IF NOT EXISTS `ImportTask_status_createdAt_idx` ON `ImportTask`(`status`, `createdAt`);
CREATE INDEX IF NOT EXISTS `ImportTask_contentHash_idx` ON `ImportTask`(`contentHash`);
CREATE INDEX IF NOT EXISTS `ImportTask_workId_idx` ON `ImportTask`(`workId`);
CREATE INDEX IF NOT EXISTS `ImportTask_editionId_idx` ON `ImportTask`(`editionId`);
CREATE INDEX IF NOT EXISTS `ImportTask_volumeId_idx` ON `ImportTask`(`volumeId`);
CREATE INDEX IF NOT EXISTS `ImportTask_status_leaseExpiresAt_idx` ON `ImportTask`(`status`, `leaseExpiresAt`);
CREATE INDEX IF NOT EXISTS `BookConversionTask_status_createdAt_idx` ON `BookConversionTask`(`status`, `createdAt`);
CREATE INDEX IF NOT EXISTS `BookConversionTask_sourceHash_idx` ON `BookConversionTask`(`sourceHash`);
CREATE INDEX IF NOT EXISTS `OrganizeJob_workId_status_idx` ON `OrganizeJob`(`workId`, `status`);
CREATE UNIQUE INDEX IF NOT EXISTS `OrganizeJob_unresolved_workId_key`
ON `OrganizeJob`(`workId`)
WHERE `status` IN ('LOOKUP_PENDING', 'PENDING', 'QUEUED', 'RUNNING', 'RETRY_WAIT', 'REVIEWING', 'FAILED');
CREATE INDEX IF NOT EXISTS `OrganizeJob_runId_status_idx` ON `OrganizeJob`(`runId`, `status`);
CREATE INDEX IF NOT EXISTS `OrganizeJob_editionId_idx` ON `OrganizeJob`(`editionId`);
CREATE INDEX IF NOT EXISTS `OrganizeJob_importTaskId_idx` ON `OrganizeJob`(`importTaskId`);
CREATE INDEX IF NOT EXISTS `OrganizeJob_status_updatedAt_idx` ON `OrganizeJob`(`status`, `updatedAt`);
CREATE INDEX IF NOT EXISTS `MetadataLookupTask_status_nextAttemptAt_idx` ON `MetadataLookupTask`(`status`, `nextAttemptAt`);
CREATE INDEX IF NOT EXISTS `MetadataLookupTask_workId_createdAt_idx` ON `MetadataLookupTask`(`workId`, `createdAt`);
CREATE UNIQUE INDEX IF NOT EXISTS `MetadataLookupTask_importTaskId_key` ON `MetadataLookupTask`(`importTaskId`);
CREATE INDEX IF NOT EXISTS `MetadataProviderExecution_jobId_status_idx` ON `MetadataProviderExecution`(`jobId`, `status`);
CREATE INDEX IF NOT EXISTS `MetadataProviderExecution_lookupTaskId_idx` ON `MetadataProviderExecution`(`lookupTaskId`);
CREATE INDEX IF NOT EXISTS `MetadataProviderPipeline_workType_position_idx` ON `MetadataProviderPipeline`(`workType`, `included`, `position`);
CREATE INDEX IF NOT EXISTS `OrganizeRun_status_createdAt_idx` ON `OrganizeRun`(`status`, `createdAt`);
CREATE INDEX IF NOT EXISTS `MetadataSuggestion_jobId_status_idx` ON `MetadataSuggestion`(`jobId`, `status`);
CREATE INDEX IF NOT EXISTS `MetadataSuggestion_field_idx` ON `MetadataSuggestion`(`field`);
CREATE INDEX IF NOT EXISTS `MetadataSuggestion_source_idx` ON `MetadataSuggestion`(`source`);
CREATE INDEX IF NOT EXISTS `DuplicateCandidate_jobId_status_idx` ON `DuplicateCandidate`(`jobId`, `status`);
CREATE INDEX IF NOT EXISTS `DuplicateCandidate_targetWorkId_idx` ON `DuplicateCandidate`(`targetWorkId`);
CREATE INDEX IF NOT EXISTS `DuplicateCandidate_suggestedAction_idx` ON `DuplicateCandidate`(`suggestedAction`);
CREATE INDEX IF NOT EXISTS `ImportLog_importTaskId_createdAt_idx` ON `ImportLog`(`importTaskId`, `createdAt`);
CREATE INDEX IF NOT EXISTS `ImportAsset_importTaskId_sortOrder_idx` ON `ImportAsset`(`importTaskId`, `sortOrder`);
CREATE UNIQUE INDEX IF NOT EXISTS `ImportAsset_importTaskId_sourcePath_key` ON `ImportAsset`(`importTaskId`, `sourcePath`);
CREATE INDEX IF NOT EXISTS `SystemEvent_level_createdAt_idx` ON `SystemEvent`(`level`, `createdAt`);
CREATE INDEX IF NOT EXISTS `SystemEvent_source_createdAt_idx` ON `SystemEvent`(`source`, `createdAt`);
CREATE INDEX IF NOT EXISTS `SystemEvent_actorType_createdAt_idx` ON `SystemEvent`(`actorType`, `createdAt`);
CREATE INDEX IF NOT EXISTS `SystemEvent_action_createdAt_idx` ON `SystemEvent`(`action`, `createdAt`);
CREATE INDEX IF NOT EXISTS `SystemEvent_targetType_targetId_idx` ON `SystemEvent`(`targetType`, `targetId`);
CREATE INDEX IF NOT EXISTS `SystemEvent_createdAt_idx` ON `SystemEvent`(`createdAt`);
CREATE INDEX IF NOT EXISTS `ReaderPreference_userId_idx` ON `ReaderPreference`(`userId`);
CREATE UNIQUE INDEX IF NOT EXISTS `ReaderPreference_userId_readerType_key` ON `ReaderPreference`(`userId`, `readerType`);
CREATE INDEX IF NOT EXISTS `ReaderBookPreference_userId_idx` ON `ReaderBookPreference`(`userId`);
CREATE INDEX IF NOT EXISTS `ReaderBookPreference_workId_idx` ON `ReaderBookPreference`(`workId`);
CREATE UNIQUE INDEX IF NOT EXISTS `ReaderBookPreference_userId_workId_key` ON `ReaderBookPreference`(`userId`, `workId`);
CREATE INDEX IF NOT EXISTS `ReaderProgressCursor_userId_idx` ON `ReaderProgressCursor`(`userId`);
CREATE INDEX IF NOT EXISTS `ReaderProgressCursor_workId_idx` ON `ReaderProgressCursor`(`workId`);
CREATE UNIQUE INDEX IF NOT EXISTS `ReaderProgressCursor_userId_workId_clientId_key` ON `ReaderProgressCursor`(`userId`, `workId`, `clientId`);
CREATE INDEX IF NOT EXISTS `ExternalMetadataCache_provider_expiresAt_idx` ON `ExternalMetadataCache`(`provider`, `expiresAt`);
CREATE UNIQUE INDEX IF NOT EXISTS `ExternalMetadataCache_provider_queryKey_key` ON `ExternalMetadataCache`(`provider`, `queryKey`);
CREATE INDEX IF NOT EXISTS `BookIdentityCache_parserVersion_idx` ON `BookIdentityCache`(`parserVersion`);
CREATE INDEX IF NOT EXISTS `Shelf_updatedAt_idx` ON `Shelf`(`updatedAt`);
CREATE INDEX IF NOT EXISTS `Shelf_kind_updatedAt_idx` ON `Shelf`(`kind`, `updatedAt`);
CREATE INDEX IF NOT EXISTS `Shelf_ownerUserId_updatedAt_idx` ON `Shelf`(`ownerUserId`, `updatedAt`);
CREATE INDEX IF NOT EXISTS `ShelfWork_workId_idx` ON `ShelfWork`(`workId`);
CREATE INDEX IF NOT EXISTS `ShelfWork_shelfId_createdAt_idx` ON `ShelfWork`(`shelfId`, `createdAt`);
CREATE INDEX IF NOT EXISTS `LibraryFacet_kind_name_idx` ON `LibraryFacet`(`kind`, `name`);
CREATE INDEX IF NOT EXISTS `LibraryWorkFacet_workId_idx` ON `LibraryWorkFacet`(`workId`);
CREATE INDEX IF NOT EXISTS `LibraryEditionFacet_editionId_idx` ON `LibraryEditionFacet`(`editionId`);
CREATE INDEX IF NOT EXISTS `LibraryOperation_action_createdAt_idx` ON `LibraryOperation`(`action`, `createdAt`);
CREATE INDEX IF NOT EXISTS `LibraryOperation_status_expiresAt_idx` ON `LibraryOperation`(`status`, `expiresAt`);
CREATE INDEX IF NOT EXISTS `ImportTask_createdAt_id_idx` ON `ImportTask`(`createdAt`, `id`);
CREATE INDEX IF NOT EXISTS `LibraryWork_createdAt_id_idx` ON `LibraryWork`(`createdAt`, `id`);
CREATE INDEX IF NOT EXISTS `LibraryReadingUnit_editionId_sortOrder_idx` ON `LibraryReadingUnit`(`editionId`, `sortOrder`);
CREATE INDEX IF NOT EXISTS `LibraryReadingUnit_editionId_unitType_idx` ON `LibraryReadingUnit`(`editionId`, `unitType`);
CREATE INDEX IF NOT EXISTS `LibraryReadingUnit_volumeId_sortOrder_idx` ON `LibraryReadingUnit`(`volumeId`, `sortOrder`);
CREATE INDEX IF NOT EXISTS `LibraryReadingUnit_fileId_sortOrder_idx` ON `LibraryReadingUnit`(`fileId`, `sortOrder`);
CREATE UNIQUE INDEX IF NOT EXISTS `LibraryReadingUnit_volumeId_unitType_sortOrder_key` ON `LibraryReadingUnit`(`volumeId`, `unitType`, `sortOrder`);
CREATE INDEX IF NOT EXISTS `LibraryMetadata_editionId_idx` ON `LibraryMetadata`(`editionId`);
CREATE INDEX IF NOT EXISTS `LibraryReadingProgress_workId_idx` ON `LibraryReadingProgress`(`workId`);
CREATE INDEX IF NOT EXISTS `LibraryReadingProgress_editionId_idx` ON `LibraryReadingProgress`(`editionId`);
CREATE INDEX IF NOT EXISTS `LibraryReadingProgress_volumeId_idx` ON `LibraryReadingProgress`(`volumeId`);
CREATE INDEX IF NOT EXISTS `LibraryReadingProgress_clientId_clientSequence_idx` ON `LibraryReadingProgress`(`clientId`, `clientSequence`);
CREATE UNIQUE INDEX IF NOT EXISTS `LibraryReadingProgress_userId_editionId_volumeId_key` ON `LibraryReadingProgress`(`userId`, `editionId`, `volumeId`);
CREATE INDEX IF NOT EXISTS `LibraryConsumptionState_workId_idx` ON `LibraryConsumptionState`(`workId`);
CREATE UNIQUE INDEX IF NOT EXISTS `LibraryConsumptionState_user_work_media_key` ON `LibraryConsumptionState`(`userId`, `workId`, `mediaKind`);
CREATE UNIQUE INDEX IF NOT EXISTS `WorkDetailPreference_user_work_key` ON `WorkDetailPreference`(`userId`, `workId`);
CREATE INDEX IF NOT EXISTS `ReaderBookmark_user_edition_idx` ON `ReaderBookmark`(`userId`, `editionId`);
CREATE UNIQUE INDEX IF NOT EXISTS `ReaderBookmark_user_edition_fingerprint_bookmark_key`
ON `ReaderBookmark`(`userId`, `editionId`, `contentFingerprint`, `bookmarkId`);

PRAGMA user_version = 14;
