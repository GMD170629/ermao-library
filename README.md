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
