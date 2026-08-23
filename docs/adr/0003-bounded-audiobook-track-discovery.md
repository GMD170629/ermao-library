# ADR 0003: Bounded audiobook track discovery

## Status

Accepted; constrained by [ADR 0017](0017-library-root-directory-topology.md)

## Context

An audiobook Work may contain tracks directly in its directory or in immediate
Volume directories. Building a complete track list before enforcing a limit
makes memory proportional to the source directory.

## Decision

One audiobook Work directory may contain at most 10,000 tracks across all of
its Volumes. Directory scanning enumerates tracks with `os.scandir()` inside
the existing 5,000-entry and 250-millisecond scan slices. It retains only a
counter and the bounded iterator stack. Root-level audio files are independent
single-file Works and are not grouped by filename.

An oversized audiobook produces one scan error with the stable code
`AUDIO_TRACK_LIMIT_EXCEEDED`. It creates no import task or work item. Supported
audio candidates from other Work directories continue through normal discovery.
The scanner submits the Work directory once; ADR 0017 interprets every immediate
child directory as a Volume without title, author, disc, or volume-number heuristics.

## Consequences

Memory remains bounded independently of the number of audio files. A scan may
read the rest of an oversized directory to report the observed count, but it
continues yielding between slices. The scanner does not revalidate or delete
previous rows. Users must split oversized sources into separate Work directories
before scanning them.
