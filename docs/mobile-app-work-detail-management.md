# Mobile Book Detail Management Status

This document supersedes ADR 0020 only for native book-detail management scope.

Native book-detail administration is enabled for authorized system managers.
`/api/mobile/compatibility` publishes `bookDetailManagement=true`; Android and iOS
must additionally require `canManageSystem` before exposing management commands.
Global governance and unrelated batch administration remain Web-only.

The shared management adapter owns current Book/Resource/Asset request models. It
remains capability-gated and must not restore any
Work/Version/Volume/File route or compatibility mapping. Shelf membership, Reader
reading status, managed offline downloads, and Kindle sending are independent user
flows; they continue to use their current Book/Resource/Asset contracts where the
native UI already supports them.

The enabled surface is limited to metadata editing, cover regeneration, metadata
recognition, source-node rescan, permanent source deletion, and book-level reading
status. Release acceptance requires physical-device evidence for Android and iOS.
