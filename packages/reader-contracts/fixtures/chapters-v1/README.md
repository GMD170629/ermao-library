# Chapter core fixtures v1

The `manifest.json` file is a format-neutral conformance fixture for the native
chapter core. It describes the already parsed input that adapters pass to the C
ABI. XML fixtures use `start`, `text`, and `end` events; `name` and attribute
names are local names, and `targetHref` is already validated and resolved by
the adapter. MOBI fixtures use the source node index as `parentIndex`.

The expected `entries` array is the public result order. `index` and `key` are
zero-based final preorder values, while `parentIndex` refers to that same
final array. `sourceStart` is a normalized UTF-8 byte offset for TXT and a
zero-based start-element ordinal for XML. A missing `href` means the entry is
a non-clickable group. These fixtures do not define parser, archive, or
safety budgets.
