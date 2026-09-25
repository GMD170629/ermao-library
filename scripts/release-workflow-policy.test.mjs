import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const releaseWorkflow = readFileSync('.github/workflows/fnos-package.yml', 'utf8');
const maintenanceWorkflow = readFileSync('.github/workflows/sync-release-notes.yml', 'utf8');
const dockerPublisher = readFileSync('scripts/publish-docker-hub.sh', 'utf8');
const unifiedAppStartup = readFileSync('scripts/start-unified-app.sh', 'utf8');
const job = name => releaseWorkflow.split(`\n  ${name}:`)[1].split(/\n  [a-z][\w-]*:/)[0];
const gitAttributes = readFileSync('.gitattributes', 'utf8');

test('repository text normalization protects container entrypoints', () => {
  assert.doesNotMatch(unifiedAppStartup, /\r/u);
  assert.match(gitAttributes, /^\* text=auto eol=lf$/mu);
});

test('formal publishing has no generated-note or manual-release bypass', () => {
  assert.doesNotMatch(releaseWorkflow, /--generate-notes/u);
  assert.doesNotMatch(releaseWorkflow, /publish_release/u);
  assert.match(releaseWorkflow, /if: github\.ref_type == 'tag'/u);
  assert.match(releaseWorkflow, /node scripts\/validate-release-notes\.mjs --tag/u);
});

test('Draft Release publication and release-feed updates have a strict order', () => {
  const draft = releaseWorkflow.indexOf('Prepare strict bilingual Draft Release');
  const upload = releaseWorkflow.indexOf('Upload complete APK and fnOS bundle to Draft Release');
  const publish = releaseWorkflow.indexOf('Verify and publish strict bilingual Release');
  const feed = releaseWorkflow.indexOf('Publish verified release feed');
  assert.ok(draft >= 0 && draft < upload);
  assert.ok(upload < publish);
  assert.ok(publish < feed);
  assert.match(releaseWorkflow, /gh release edit "\$RELEASE_TAG" --draft=false/u);
  assert.match(releaseWorkflow, /Release body differs from the authoritative bilingual release note/u);
});

test('stable releases gate selected mobile checks before image promotion', () => {
  const packageJob = releaseWorkflow.split('\n  package:')[1].split('\n  publish:')[0];
  const publishJob = releaseWorkflow.split('\n  publish:')[1];
  assert.match(job('android-package'), /needs: \[validate, mobile-release\]/);
  assert.match(releaseWorkflow, /uses: \.\/\.github\/workflows\/mobile.yml/);
  assert.match(releaseWorkflow, /run_full_android_regression: false/);
  assert.match(job('android-package'), /sign-android-apk.sh unsigned-android dist\/android stable/);
  assert.match(publishJob, /assets=\(dist\/fnos\/\*\.fpk dist\/fnos\/\*\.sha256\)/);
  assert.match(publishJob, /if \[\[ "\$BUILD_ANDROID" == 'true' \]\]/);
  const verify = publishJob.indexOf('"$RUNNER_TEMP/release-assets.json"\n');
  const promote = publishJob.indexOf('Promote verified release Docker image');
  const publish = publishJob.indexOf('Verify and publish strict bilingual Release');
  assert.ok(verify > 0 && verify < promote && promote < publish);
});

test('maintenance synchronization edits published history but cannot create or publish Releases', () => {
  assert.doesNotMatch(maintenanceWorkflow, /gh release create/u);
  assert.doesNotMatch(maintenanceWorkflow, /--draft=false/u);
  assert.doesNotMatch(maintenanceWorkflow, /<<['"]?NODE/u);
  assert.match(maintenanceWorkflow, /if \[\[ "\$is_draft" != 'false' \]\]/u);
  assert.match(maintenanceWorkflow, /gh release edit "\$release_tag".*--notes-file/u);
  assert.match(maintenanceWorkflow, /replace\(\/\\n\*\$\/, "\\n"\)/u);
  assert.match(maintenanceWorkflow, /release-feed/u);
});

test('Release body verification ignores only transport-added trailing newlines', () => {
  const strictTrailingNewlineNormalizers =
    releaseWorkflow.match(/replace\(\/\\n\*\$\/, '\\n'\)/gu) ?? [];
  assert.equal(strictTrailingNewlineNormalizers.length, 2);
});

test('the standalone Docker publisher always validates release metadata', () => {
  assert.match(dockerPublisher, /pnpm release:validate/u);
  assert.match(dockerPublisher, /VERSION_TAG.*v\$\{APP_VERSION\}/u);
});

test('develop pushes publish only the isolated develop image channel', () => {
  assert.match(releaseWorkflow, /branches:\s+- prod\s+- develop/u);
  const developJob = job('publish-develop-image');

  assert.ok(developJob, 'the develop image publishing job must exist');
  assert.match(developJob, /if: github\.ref == 'refs\/heads\/develop'/u);
  assert.match(developJob, /needs: \[validate, startup-acceptance\]/u);
  assert.match(developJob, /platforms: linux\/amd64(?:\r?\n)/u);
  assert.doesNotMatch(developJob, /linux\/arm64/u);
  assert.match(developJob, /tags: gamersgu\/shuku-starship-web:develop/u);
  assert.doesNotMatch(developJob, /shuku-starship-web:(?:prod|latest)/u);
  assert.match(job('server-package'), /needs: validate/);
  assert.match(job('server-package'), /if: github.ref_type == 'tag'/);
});

test('stable Android selection replaces historical exceptions and guards the entire APK chain', () => {
  const mobileJob = releaseWorkflow.split('\n  mobile-release:')[1].split('\n  package:')[0];
  const packageJob = releaseWorkflow.split('\n  package:')[1].split('\n  publish:')[0];
  assert.match(mobileJob, /outputs.build_android == 'true'/);
  assert.match(mobileJob, /build_android: true/);
  assert.doesNotMatch(releaseWorkflow, /1\.0\.3|1\.0\.4|1\.1\.0|1\.2\.0/);
  assert.match(packageJob, /outputs.build_android == 'false'/);
  assert.match(packageJob, /needs.mobile-release.result == 'skipped' && needs.android-package.result == 'skipped'/);
  assert.match(job('mobile-contracts'), /build_android: false/);
  assert.match(packageJob, /outputs.build_android == 'true' && needs.mobile-contracts.result == 'skipped' && needs.mobile-release.result == 'success'/);
  for (const name of ['Download checked stable Android APK', 'Set up JDK for stable signing', 'Set up Android SDK for stable signing', 'Install signing tools', 'Sign and verify stable Android APK']) {
    assert.ok(job('android-package').includes(`- name: ${name}\n        if: needs.validate.outputs.build_android == 'true'`));
  }
});

test('authorized publication uses the exact build artifact and image digest without rebuilding', () => {
  const packageJob = releaseWorkflow.split('\n  package:')[1].split('\n  publish:')[0];
  const publishJob = releaseWorkflow.split('\n  publish:')[1];
  assert.match(packageJob, /bundle_id: \$\{\{ steps.bundle.outputs.artifact-id \}\}/);
  assert.match(job('server-package'), /image_digest: \$\{\{ steps.release_image.outputs.digest \}\}/);
  assert.match(job('server-package'), /value=release-\$\{\{ github.sha \}\}-\$\{\{ github.run_id \}\}-\$\{\{ github.run_attempt \}\}/);
  assert.doesNotMatch(packageJob, /gh release (create|upload|edit)|imagetools create/);
  assert.match(publishJob, /needs: \[validate, package\]/);
  assert.match(publishJob, /!cancelled\(\) && needs.validate.result == 'success' && needs.package.result == 'success'/);
  assert.doesNotMatch(publishJob, /environment:/);
  assert.match(publishJob, /artifact-ids: \$\{\{ needs.package.outputs.bundle_id \}\}/);
  assert.match(publishJob, /merge-multiple: true/);
  assert.match(publishJob, /IMAGE_DIGEST: \$\{\{ needs.package.outputs.image_digest \}\}/);
  assert.match(publishJob, /shuku-starship-web@\$IMAGE_DIGEST/);
  assert.doesNotMatch(publishJob, /build-push-action|sign-android-apk|sdkmanager|pytest|pnpm|build-fnos-package/);
  assert.ok(publishJob.indexOf('Verify downloaded release bundle') < publishJob.indexOf('gh release upload'));
  assert.match(releaseWorkflow, /node scripts\/validate-release-source.mjs/);
  assert.match(releaseWorkflow, /cancel-in-progress: false/);
});


test('protocol 2 assets build offline per architecture before collision-checked merge', () => {
  const packaging = readFileSync(new URL('./build-release-app-packages.sh', import.meta.url), 'utf8');
  assert.match(packaging, /--network none --platform/);
  assert.match(packaging, /--python \/tmp\/package-tools\/bin\/python --no-index --no-deps --no-build/);
  assert.match(packaging, /\/tmp\/package-tools\/bin\/python \/opt\/shuku-image\/scripts\/build-application-package.py/);
  assert.match(packaging, /--dependency-seed/);
  assert.match(packaging, /--fixed-environment.*--verify/);
  assert.match(packaging, /--merge/);
  assert.ok(releaseWorkflow.indexOf('Verify and publish strict bilingual Release') < releaseWorkflow.indexOf('Publish verified release feed'));
  assert.match(maintenanceWorkflow, /assemble-release-feed.mjs/);
});


test('backend installation tests use the production uv version and report its executable', () => {
  const packageJob = job('backend-tests');
  assert.match(packageJob, /uses: astral-sh\/setup-uv@v6\n        with:\n          version: "0\.11\.29"/);
  assert.match(packageJob, /command -v uv\n          uv --version/);
  assert.match(packageJob, /uv run --extra dev --locked pytest -q/);
  assert.ok(packageJob.indexOf('uses: astral-sh/setup-uv') < packageJob.indexOf('command -v uv'));
  assert.ok(packageJob.indexOf('ctest --test-dir') < packageJob.indexOf('uv run --extra dev --locked pytest -q'));
  assert.match(packageJob, /sudo apt-get install -y ffmpeg/);
  assert.ok(packageJob.indexOf('sudo apt-get install -y ffmpeg') < packageJob.indexOf('uv run --extra dev --locked pytest -q'));
});

test('GHCR artifacts are anonymously verified before stable publication and stay out of Releases', () => {
  const publish = releaseWorkflow.split('\n  publish:')[1];
  assert.match(publish, /packages: write/);
  assert.match(publish, /version: 1\.3\.0/);
  assert.ok(publish.indexOf('node scripts/ghcr-updates.mjs') < publish.indexOf('Promote verified release Docker image'));
  assert.doesNotMatch(publish, /gh release upload[^\n]*dist\/application/);
});

test('explicit quick mode gates every image build, installer and promotion in the shared workflow', () => {
  const packageJob = releaseWorkflow.split('\n  package:')[1].split('\n  publish:')[0];
  for (const name of ['Build and push release Docker image', 'Build fnOS package', 'Hash fnOS packages', 'Accept the exact server release image before publication']) {
    assert.ok(job('server-package').includes(`- name: ${name}\n        if: needs.validate.outputs.release_mode != 'code-only'`), name);
  }
  for (const job of ['startup-acceptance', 'publish-develop-image', 'publish-prod-image', 'mobile-release']) {
    const text = releaseWorkflow.split(`\n  ${job}:`)[1].split(/\n  [a-z][\w-]*:/)[0];
    assert.match(text, /if: .*needs.validate.outputs.release_mode != 'code-only'/);
  }
  const publish = releaseWorkflow.split('\n  publish:')[1];
  assert.match(publish, /- name: Promote verified release Docker image\n        if: .*release_mode != 'code-only'/);
  assert.match(publish, /- name: Upload complete APK and fnOS bundle to Draft Release\n        if: .*release_mode != 'code-only'/);
  assert.doesNotMatch(packageJob, /accept_container_update|candidate browser|prior-application/);
  assert.match(packageJob, /Validate complete release bundle/);
});

test('system release checkout never initializes the unrelated Wiki submodule', () => {
  assert.doesNotMatch(releaseWorkflow, /submodules:|submodule update/);
  const packaging = readFileSync(new URL('./build-release-app-packages.sh', import.meta.url), 'utf8');
  assert.doesNotMatch(packaging, /--recurse-submodules/);
  assert.match(packaging, /name == 'ermao-library\.wiki'/);
});


test('server build and backend tests run independently, then require every selected result', () => {
  for (const name of ['server-package', 'backend-tests']) {
    assert.match(job(name), /needs: validate/);
    assert.doesNotMatch(job(name), /needs: \[|mobile-release|android-package/);
  }
  assert.equal((job('backend-tests').match(/uv run --extra dev --locked pytest -q/g) ?? []).length, 1);
  assert.match(job('validate'), /Verify quick-update database upgrade[\s\S]*?has_migrations == 'true'[\s\S]*?test_book_task_shape_migration\.py/u);
  assert.match(job('package'), /artifact-ids: \$\{\{ needs.server-package.outputs.artifact_id \}\}/);
  assert.match(job('package'), /artifact-ids: \$\{\{ needs.android-package.outputs.artifact_id \}\}/);
  assert.match(job('android-package'), /artifact-ids: \$\{\{ needs.mobile-release.outputs.stable_artifact_id \}\}/);
  // Evaluate the actual, bounded job condition with all Actions result states.
  const condition = job('package').match(/if: >-\s+\$\{\{([\s\S]*?)\}\}/)[1];
  const permitted = ({ android = false, mode = 'full', cancelled = false, results = {} } = {}) => {
    const needs = Object.fromEntries(['validate', 'backend-tests', 'server-package', 'mobile-contracts', 'mobile-release', 'android-package'].map(name => [name, { result: 'success' }]));
    needs.validate.outputs = { build_android: String(android), release_mode: mode };
    if (android || mode === 'code-only') needs['mobile-contracts'].result = 'skipped';
    if (!android) for (const name of ['mobile-release', 'android-package']) needs[name].result = 'skipped';
    if (mode === 'code-only') needs['backend-tests'].result = 'skipped';
    for (const [name, result] of Object.entries(results)) needs[name].result = result;
    const expression = condition.replace(/needs\.([\w-]+)/g, (_, name) => `needs[${JSON.stringify(name)}]`);
    return Function('needs', 'github', 'cancelled', `return (${expression});`)(needs, { ref_type: 'tag' }, () => cancelled);
  };
  assert.equal(permitted(), true);
  assert.equal(permitted({ android: true }), true);
  assert.equal(permitted({ mode: 'code-only' }), true);
  assert.equal(permitted({ cancelled: true }), false);
  for (const android of [false, true]) {
    for (const name of ['validate', 'backend-tests', 'server-package', ...(android ? ['mobile-release', 'android-package'] : ['mobile-contracts'])]) {
      for (const result of ['failure', 'cancelled', 'skipped']) assert.equal(permitted({ android, results: { [name]: result } }), false, `${name}: ${result}`);
    }
  }
  assert.equal(permitted({ results: { 'mobile-release': 'success' } }), false);
});
