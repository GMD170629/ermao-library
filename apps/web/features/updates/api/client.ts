import { parseReleaseFeed } from '../model/release-notes';
import { requestUpdate } from './operations';

export async function fetchReleaseFeed(signal?: AbortSignal) {
  return parseReleaseFeed(await requestUpdate('releases', signal));
}

export async function fetchReleaseNote(notesPath: string, signal?: AbortSignal) {
  if (!/^v\d+\.\d+\.\d+\.md$/u.test(notesPath)) throw new Error('更新说明路径无效');
  const result = await requestUpdate('releases/' + notesPath.slice(1, -3) + '/notes', signal);
  if (typeof result !== 'object' || result === null || !('markdown' in result) || typeof result.markdown !== 'string') {
    throw new Error('暂时无法读取更新说明');
  }
  return result.markdown;
}
