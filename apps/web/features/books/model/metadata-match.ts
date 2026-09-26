import type { SourceNodeMetadataMatch } from './book-contents';

const outcomeLabels: Record<SourceNodeMetadataMatch['outcome'], string> = {
  MATCHED: '匹配',
  AMBIGUOUS: '待确认',
  REJECTED: '已排除',
  NO_MATCH: '未匹配'
};

const levelLabels: Record<SourceNodeMetadataMatch['level'], string> = {
  SERIES: '系列',
  WORK: '作品',
  VOLUME: '卷册',
  EDITION: '版本',
  UNKNOWN: '范围未知'
};

const reasonLabels: Readonly<Record<string, string>> = {
  AUTHOR_CONFLICT: '作者不一致',
  VOLUME_CONFLICT: '卷册不一致',
  EDITION_CONFLICT: '版本不一致',
  TITLE_CONFLICT: '标题不一致',
  INSUFFICIENT_EVIDENCE: '证据不足',
  AI_UNVERIFIED: 'AI 建议未经验证',
  MULTIPLE_MATCHES: '存在多个可能匹配',
  IDENTIFIER_MATCH: '标识符一致',
  TITLE_AUTHOR_MATCH: '标题和作者一致',
  UNKNOWN_SCOPE: '无法确定对应范围',
  INVALID_ISBN: 'ISBN 无效'
};

export function metadataMatchLabels(match: SourceNodeMetadataMatch): Readonly<{ outcome: string; level: string; reasons: string[] }> {
  return {
    outcome: outcomeLabels[match.outcome],
    level: levelLabels[match.level],
    reasons: match.reasons.map((reason) => reasonLabels[reason] ?? '其他匹配原因')
  };
}
