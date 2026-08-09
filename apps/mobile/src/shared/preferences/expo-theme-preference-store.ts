import { File, Paths } from 'expo-file-system';

import {
  decodeThemePreference,
  type ThemePreference,
  type ThemePreferenceStore,
} from './theme-preference';

const MAXIMUM_PREFERENCE_CHARACTERS = 16;

export class ExpoThemePreferenceStore implements ThemePreferenceStore {
  private pendingWrite: Promise<void> = Promise.resolve();

  load(): ThemePreference {
    const file = this.preferenceFile();
    if (!file.exists) return 'system';
    const value = file.textSync();
    return value.length <= MAXIMUM_PREFERENCE_CHARACTERS
      ? decodeThemePreference(value.trim())
      : 'system';
  }

  save(preference: ThemePreference): Promise<void> {
    const write = this.pendingWrite.then(async () => {
      const temporaryFile = this.temporaryFile();
      temporaryFile.create({ intermediates: true, overwrite: true });
      temporaryFile.write(preference);
      const staged = await temporaryFile.text();
      if (decodeThemePreference(staged.trim()) !== preference) {
        throw new Error('Theme preference failed staged validation');
      }
      await temporaryFile.move(this.preferenceFile(), { overwrite: true });
    });
    this.pendingWrite = write.catch(() => undefined);
    return write;
  }

  private preferenceFile(): File {
    return this.file('theme.txt');
  }

  private temporaryFile(): File {
    return this.file('.theme.tmp');
  }

  private file(name: string): File {
    return new File(
      Paths.document,
      'shuku-starship',
      'mobile',
      'v1',
      'preferences',
      name,
    );
  }
}
