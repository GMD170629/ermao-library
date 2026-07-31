# ADR 0003: Bounded audiobook track discovery

## Status

Accepted

## Context

An audiobook may contain tracks directly in its book directory, in CD/Disc
subdirectories, or across multiple volume directories. Building a complete
track list before enforcing a limit makes memory proportional to the source
directory and can turn an oversized audiobook into thousands of independent
import tasks.

## Decision

One logical audiobook may contain at most 10,000 tracks across all of its
volumes and disc directories. Directory scanning enumerates tracks with
`os.scandir()` inside the existing 5,000-entry and 250-millisecond scan slices.
It retains at most 10,000 paths. On the 10,001st track it discards the buffered
paths, continues counting without retaining them, and suppresses every audio
candidate in that logical directory.

An oversized audiobook produces one scan error with the stable code
`AUDIO_TRACK_LIMIT_EXCEEDED`. It creates no import task or work item. Supported
non-audio files in the same directory continue through normal discovery.
Watcher audio events debounce into one delayed directory scan so the same
bounded discovery path owns grouping and limit enforcement.

## Consequences

Memory remains bounded independently of the number of audio files. A scan may
read the rest of an oversized directory to report the observed count and find
non-audio books, but it continues yielding between slices. Existing imported
audiobooks are not revalidated or deleted. Users must split oversized sources
into separate logical book or volume directories before importing them.
