import { File } from 'expo-file-system';

import type {
  LibraryFilePicker,
  LibraryFilePickerResult,
} from '../application/ports';

type PickedLibraryFile = Blob &
  Readonly<{
    name: string;
    size: number;
    type: string;
  }>;

export type ExpoLibraryFilePickerResult =
  | Readonly<{ canceled: true; result: null }>
  | Readonly<{
      canceled: false;
      result: readonly PickedLibraryFile[];
    }>;

export type ExpoLibraryFilePickerFunction = () => Promise<
  ExpoLibraryFilePickerResult
>;

async function pickLibraryFiles(): Promise<ExpoLibraryFilePickerResult> {
  return File.pickFileAsync({
    // Several supported ebook/archive formats have no stable platform MIME
    // mapping. The application boundary validates every selected extension.
    mimeTypes: ['*/*'],
    multipleFiles: true,
  });
}

export class ExpoLibraryFilePicker implements LibraryFilePicker {
  constructor(
    private readonly pick: ExpoLibraryFilePickerFunction = pickLibraryFiles,
  ) {}

  async pickFiles(): Promise<LibraryFilePickerResult> {
    try {
      const result = await this.pick();
      if (result.canceled) {
        return { outcome: 'cancelled' };
      }
      if (result.result.length === 0) {
        return { outcome: 'cancelled' };
      }
      return {
        outcome: 'selected',
        files: result.result.map((file) => ({
          name: file.name,
          ...(file.type.length === 0 ? {} : { mimeType: file.type }),
          ...(Number.isFinite(file.size) && file.size >= 0
            ? { sizeBytes: file.size }
            : {}),
          content: file,
        })),
      };
    } catch (cause: unknown) {
      return {
        outcome: 'failed',
        reason:
          cause instanceof Error && cause.name.length > 0
            ? cause.name
            : 'FILE_PICKER_FAILED',
      };
    }
  }
}
