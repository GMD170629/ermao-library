# Server-owned account avatar

Date: 2026-09-09

## Decision

Authentication responses provide `avatarImageUrl` for display. Nullable `avatarUrl`
continues to identify a custom upload, preserving upload/delete affordances and
existing consumers. The display field is resolved by the authentication response
schema for setup, login, session reads and account mutations.

Authenticated GET `/api/auth/avatar` serves the uploaded image, or the server's
bundled default if no usable upload exists. The default is a lossless WebP of the
previous Web brand icon, packaged with the backend; clients do not generate or
choose default artwork. Delivery uses `private, no-cache` to revalidate account
image changes. The same bounded filesystem adapter resolves upload cleanup,
deletion and delivery paths. The read use case performs no writes.

Web's account-avatar public component owns all three account image entry points.
KMP personal-settings wire mapping carries the display address to Android and
iOS. Native views render fetched bytes. Missing/failed responses leave an empty
image slot; local initials, BrandMark and pending-upload substitutions are removed.
Old servers without the additive field can only display their existing custom URL.

## Verification and rollout

API contract tests cover default delivery, upload, deletion, reopening, missing
files and paths outside storage. KMP tests distinguish default display from custom
upload ownership. Android view-model and physical-device rendering tests cover
response bytes and forbidden local substitutions. Web tests render the shared
component. iOS test coverage is added but requires macOS/device execution.

Deploy the backend with the updated clients to obtain default images. Pushing
source does not update an already running NAS backend.
