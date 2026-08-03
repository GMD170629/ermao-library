import assert from 'node:assert/strict';
import test from 'node:test';
import { parseSaveUploadedFilesResponse } from './save-uploaded-files';

test('preserves the stable error code for an unmonitored upload destination', () => {
  assert.deepEqual(
    parseSaveUploadedFilesResponse({
      ok: false,
      error: {
        code: 'UPLOAD_TARGET_NOT_MONITORED',
        message: '上传目录必须位于已启用的监控文件夹中'
      }
    }),
    {
      kind: 'rejected',
      code: 'UPLOAD_TARGET_NOT_MONITORED',
      message: '上传目录必须位于已启用的监控文件夹中'
    }
  );
});
