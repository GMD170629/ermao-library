export type SystemEventPresentationInput = {
  action: string;
  metadata: Record<string, unknown>;
};

type Translate = (
  message: string,
  values?: Record<string, string | number>,
) => string;

function importIgnoreReasonLabel(reason: unknown, translate: Translate) {
  if (reason === 'temporary_upload') return translate('临时上传文件');
  if (reason === 'hidden_path') return translate('隐藏路径');
  if (reason === 'global_ignore_pattern') return translate('全局忽略规则');
  if (reason === 'library_ignore_pattern') return translate('书库忽略规则');
  if (reason === 'unsupported_file_type') return translate('不支持的文件类型');
  if (reason === 'extension_not_allowed') return translate('扩展名未在允许列表中');
  if (reason === 'below_minimum_size') return translate('文件小于最小导入大小');
  return translate('未知导入规则');
}

export function ignoredImportEventSummary(
  event: SystemEventPresentationInput,
  translate: Translate,
) {
  if (event.action !== 'scan.file.ignored') return null;
  const sourceName = typeof event.metadata.sourceName === 'string'
    ? event.metadata.sourceName
    : translate('未知文件');
  return translate('导入规则忽略文件：{file}（原因：{reason}）', {
    file: sourceName,
    reason: importIgnoreReasonLabel(event.metadata.reason, translate),
  });
}
