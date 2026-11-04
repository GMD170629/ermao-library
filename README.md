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

From v1.4.2 onward, write each locale in this order. Omit any section
with no actual item, including Notes when no user action is required:

```markdown
<!-- shuku:locale=zh-CN:start -->
## 新增：

1. 具体新增内容。

## 修复：

1. 具体修复内容。

## 注意事项：

1. 仅填写用户必须采取的具体操作或直接影响使用的事项。
<!-- shuku:locale=zh-CN:end -->

<!-- shuku:locale=en-US:start -->
## Added:

1. A specific user-visible addition.

## Fixed:

1. A specific user-visible fix.

## Notes:

1. A concrete action required of users or a direct impact on use.
<!-- shuku:locale=en-US:end -->
```

Release notes describe user-visible changes. Do not explain routine database
migrations, online-update support, container/image implementation, dependency
packaging, or backup and rollback mechanics. Keep those details in internal
release documentation. If an exceptional release requires users to take an
upgrade action, state only that action in plain language under Notes; otherwise
omit Notes. Published historical notes are left intact.

Run `pnpm release:validate` before creating the matching `vMAJOR.MINOR.PATCH`
tag. GitHub Actions publishes the exact Markdown file as the Release body and
only then updates the public `release-feed` branch.

Stable releases start once from the version tag, after `main` and `develop` have
been synchronized to that exact commit. The release workflow reuses the same
validated artifacts for publication. Android is included only when explicitly
selected for that release.

If publication fails after a successful build, rerun only the failed publication
job. Do not rerun all jobs or move a published tag. Synchronize post-release note
edits to both branches by fast-forwarding; avoid reciprocal merge commits.
