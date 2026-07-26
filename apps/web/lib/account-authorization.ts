import type { AccountResponse } from '../generated/api-v2';

type AccountAuthorizationSource = Pick<AccountResponse, 'role' | 'scopes'>;

/**
 * Stable namespace version for private browser state and Service Worker caches.
 * Every authentication surface must derive this value identically; otherwise
 * two components can mistake the same session for a permission change and
 * erase durable offline state.
 */
export function accountAuthorizationVersion(account: AccountAuthorizationSource) {
  const authorizationKey = `${account.role}\0${[...account.scopes].sort().join('\0')}`;
  return [...authorizationKey].reduce(
    (value, character) => ((value * 31) + character.charCodeAt(0)) >>> 0,
    1
  );
}
