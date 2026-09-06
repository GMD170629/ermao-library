# ADR 0003: Bounded audiobook track discovery

Status: Accepted; directory ownership is defined by [ADR 0022](0022-audiobook-directory-resource-boundaries.md)

## Decision

Audiobooks are resource adapters inside the `FLAT`/`VOLUMES` library modes. They
are not a third organization mode. An audiobook-directory resource owns its direct
audio files and descendants through the transparent directory names defined by
ADR 0022 (`CD`, `Disc`, `Disk`, `碟`, `盘`, with an optional numeric suffix).
Other child directories remain independent source-tree resources.

Discovery uses the existing bounded filesystem scan and the generated
safety-contract budget `audioTrackMaxCount`; this ADR does not add a second
hard-coded policy. The backend uses `app/services/audio_metadata.py` and the
generated `AUDIO.TRACK_AND_CHAPTER_BOUNDS` rule. The resulting stable generated
error outcome is returned for an oversized input and no new asset is created for
the rejected track.

Single audio files use the normal audio adapter and are not grouped by filename.
Track metadata and chapter limits remain separate concerns owned by the generated
Reader safety contract in `packages/reader-contracts/reader-safety-policy.json`.

## Consequences

Memory remains bounded by the scan budget rather than the total number of tracks.
Supported resources from other source directories continue to import when one
directory exceeds the limit. The scanner does not introduce a second queue,
organization mode or heuristic volume model.
