# Shuku Starship release notes

This directory is the authoritative source for both the in-app update history and
GitHub Release descriptions.

Every stable release must be listed in `index.json` and have one Markdown file.
The locale markers are part of the public contract and must not be renamed:

```markdown
<!-- shuku:locale=zh-CN:start -->
## 简体中文

...
<!-- shuku:locale=zh-CN:end -->

<!-- shuku:locale=en-US:start -->
## English

...
<!-- shuku:locale=en-US:end -->
```

Run `pnpm release:validate` before creating the matching `vMAJOR.MINOR.PATCH`
tag. GitHub Actions publishes the exact Markdown file as the Release body and
only then updates the public `release-feed` branch.

Stable releases start once from the version tag, after `main` and `develop` have
been synchronized to that exact commit. Do not run a candidate build on `main`.
The build uploads the final signed bundle as a run artifact. For mobile releases,
download that bundle, complete physical-device acceptance, and approve the
`stable-release` environment in the same run. Configure its required reviewer in
repository Settings → Environments before releasing; preflight rejects a missing
gate. Approval releases the original artifact and promotes the original Docker
digest without rebuilding. The owner-approved v1.0.3 and v1.0.4 releases are server-only exceptions.

If publication fails after a successful build, rerun only the failed publication
job. Do not rerun all jobs or move a published tag. Synchronize post-release note
edits to both branches by fast-forwarding; avoid reciprocal merge commits.
