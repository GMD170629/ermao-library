import * as Crypto from 'expo-crypto';

import type { IdGenerator } from '../lib/runtime';

export class ExpoIdGenerator implements IdGenerator {
  nextId(): string {
    return Crypto.randomUUID();
  }
}
