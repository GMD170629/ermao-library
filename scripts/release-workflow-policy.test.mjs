import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const releaseWorkflow = readFileSync('.github/workflows/fnos-package.yml', 'utf8');
const maintenanceWorkflow = readFileSync('.github/workflows/sync-release-notes.yml', 'utf8');
const dockerPublisher = readFileSync('scripts/publish-docker-hub.sh', 'utf8');

test('formal publishing has no generated-note or manual-release bypass', () => {
  assert.doesNotMatch(releaseWorkflow, /--generate-notes/u);
  assert.doesNotMatch(releaseWorkflow, /publish_release/u);
  assert.match(releaseWorkflow, /if: github\.ref_type == 'tag'/u);
  assert.match(releaseWorkflow, /node scripts\/validate-release-notes\.mjs --tag/u);
});

test('Draft Release publication and release-feed updates have a strict order', () => {
  const draft = releaseWorkflow.indexOf('Prepare strict bilingual Draft Release');
  const upload = releaseWorkflow.indexOf('Upload fnOS package to Draft Release');
  const publish = releaseWorkflow.indexOf('Verify and publish strict bilingual Release');
  const feed = releaseWorkflow.indexOf('Publish verified release feed');
  assert.ok(draft >= 0 && draft < upload);
  assert.ok(upload < publish);
  assert.ok(publish < feed);
  assert.match(releaseWorkflow, /gh release edit "\$RELEASE_TAG" --draft=false/u);
  assert.match(releaseWorkflow, /Release body differs from the authoritative bilingual release note/u);
});

test('maintenance synchronization edits published history but cannot create or publish Releases', () => {
  assert.doesNotMatch(maintenanceWorkflow, /gh release create/u);
  assert.doesNotMatch(maintenanceWorkflow, /--draft=false/u);
  assert.match(maintenanceWorkflow, /if \[\[ "\$is_draft" != 'false' \]\]/u);
  assert.match(maintenanceWorkflow, /gh release edit "\$release_tag".*--notes-file/u);
  assert.match(maintenanceWorkflow, /release-feed/u);
});

test('the standalone Docker publisher always validates release metadata', () => {
  assert.match(dockerPublisher, /pnpm release:validate/u);
  assert.match(dockerPublisher, /VERSION_TAG.*v\$\{APP_VERSION\}/u);
});
