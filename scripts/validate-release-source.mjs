import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

export function isFormalRelease({ eventName, refType, refName }) {
  if (eventName === 'pull_request') return false;
  if (refType === 'tag' && /^v\d+\.\d+\.\d+$/.test(refName)) return true;
  if (refType === 'branch' && ['develop', 'prod'].includes(refName)) return false;
  throw Error('Stable releases build once from a version tag; main candidate builds are disabled.');
}

export function validateReleaseSource({ sha, mainSha, developSha, tag, version, release, environment }) {
  if (!/^[a-f0-9]{40}$/.test(sha) || mainSha !== sha || developSha !== sha) {
    throw Error('Before tagging, fast-forward main and develop to the same release commit.');
  }
  if (tag !== `v${version}`) throw Error('Release tag does not match the application version.');
  if (release && !release.draft) throw Error('This release is already published; do not rebuild or replace its artifacts.');
  if (!['1.0.3', '1.0.4', '1.1.0'].includes(version) && !environment?.protection_rules?.some(rule =>
    rule.type === 'required_reviewers' && rule.reviewers?.length > 0)) {
    throw Error('Configure required reviewers on the stable-release environment before building mobile release artifacts.');
  }
}

function command(program, args) {
  return execFileSync(program, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}

function optionalGitHubResource(path) {
  try {
    return JSON.parse(command('gh', ['api', path]));
  } catch (error) {
    if (String(error.stderr).includes('(HTTP 404)')) return null;
    throw error;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const { GITHUB_EVENT_NAME: eventName, GITHUB_REF_TYPE: refType, GITHUB_REF_NAME: refName,
    GITHUB_SHA: sha, GITHUB_REPOSITORY: repository } = process.env;
  if (isFormalRelease({ eventName, refType, refName })) {
    command('git', ['fetch', 'origin', '+refs/heads/main:refs/remotes/origin/main',
      '+refs/heads/develop:refs/remotes/origin/develop']);
    const version = JSON.parse(readFileSync('package.json', 'utf8')).version;
    validateReleaseSource({
      sha, tag: refName, version,
      mainSha: command('git', ['rev-parse', 'origin/main']),
      developSha: command('git', ['rev-parse', 'origin/develop']),
      release: optionalGitHubResource(`repos/${repository}/releases/tags/${refName}`),
      environment: ['1.0.3', '1.0.4', '1.1.0'].includes(version) ? null : optionalGitHubResource(`repos/${repository}/environments/stable-release`),
    });
  }
  console.log('Release entry point and source verified.');
}
