import { fetch as expoFetch } from 'expo/fetch';

import type { FetchFunction } from '../api/json-transport';

export const expoFetchFunction: FetchFunction = (url, request) =>
  expoFetch(url, request);
