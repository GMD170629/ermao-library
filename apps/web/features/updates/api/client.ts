import { parseReleaseFeed } from '../model/release-notes';

const releaseFeedRoot = 'https://raw.githubusercontent.com/GMD170629/ermao-library/release-feed';

function cacheBuster() {
  return `t=${Date.now()}`;
}

export async function fetchReleaseFeed(signal?: AbortSignal) {
  const response = await fetch(`${releaseFeedRoot}/index.json?${cacheBuster()}`, {
    cache: 'no-store',
    signal
  });
  if (!response.ok) throw new Error('暂时无法检查更新');
  const payload: unknown = await response.json();
  return parseReleaseFeed(payload);
}

export async function fetchReleaseNote(notesPath: string, signal?: AbortSignal) {
  if (!/^v\d+\.\d+\.\d+\.md$/u.test(notesPath)) throw new Error('更新说明路径无效');
  const response = await fetch(`${releaseFeedRoot}/${encodeURIComponent(notesPath)}?${cacheBuster()}`, {
    cache: 'no-store',
    signal
  });
  if (!response.ok) throw new Error('暂时无法读取更新说明');
  return response.text();
}
