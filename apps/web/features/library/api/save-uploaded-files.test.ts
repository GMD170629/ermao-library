import assert from 'node:assert/strict';
import test from 'node:test';
import { parseSaveUploadedFilesResponse } from './save-uploaded-files';

test('preserves the error code for an upload destination outside a library', () => {
  assert.deepEqual(
    parseSaveUploadedFilesResponse({
      ok: false,
      error: {
        code: 'UPLOAD_TARGET_OUTSIDE_LIBRARY',
        message: '上传目录必须位于已启用的书库中'
      }
    }),
    {
      kind: 'rejected',
      code: 'UPLOAD_TARGET_OUTSIDE_LIBRARY',
      message: '上传目录必须位于已启用的书库中'
    }
  );
});
