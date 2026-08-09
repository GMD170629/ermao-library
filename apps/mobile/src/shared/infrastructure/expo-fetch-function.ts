import { fetch as expoFetch } from 'expo/fetch';

import type { ApiFetchFunction } from '../api/public';

export const expoFetchFunction: ApiFetchFunction = (url, request) =>
  expoFetch(url, request);
